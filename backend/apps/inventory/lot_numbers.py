"""LOT number generation from lot_number_rules + lot_number_sequences.

Pattern tokens
    {item_code}          items.item_code
    {item_type}          items.item_type (RAW, PACKAGING, ...)
    {date:FMT}           the base date: received date for INCOMING, manufacturing date for
                         PRODUCED. FMT tokens: yyyy, yy, MM, dd  e.g. {date:yyMMdd} -> 261009
    {received:FMT}       same as {date:FMT} (older name, kept for existing rules)
    {seq:A}              per-key sequence as letters: A..Z, AA..AZ, BA.. (no upper limit)
    {seq:000}            per-key sequence as zero-padded number, width = number of zeros

The sequence key is the rendered pattern without the {seq} token, so the counter restarts
for every item and date: 1000019-261009A, 1000019-261009B, 1000019-261010A, ...

Call next_lot_number() inside the caller's transaction.atomic() block (BEGIN IMMEDIATE,
rule S5): the counter increment and the LOT insert then commit or roll back together, and
concurrent writers wait instead of drawing the same number.
"""

import re

from django.db import connection
from django.db.models import Q

from .models import Lot, LotNumberRule

_TOKEN = re.compile(r"\{(\w+)(?::([^}]*))?\}")
_DATE_PART = re.compile(r"yyyy|yy|MM|dd")
_MAX_SKIPS = 1000


class LotNumberError(Exception):
    """No usable rule, an invalid pattern, or the call is outside a transaction."""


def seq_to_letters(number):
    """1 -> A, 26 -> Z, 27 -> AA, 52 -> AZ, 53 -> BA (bijective base 26)."""
    if number < 1:
        raise ValueError("Sequence starts at 1.")
    letters = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def _format_date(value, fmt):
    parts = {
        "yyyy": f"{value.year:04d}",
        "yy": f"{value.year % 100:02d}",
        "MM": f"{value.month:02d}",
        "dd": f"{value.day:02d}",
    }
    return _DATE_PART.sub(lambda match: parts[match.group(0)], fmt)


def _format_seq(number, fmt):
    if fmt == "A":
        return seq_to_letters(number)
    if fmt and set(fmt) == {"0"}:
        return f"{number:0{len(fmt)}d}"
    raise LotNumberError(f"Unknown seq format '{fmt}'. Use {{seq:A}} or {{seq:000}}.")


def render(pattern, *, item, base_date, seq=None):
    """Render a pattern. With seq=None the {seq} token is dropped (gives the sequence key)."""
    seq_tokens = [m for m in _TOKEN.finditer(pattern) if m.group(1) == "seq"]
    if len(seq_tokens) != 1:
        raise LotNumberError(f"Pattern must contain exactly one {{seq:...}} token: {pattern}")

    def replace(match):
        name, fmt = match.group(1), match.group(2)
        if name == "item_code":
            return item.item_code
        if name == "item_type":
            return item.item_type_id
        if name in {"date", "received"}:
            if not fmt:
                raise LotNumberError("Date token needs a format, e.g. {date:yyMMdd}.")
            return _format_date(base_date, fmt)
        if name == "seq":
            return "" if seq is None else _format_seq(seq, fmt)
        raise LotNumberError(f"Unknown token '{{{name}}}' in pattern: {pattern}")

    return _TOKEN.sub(replace, pattern)


def find_rule(*, lot_kind, item, on_date):
    """Active rule for the kind, preferring one for the item's type over a generic one
    (item_type NULL), and the latest effective_from not after on_date."""
    candidates = LotNumberRule.objects.filter(
        Q(item_type=item.item_type_id) | Q(item_type__isnull=True),
        lot_kind=lot_kind,
        is_active=True,
        effective_from__lte=on_date,
    )
    rules = sorted(
        candidates, key=lambda r: (r.item_type_id is not None, r.effective_from, r.pk), reverse=True
    )
    if not rules:
        raise LotNumberError(
            f"No active {lot_kind} LOT number rule for {item.item_code} on {on_date}."
        )
    return rules[0]


def _next_seq(seq_key):
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO lot_number_sequences (seq_key, current_seq, updated_at) "
            "VALUES (%s, 1, datetime('now', 'localtime')) "
            "ON CONFLICT (seq_key) DO UPDATE SET current_seq = current_seq + 1, "
            "updated_at = datetime('now', 'localtime') "
            "RETURNING current_seq",
            [seq_key],
        )
        return cursor.fetchone()[0]


def next_lot_number(*, lot_kind, item, base_date):
    """Draw the next LOT number for the item and date. Must run inside transaction.atomic()."""
    if not connection.in_atomic_block:
        raise LotNumberError("next_lot_number() must run inside transaction.atomic().")
    rule = find_rule(lot_kind=lot_kind, item=item, on_date=base_date)
    seq_key = render(rule.pattern, item=item, base_date=base_date)
    # A number can already exist if it was entered by hand or migrated. Skip it.
    for _ in range(_MAX_SKIPS):
        lot_number = render(rule.pattern, item=item, base_date=base_date, seq=_next_seq(seq_key))
        if not Lot.objects.filter(item=item, lot_number=lot_number).exists():
            return lot_number
    raise LotNumberError(f"Could not find a free LOT number for key {seq_key}.")
