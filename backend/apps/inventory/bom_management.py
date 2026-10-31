"""Versioned BOM authoring. Used recipes are immutable; replacement is a new version."""

from django.db import transaction
from django.db.models import Max

from .errors import InventoryError, NotFound
from .fields import kst_now
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


def deactivate_other_versions(bom, staff):
    """Switch the default for future plans without changing existing batch references.

    Call this BEFORE the chosen version is saved as active: the DB allows at most one active
    version per item (ux_boms_one_active_per_item), so the old one must be off first.
    """
    others = Bom.objects.select_for_update().filter(item_id=bom.item_id, is_active=True)
    if bom.pk is not None:
        others = others.exclude(pk=bom.pk)
    others = list(others)
    for other in others:
        before = snapshot(other)
        other.is_active = False
        other.save(update_fields=["is_active"])
        AuditLog.objects.create(
            table_name="boms",
            record_id=str(other.pk),
            action="UPDATE",
            before_json=before,
            after_json=snapshot(other),
            reason=f"v{bom.version} 활성화로 기본 BOM 변경",
            staff=staff,
        )
    return bool(others)


def update_metadata(bom, data, staff):
    before = snapshot(bom)
    active = data.get("is_active", bom.is_active)
    if not isinstance(active, bool):
        raise InventoryError("사용 여부는 참/거짓이어야 합니다.")
    notes = str(data.get("notes", bom.notes) or "").strip() or None
    switched = deactivate_other_versions(bom, staff) if active else False
    if active == bom.is_active and notes == bom.notes and not switched:
        raise InventoryError("변경된 내용이 없습니다.")
    bom.is_active, bom.notes = active, notes
    bom.save(update_fields=["is_active", "notes"])
    AuditLog.objects.create(
        table_name="boms",
        record_id=str(bom.pk),
        action="UPDATE",
        before_json=before,
        after_json=snapshot(bom),
        reason=str(data.get("reason") or "BOM 상태·메모 변경"),
        staff=staff,
    )
    return bom


@transaction.atomic
def save_bom(data, bom_id=None):
    staff = _staff(integer(data.get("staff_id"), "담당자"))
    old = None
    if bom_id is not None:
        old = Bom.objects.select_for_update().filter(pk=bom_id).first()
        if old is None:
            raise NotFound("BOM을 찾을 수 없습니다.")
        Item.objects.select_for_update().get(pk=old.item_id)
        if set(data) <= {"staff_id", "is_active", "notes", "reason", "new_version"}:
            return update_metadata(old, data, staff)
    item_id = integer(data.get("item_id"), "생산 품목")
    item = (
        Item.objects.select_for_update()
        .filter(pk=item_id, is_active=True, item_type_id="SEMI")
        .first()
    )
    if item is None:
        raise InventoryError("사용 중인 반제품 품목을 선택하세요.")
    if old and old.item_id != item.pk:
        raise InventoryError("기존 BOM의 생산 품목을 변경할 수 없습니다.")
    # 적용 시작일은 입력받지 않는다 (10-31): 활성 버전이 품목당 하나라 예약 적용이 필요 없다.
    # 새 버전은 등록일을, 덮어쓰기는 기존 날짜를 기록한다. 요청의 effective_from 은 무시한다.
    effective = old.effective_from if old else kst_now().date()
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
    overwrite = data.get("overwrite", False)
    if not isinstance(overwrite, bool):
        raise InventoryError("덮어쓰기 여부는 참/거짓이어야 합니다.")
    if overwrite and data.get("new_version"):
        raise InventoryError("새 버전 저장과 덮어쓰기를 동시에 선택할 수 없습니다.")
    before = snapshot(old) if old else None
    if old:
        # Compare normalized quantities and sets, not display units or row order.
        previous = sorted(
            (row["item_id"], row["quantity_e6"], sorted(row["alternatives"]))
            for row in before["lines"]
        )
        current = sorted(
            (component.pk, amount, sorted(a.pk for a in alternatives))
            for component, amount, alternatives in lines
        )
        recipe_changed = base != old.base_quantity_e6 or current != previous
        if not recipe_changed:
            return update_metadata(old, data, staff)
        if used and overwrite:
            raise InventoryError(
                "생산 연결 이력이 있는 버전은 덮어쓸 수 없습니다. 새 버전으로 저장하세요."
            )
    if used or data.get("new_version") or old is None:
        version = (Bom.objects.filter(item=item).aggregate(last=Max("version"))["last"] or 0) + 1
        bom = Bom(
            item=item,
            version=version,
            base_quantity_e6=base,
            effective_from=kst_now().date(),
            is_active=active,
            notes=str(data.get("notes") or "").strip() or None,
            created_by=staff,
        )
        if active:
            deactivate_other_versions(bom, staff)
        bom.save(force_insert=True)
    else:
        bom = old
        BomLineAlternative.objects.filter(bom_line__bom=bom).delete()
        BomLine.objects.filter(bom=bom).delete()
        bom.base_quantity_e6 = base
        bom.effective_from = effective
        bom.is_active = active
        bom.notes = str(data.get("notes") or "").strip() or None
        if active:
            deactivate_other_versions(bom, staff)
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
