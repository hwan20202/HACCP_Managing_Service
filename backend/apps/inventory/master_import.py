"""Master data import (staff, suppliers, items) and default LOT number rules.

Rows are dicts keyed by the CSV header names below. Existing rows are matched by code
and updated; new codes are created. Nothing is deleted. Rows are validated first and the
whole import is rejected if any row is invalid, so a file is applied all or nothing.

    staff.csv      staff_code*, name*, is_active
    suppliers.csv  supplier_code*, name*, is_active
    items.csv      item_code*, item_type*, name*, base_unit*, short_code, unit_weight_mg,
                   shelf_life_months, shelf_life_days, origin_country, food_type,
                   minimum_stock, is_stock_managed, is_active   (소비기한은 개월·일수 중 하나만)

(* required)  item_type: RAW / PACKAGING / SEMI / FINISHED.  minimum_stock is in the base
unit (e.g. 12.5 for 12.5 kg) and is stored as minimum_stock_e6.  is_active: 1/0, Y/N,
true/false; blank means 1. is_stock_managed: 0 for 정제수 같은 공정용수 (LOT·재고 없음), same
values as is_active, blank means 1.
"""

import datetime
from dataclasses import dataclass, field

from django.db import IntegrityError, transaction

from .models import Item, ItemType, LotKind, LotNumberRule, Staff, Supplier
from .quantity import to_e6

# 원료·포장재: BOM v4 멘토안 (같은 날 같은 품목이 또 생기면 -2, -3, 가정)
# 반제품·완제품: 제조일(생산 시작일) + 품목별 생산 순번 (v6.1, 근무조 폐지 10/14)
DEFAULT_INCOMING_PATTERN = "{short_code}{date:yyMMdd}{seq:-N}"  # LOT 약어 + 입고일
DEFAULT_INCOMING_SEMI_PATTERN = "{date:yyMMdd}{seq:A}"  # 구매 반제품: 입고일 + 순번 (가정)
DEFAULT_PRODUCED_PATTERN = "{date:yyMMdd}{seq:A}"  # 제조일 + 품목별 생산 순번 (반제품)
DEFAULT_FINISHED_PATTERN = "{date:yyMMdd}{seq:A}"  # 제조일 + 품목별 생산 순번 (완제품)
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


def _raw(row, key):
    value = row.get(key)
    return "" if value is None else str(value).strip()


def _text(row, key, required=False):
    value = _raw(row, key)
    if required and not value:
        raise ValueError(f"'{key}' 값이 필요합니다")
    return value or None


def _bool(row, key):
    value = _raw(row, key).lower()
    if not value or value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise ValueError(f"'{key}' 는 1/0, Y/N, true/false 중 하나여야 합니다 (입력: '{row.get(key)}')")


def _positive_int(row, key):
    value = _text(row, key)
    if value is None:
        return None
    try:
        number = int(value.replace(",", ""))
    except ValueError as error:
        raise ValueError(f"'{key}' 는 정수여야 합니다 (입력: '{value}')") from error
    if number <= 0:
        raise ValueError(f"'{key}' 는 0보다 커야 합니다")
    return number


def parse_staff_row(row):
    return {
        "code": _text(row, "staff_code", required=True),
        "name": _text(row, "name", required=True),
        "is_active": _bool(row, "is_active"),
    }


def parse_supplier_row(row):
    return {
        "code": _text(row, "supplier_code", required=True),
        "name": _text(row, "name", required=True),
        "is_active": _bool(row, "is_active"),
    }


def parse_item_row(row, item_types=None):
    item_types = item_types or set(ItemType.objects.values_list("code", flat=True))
    item_type = (_text(row, "item_type", required=True) or "").upper()
    if item_type not in item_types:
        raise ValueError(
            f"'item_type' 은 {sorted(item_types)} 중 하나여야 합니다 (입력: '{item_type}')"
        )
    minimum_stock = _text(row, "minimum_stock")
    try:
        minimum_stock_e6 = to_e6(minimum_stock.replace(",", "")) if minimum_stock else 0
    except (TypeError, ValueError) as error:
        raise ValueError(f"'minimum_stock' 값을 확인하세요: {error}") from error
    if minimum_stock_e6 < 0:
        raise ValueError("'minimum_stock' 은 음수일 수 없습니다")
    shelf_life_months = _positive_int(row, "shelf_life_months")
    shelf_life_days = _positive_int(row, "shelf_life_days")
    if shelf_life_months and shelf_life_days:
        raise ValueError(
            "소비기한은 'shelf_life_months'(개월)와 'shelf_life_days'(일) 중 하나만 입력하세요"
        )
    return {
        "code": _text(row, "item_code", required=True),
        "item_type_id": item_type,
        "name": _text(row, "name", required=True),
        "base_unit": _text(row, "base_unit", required=True),
        "short_code": _text(row, "short_code"),
        "unit_weight_mg": _positive_int(row, "unit_weight_mg"),
        "shelf_life_months": shelf_life_months,
        "shelf_life_days": shelf_life_days,
        "origin_country": _text(row, "origin_country"),
        "food_type": _text(row, "food_type"),
        "minimum_stock_e6": minimum_stock_e6,
        "is_stock_managed": _bool(row, "is_stock_managed"),
        "is_active": _bool(row, "is_active"),
    }


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
            errors.append(f"  line {line}: 코드 '{code}' 중복 ({seen[code]}행과 같음)")
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
            errors.append(f"  line {line}: '{code}' 저장 실패 (DB 제약 위반): {error}")
            continue
        (result.created if created else result.updated).append(code)
    if errors:
        raise MasterImportError(label, errors)
    return result


def import_staff(rows):
    return _upsert(Staff, "staff_code", _parse_rows(rows, "staff", parse_staff_row), "staff")


def import_suppliers(rows):
    parsed = _parse_rows(rows, "suppliers", parse_supplier_row)
    return _upsert(Supplier, "supplier_code", parsed, "suppliers")


def import_items(rows):
    item_types = set(ItemType.objects.values_list("code", flat=True))
    parsed = _parse_rows(rows, "items", lambda row: parse_item_row(row, item_types))
    return _upsert(Item, "item_code", parsed, "items")


def ensure_default_lot_rules():
    """Create each default rule whose (kind, item type) has no active rule. Returns new rules."""
    defaults = [
        (LotKind.INCOMING, None, DEFAULT_INCOMING_PATTERN, "기본 입고 LOT 규칙 (seed_master 생성)"),
        (
            LotKind.INCOMING,
            "SEMI",
            DEFAULT_INCOMING_SEMI_PATTERN,
            "구매 반제품 LOT: 입고일 + 순번 (가정)",
        ),
        (LotKind.PRODUCED, "SEMI", DEFAULT_PRODUCED_PATTERN, "반제품 LOT: 제조일 + 생산 순번"),
        (
            LotKind.PRODUCED,
            "FINISHED",
            DEFAULT_FINISHED_PATTERN,
            "완제품 LOT: 제조일 + 생산 순번 (근무조 폐지)",
        ),
    ]
    created = []
    for kind, item_type, pattern, notes in defaults:
        if LotNumberRule.objects.filter(
            lot_kind=kind, item_type_id=item_type, is_active=True
        ).exists():
            continue
        created.append(
            LotNumberRule.objects.create(
                lot_kind=kind,
                item_type_id=item_type,
                pattern=pattern,
                effective_from=DEFAULT_RULE_EFFECTIVE_FROM,
                notes=notes,
            )
        )
    return created
