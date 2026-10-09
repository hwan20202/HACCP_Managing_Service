"""Master data import (staff, suppliers, items) and default LOT number rules.

Rows are dicts keyed by the CSV header names below. Existing rows are matched by code
and updated; new codes are created. Nothing is deleted. Rows are validated first and the
whole import is rejected if any row is invalid, so a file is applied all or nothing.

    staff.csv      staff_code*, name*, is_active
    suppliers.csv  supplier_code*, name*, is_active
    items.csv      item_code*, item_type*, name*, base_unit*, short_code, unit_weight_mg,
                   shelf_life_days, origin_country, food_type, minimum_stock, is_active

(* required)  item_type: RAW / PACKAGING / SEMI / FINISHED.  minimum_stock is in the base
unit (e.g. 12.5 for 12.5 kg) and is stored as minimum_stock_e6.  is_active: 1/0, Y/N,
true/false; blank means 1.
"""

import datetime
from dataclasses import dataclass, field

from django.db import IntegrityError, transaction

from .models import Item, ItemType, LotKind, LotNumberRule, Staff, Supplier
from .quantity import to_e6

DEFAULT_INCOMING_PATTERN = "{item_code}-{received:yyMMdd}{seq:A}"
DEFAULT_RULE_EFFECTIVE_FROM = datetime.date(2026, 1, 1)

_TRUE = {"1", "y", "yes", "true", "t", "사용"}
_FALSE = {"0", "n", "no", "false", "f", "미사용"}


class MasterImportError(Exception):
    def __init__(self, label, errors):
        self.label = label
        self.errors = errors
        super().__init__(f"{label}: {len(errors)} invalid row(s)\n" + "\n".join(errors))


@dataclass
class ImportResult:
    label: str
    created: list = field(default_factory=list)
    updated: list = field(default_factory=list)

    def __str__(self):
        return f"{self.label}: created {len(self.created)}, updated {len(self.updated)}"


def _text(row, key, required=False):
    value = (row.get(key) or "").strip()
    if required and not value:
        raise ValueError(f"'{key}' is required")
    return value or None


def _bool(row, key):
    value = (row.get(key) or "").strip().lower()
    if not value or value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise ValueError(f"'{key}' must be 1/0, Y/N or true/false (got '{row.get(key)}')")


def _positive_int(row, key):
    value = _text(row, key)
    if value is None:
        return None
    try:
        number = int(value.replace(",", ""))
    except ValueError as error:
        raise ValueError(f"'{key}' must be a whole number (got '{value}')") from error
    if number <= 0:
        raise ValueError(f"'{key}' must be greater than 0")
    return number


def _parse_rows(rows, label, parse):
    """Parse every row first; collect all errors with CSV line numbers (header = line 1)."""
    parsed, errors, seen = [], [], {}
    for line, row in enumerate(rows, start=2):
        try:
            values = parse(row)
        except ValueError as error:
            errors.append(f"  line {line}: {error}")
            continue
        code = values["code"]
        if code in seen:
            errors.append(f"  line {line}: duplicate code '{code}' (also line {seen[code]})")
            continue
        seen[code] = line
        parsed.append((line, values))
    if errors:
        raise MasterImportError(label, errors)
    return parsed


def _upsert(model, code_field, parsed, label):
    result = ImportResult(label)
    errors = []
    for line, values in parsed:
        code = values.pop("code")
        try:
            with transaction.atomic():
                _, created = model.objects.update_or_create(**{code_field: code}, defaults=values)
        except IntegrityError as error:
            errors.append(f"  line {line}: '{code}' rejected by the database: {error}")
            continue
        (result.created if created else result.updated).append(code)
    if errors:
        raise MasterImportError(label, errors)
    return result


def import_staff(rows):
    def parse(row):
        return {
            "code": _text(row, "staff_code", required=True),
            "name": _text(row, "name", required=True),
            "is_active": _bool(row, "is_active"),
        }

    return _upsert(Staff, "staff_code", _parse_rows(rows, "staff", parse), "staff")


def import_suppliers(rows):
    def parse(row):
        return {
            "code": _text(row, "supplier_code", required=True),
            "name": _text(row, "name", required=True),
            "is_active": _bool(row, "is_active"),
        }

    return _upsert(Supplier, "supplier_code", _parse_rows(rows, "suppliers", parse), "suppliers")


def import_items(rows):
    item_types = set(ItemType.objects.values_list("code", flat=True))

    def parse(row):
        item_type = (_text(row, "item_type", required=True) or "").upper()
        if item_type not in item_types:
            raise ValueError(f"'item_type' must be one of {sorted(item_types)} (got '{item_type}')")
        minimum_stock = _text(row, "minimum_stock")
        try:
            minimum_stock_e6 = to_e6(minimum_stock.replace(",", "")) if minimum_stock else 0
        except ValueError as error:
            raise ValueError(f"'minimum_stock': {error}") from error
        if minimum_stock_e6 < 0:
            raise ValueError("'minimum_stock' cannot be negative")
        return {
            "code": _text(row, "item_code", required=True),
            "item_type_id": item_type,
            "name": _text(row, "name", required=True),
            "base_unit": _text(row, "base_unit", required=True),
            "short_code": _text(row, "short_code"),
            "unit_weight_mg": _positive_int(row, "unit_weight_mg"),
            "shelf_life_days": _positive_int(row, "shelf_life_days"),
            "origin_country": _text(row, "origin_country"),
            "food_type": _text(row, "food_type"),
            "minimum_stock_e6": minimum_stock_e6,
            "is_active": _bool(row, "is_active"),
        }

    return _upsert(Item, "item_code", _parse_rows(rows, "items", parse), "items")


def ensure_default_lot_rules():
    """Create the default INCOMING rule when no active INCOMING rule exists. Returns it or None."""
    if LotNumberRule.objects.filter(lot_kind=LotKind.INCOMING, is_active=True).exists():
        return None
    return LotNumberRule.objects.create(
        lot_kind=LotKind.INCOMING,
        item_type=None,
        pattern=DEFAULT_INCOMING_PATTERN,
        effective_from=DEFAULT_RULE_EFFECTIVE_FROM,
        notes="기본 입고 LOT 규칙 (seed_master 생성)",
    )
