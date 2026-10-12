"""수불 판정 함수의 개발용 임시판 — 수불 `apply_incoming_judgment`와 같은 이름·규칙.

수불 확정본(feature/inventory 2026-10-12)의 규칙을 개발 테이블(lots·dev_lot_receipts)로 흉내 낸다.
개발·테스트 설정의 HACCP_INVENTORY_JUDGMENT 값(p6-s2-spec 4.6 EFF-A1). 수불 통합 때 지운다.

- PASS → AVAILABLE, FAIL → REJECTED. 입고 LOT만, 입고 기록이 있어야 한다.
- 같은 판정이면 변화 없음.
- 이미 판정된 LOT의 판정 변경은 사유 필수, 사용된 LOT은 거부. 개발용에서는 lots.status가
  CONSUMED·DISPOSED면 "판정 적합 + 입고 외 이동 있음"(사용됨)으로 흉내 낸다.
- QUARANTINE·판정 상태가 아니면 거부. 담당자는 staff에 있어야 한다(수불은 is_active도 확인).
"""

import datetime

from django.db import transaction

from apps.staff.models import Staff

from .models import DevLotReceipt, Lot


class InventoryError(Exception):
    """수불 InventoryError와 같은 역할(메시지는 화면에 그대로 보인다)."""


class NotFound(InventoryError):
    pass


TARGET = {"PASS": "AVAILABLE", "FAIL": "REJECTED"}
JUDGED = {"AVAILABLE", "REJECTED"}
USED = {"CONSUMED", "DISPOSED"}  # 개발용 "사용됨" 흉내 — 판정은 적합(AVAILABLE)이었던 것으로 본다


def apply_incoming_judgment(
    *, lot_id, result, staff_id, document_id=None, judged_at=None, reason=None
):
    if result not in TARGET:
        raise InventoryError(f"판정은 {list(TARGET)} 중 하나여야 합니다. (입력: {result!r})")
    reason = (reason or "").strip() or None
    if judged_at is not None and not isinstance(judged_at, datetime.datetime):
        raise InventoryError("판정 일시를 확인하세요.")
    with transaction.atomic():
        lot = Lot.objects.filter(pk=lot_id).first()
        if lot is None:
            raise NotFound(f"LOT을 찾을 수 없습니다. (id={lot_id})")
        if lot.lot_kind != "INCOMING":
            raise InventoryError(f"입고 LOT이 아닙니다: {lot.lot_number}")
        if not DevLotReceipt.objects.filter(lot_id=lot_id).exists():
            raise InventoryError(f"입고 건이 없는 LOT입니다 (기초재고 등): {lot.lot_number}")
        if not Staff.objects.filter(pk=staff_id).exists():
            raise NotFound(f"담당자를 찾을 수 없습니다. (id={staff_id})")
        target = TARGET[result]
        used = lot.status in USED
        current = "AVAILABLE" if used else lot.status
        if current == target:
            return lot
        if current in JUDGED:
            if not reason:
                raise InventoryError("이미 판정된 LOT의 판정을 바꾸려면 사유를 입력하세요.")
            if used:
                raise InventoryError(
                    f"LOT {lot.lot_number}은 이미 사용·조정·반품되어 판정을 바꿀 수 없습니다."
                )
        elif current != "QUARANTINE":
            raise InventoryError(
                f"LOT {lot.lot_number}의 상태({lot.status})에서는 판정을 반영할 수 없습니다."
            )
        lot.status = target
        lot.save(update_fields=["status"])
    return lot
