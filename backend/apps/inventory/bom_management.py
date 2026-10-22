"""Versioned BOM authoring. Used recipes are immutable; replacement is a new version."""

import datetime

from django.db import transaction
from django.db.models import Max

from .errors import InventoryError, NotFound
from .models import AuditLog, Bom, BomLine, BomLineAlternative, Item, ProductionBatch
from .movements import _staff
from .quantity import to_e6


def integer(value, label):
    if isinstance(value, bool) or not str(value).isdigit() or int(value) < 1:
        raise InventoryError(f"{label}: 양의 정수를 입력하세요.")
    return int(value)


def quantity(value, unit, base_unit):
    try:
        amount = to_e6(value)
    except (ValueError, TypeError, ArithmeticError) as error:
        raise InventoryError("수량은 소수점 6자리 이내 숫자로 입력하세요.") from error
    if unit != base_unit:
        if {unit, base_unit} != {"kg", "g"}:
            raise InventoryError("품목 기준단위 또는 kg/g 단위를 사용하세요.")
        if unit == "g":
            if amount % 1000:
                raise InventoryError("kg 환산 후 소수점 6자리를 초과합니다.")
            amount //= 1000
        else:
            amount *= 1000
    if amount <= 0 or amount > 9_000_000_000_000_000_000:
        raise InventoryError("수량은 저장 가능한 범위의 양수여야 합니다.")
    return amount


def snapshot(bom):
    return {
        "item_id": bom.item_id,
        "version": bom.version,
        "base_quantity_e6": bom.base_quantity_e6,
        "effective_from": str(bom.effective_from),
        "is_active": bom.is_active,
        "notes": bom.notes,
        "lines": [
            {
                "item_id": line.component_item_id,
                "quantity_e6": line.quantity_e6,
                "alternatives": list(line.alternatives.values_list("item_id", flat=True)),
            }
            for line in bom.lines.order_by("line_no")
        ],
    }


@transaction.atomic
def save_bom(data, bom_id=None):
    staff = _staff(integer(data.get("staff_id"), "담당자"))
    old = None
    if bom_id is not None:
        old = Bom.objects.filter(pk=bom_id).first()
        if old is None:
            raise NotFound("BOM을 찾을 수 없습니다.")
    item_id = integer(data.get("item_id"), "생산 품목")
    item = Item.objects.filter(pk=item_id, is_active=True, item_type_id="SEMI").first()
    if item is None:
        raise InventoryError("사용 중인 반제품 품목을 선택하세요.")
    if old and old.item_id != item.pk:
        raise InventoryError("기존 BOM의 생산 품목을 변경할 수 없습니다.")
    try:
        effective = datetime.date.fromisoformat(str(data.get("effective_from", "")))
    except ValueError as error:
        raise InventoryError("적용 시작일을 입력하세요.") from error
    active = data.get("is_active", True)
    if not isinstance(active, bool):
        raise InventoryError("사용 여부는 참/거짓이어야 합니다.")
    base = quantity(
        data.get("base_quantity"), data.get("base_unit", item.base_unit), item.base_unit
    )
    raw_lines = data.get("lines")
    if not isinstance(raw_lines, list) or not 1 <= len(raw_lines) <= 200:
        raise InventoryError("구성 원료를 1~200개 입력하세요.")
    lines, seen = [], set()
    for row in raw_lines:
        if not isinstance(row, dict):
            raise InventoryError("구성 원료 형식을 확인하세요.")
        component_id = integer(row.get("item_id"), "구성 품목")
        component = Item.objects.filter(pk=component_id, is_active=True).first()
        if component is None or component.pk == item.pk or component.pk in seen:
            raise InventoryError("구성 품목이 없거나 중복되거나 생산 품목과 같습니다.")
        seen.add(component.pk)
        amount = quantity(
            row.get("quantity"), row.get("unit", component.base_unit), component.base_unit
        )
        alternatives = row.get("alternatives", [])
        if not isinstance(alternatives, list) or len(alternatives) > 50:
            raise InventoryError("대체 원료 목록을 확인하세요.")
        ids = [integer(value, "대체 원료") for value in alternatives]
        if len(set(ids)) != len(ids) or item.pk in ids or component.pk in ids:
            raise InventoryError("대체 원료가 중복되거나 생산·기본 원료와 같습니다.")
        alternatives = list(Item.objects.filter(pk__in=ids, is_active=True))
        if len(alternatives) != len(ids):
            raise InventoryError("사용할 수 없는 대체 원료입니다.")
        for alternative in alternatives:
            if alternative.base_unit != component.base_unit and {
                alternative.base_unit,
                component.base_unit,
            } != {"kg", "g"}:
                raise InventoryError("대체 원료는 기본 원료와 환산 가능한 단위여야 합니다.")
        lines.append((component, amount, alternatives))
    used = old and ProductionBatch.objects.filter(bom=old).exists()
    before = snapshot(old) if old else None
    if used or data.get("new_version") or old is None:
        version = (Bom.objects.filter(item=item).aggregate(last=Max("version"))["last"] or 0) + 1
        bom = Bom.objects.create(
            item=item,
            version=version,
            base_quantity_e6=base,
            effective_from=effective,
            is_active=active,
            notes=str(data.get("notes") or "").strip() or None,
            created_by=staff,
        )
    else:
        bom = old
        BomLineAlternative.objects.filter(bom_line__bom=bom).delete()
        BomLine.objects.filter(bom=bom).delete()
        bom.base_quantity_e6 = base
        bom.effective_from = effective
        bom.is_active = active
        bom.notes = str(data.get("notes") or "").strip() or None
        bom.save()
    for index, (component, amount, alternatives) in enumerate(lines, 1):
        line = BomLine.objects.create(
            bom=bom, line_no=index, component_item=component, quantity_e6=amount
        )
        for alternative in alternatives:
            BomLineAlternative.objects.create(bom_line=line, item=alternative)
    AuditLog.objects.create(
        table_name="boms",
        record_id=str(bom.pk),
        action="UPDATE" if bom is old else "INSERT",
        before_json=before,
        after_json=snapshot(bom),
        reason=str(data.get("reason") or "BOM 저장"),
        staff=staff,
    )
    return bom


@transaction.atomic
def delete_bom(bom_id, data):
    staff = _staff(integer(data.get("staff_id"), "담당자"))
    bom = Bom.objects.filter(pk=bom_id).first()
    if bom is None:
        raise NotFound("BOM을 찾을 수 없습니다.")
    before = snapshot(bom)
    used = ProductionBatch.objects.filter(bom=bom).exists()
    if used:
        bom.is_active = False
        bom.save(update_fields=["is_active"])
    else:
        BomLineAlternative.objects.filter(bom_line__bom=bom).delete()
        BomLine.objects.filter(bom=bom).delete()
        bom.delete()
    AuditLog.objects.create(
        table_name="boms",
        record_id=str(bom_id),
        action="UPDATE" if used else "DELETE",
        before_json=before,
        after_json={"is_active": False} if used else None,
        reason=str(data.get("reason") or "BOM 삭제"),
        staff=staff,
    )
    return {"deleted": not used, "deactivated": bool(used)}
