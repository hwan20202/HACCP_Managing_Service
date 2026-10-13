"""LOT number generation from lot_number_rules + lot_number_sequences.

Default rules (BOM v4 mentor scheme, adopted 10/12 — see docs/inventory-decisions.md)
    INCOMING (원료·포장재)   {short_code}{date:yyMMdd}{seq:-N}    AHN261005, AHN261005-2
    PRODUCED (반제품, 기본)  {short_code}{date:yyMMdd}{seq:-N}    BNY261007
    PRODUCED FINISHED        {date:yyMMdd}{shift}{seq:-N}         261011A  (완제품코드와 함께 읽음)

Pattern tokens
    {item_code}          items.item_code
    {short_code}         items.short_code (LOT 약어: A** 원료, B** 반제품, C** 포장재)
    {item_type}          items.item_type (RAW, PACKAGING, ...)
    {shift}              근무조 A 주간 / B 야간 / C 오후 (passed by the caller)
    {date:FMT}           the base date: received date for INCOMING, manufacturing date for
                         PRODUCED. FMT tokens: yyyy, yy, MM, dd  e.g. {date:yyMMdd} -> 261009
    {received:FMT}       same as {date:FMT} (older name, kept for existing rules)
    {seq:-N}             nothing for the first, then -2, -3, ... (a LOT already labelled cannot
                         be renamed, so only the later ones get a suffix)
    {seq:A}              letters: A..Z, AA..AZ, BA.. (no upper limit)
    {seq:000}            zero-padded number, width = number of zeros

LOT numbers are unique per item (UNIQUE(item_id, lot_number)), so the sequence counts per
item: the key is the item code plus the rendered pattern without {seq}. Two finished products
made on the same day and shift both get 261011A; the same product twice gets 261011A-2.
A number that already exists for the item (entered by hand or migrated) is skipped.

Call next_lot_number() inside the caller's transaction.atomic() block (BEGIN IMMEDIATE,
rule S5): the counter increment and the LOT insert then commit or roll back together, and
concurrent writers wait instead of drawing the same number.
"""

import re

from django.db import connection
from django.db.models import Q

from .errors import InventoryError
from .models import Lot, LotNumberRule

_TOKEN = re.compile(r"\{(\w+)(?::([^}]*))?\}")
_DATE_PART = re.compile(r"yyyy|yy|MM|dd")
_MAX_SKIPS = 1000


SHIFTS = {"A": "주간", "B": "야간", "C": "오후"}


class LotNumberError(InventoryError):
    """No usable rule, an invalid pattern, missing input (LOT 약어, 근무조), or the call is
    outside a transaction."""


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
    if fmt == "-N":
        return "" if number == 1 else f"-{number}"
    if fmt == "A":
        return seq_to_letters(number)
    if fmt and set(fmt) == {"0"}:
        return f"{number:0{len(fmt)}d}"
    raise LotNumberError(f"Unknown seq format '{fmt}'. Use {{seq:-N}}, {{seq:A}} or {{seq:000}}.")


def render(pattern, *, item, base_date, seq=None, shift=None):
    """Render a pattern. With seq=None the {seq} token is dropped (gives the sequence key)."""
    seq_tokens = [m for m in _TOKEN.finditer(pattern) if m.group(1) == "seq"]
    if len(seq_tokens) != 1:
        raise LotNumberError(f"Pattern must contain exactly one {{seq:...}} token: {pattern}")

    def replace(match):
        name, fmt = match.group(1), match.group(2)
        if name == "item_code":
            return item.item_code
        if name == "short_code":
            if not item.short_code:
                raise LotNumberError(f"품목 {item.item_code}에 LOT 약어(short_code)가 없습니다.")
            return item.short_code
        if name == "item_type":
            return item.item_type_id
        if name == "shift":
            if shift not in SHIFTS:
                raise LotNumberError(
                    "근무조를 선택하세요 (A 주간 / B 야간 / C 오후)."
                    + (f" (입력: {shift!r})" if shift else "")
                )
            return shift
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


def next_lot_number(*, lot_kind, item, base_date, shift=None):
    """Draw the next LOT number for the item and date (and shift, for patterns with {shift}).
    Must run inside transaction.atomic()."""
    if not connection.in_atomic_block:
        raise LotNumberError("next_lot_number() must run inside transaction.atomic().")
    rule = find_rule(lot_kind=lot_kind, item=item, on_date=base_date)
    seq_key = f"{item.item_code}:" + render(
        rule.pattern, item=item, base_date=base_date, shift=shift
    )
    # A number can already exist if it was entered by hand or migrated. Skip it.
    for _ in range(_MAX_SKIPS):
        lot_number = render(
            rule.pattern, item=item, base_date=base_date, seq=_next_seq(seq_key), shift=shift
        )
        if not Lot.objects.filter(item=item, lot_number=lot_number).exists():
            return lot_number
    raise LotNumberError(f"Could not find a free LOT number for key {seq_key}.")
