"""Incoming visual inspection judgment -> LOT status.

Called directly by the document app when an inspection record is completed (agreed: direct
service calls; status changes only on 작성완료, not on approval or rejection of approval).

    PASS -> AVAILABLE
    FAIL -> REJECTED   (a FAIL LOT is returned in full; record that with
                        movements.return_to_supplier, which also marks the LOT DISPOSED)

Re-judgment (the record was corrected and completed again):
    PASS -> FAIL  only while the LOT is untouched (no movement other than its RECEIPT)
    FAIL -> PASS  only while it has not been returned or disposed
Sending the same result again changes nothing.
"""

import datetime

from django.db import models, transaction

from .errors import InventoryError, NotFound
from .fields import kst_now, to_kst_text
from .models import AuditLog, IncomingReceipt, Lot, LotKind, LotStatus, Staff, StockMovement


class Judgment(models.TextChoices):
    PASS = "PASS", "적합"
    FAIL = "FAIL", "부적합"


STATUS_FOR = {Judgment.PASS: LotStatus.AVAILABLE, Judgment.FAIL: LotStatus.REJECTED}
JUDGED_STATUSES = {LotStatus.AVAILABLE, LotStatus.REJECTED}


def _staff(staff_id):
    staff = Staff.objects.filter(pk=staff_id).first()
    if staff is None:
        raise NotFound(f"담당자를 찾을 수 없습니다. (id={staff_id})")
    if not staff.is_active:
        raise InventoryError(f"사용 중지된 담당자입니다: {staff}")
    return staff


def apply_incoming_judgment(
    *, lot_id, result, staff_id, document_id=None, judged_at=None, reason=None
):
    """Set an incoming LOT's status from the inspection result. Returns the LOT."""
    if result not in Judgment.values:
        raise InventoryError(f"판정은 {Judgment.values} 중 하나여야 합니다. (입력: {result!r})")
    reason = (reason or "").strip() or None
    if judged_at is not None and not isinstance(judged_at, datetime.datetime):
        raise InventoryError("판정 일시를 확인하세요.")

    with transaction.atomic():
        lot = Lot.objects.select_related("item").filter(pk=lot_id).first()
        if lot is None:
            raise NotFound(f"LOT을 찾을 수 없습니다. (id={lot_id})")
        if lot.lot_kind != LotKind.INCOMING:
            raise InventoryError(f"입고 LOT이 아닙니다: {lot.lot_number}")
        receipt = IncomingReceipt.objects.filter(lot=lot).first()
        if receipt is None:
            raise InventoryError(f"입고 건이 없는 LOT입니다 (기초재고 등): {lot.lot_number}")
        if receipt.receipt_status == "CANCELLED":
            raise InventoryError(f"취소된 입고의 LOT입니다: {lot.lot_number}")
        staff = _staff(staff_id)

        target = STATUS_FOR[result]
        if lot.status == target:
            return lot
        if lot.status in JUDGED_STATUSES:
            if not reason:
                raise InventoryError("이미 판정된 LOT의 판정을 바꾸려면 사유를 입력하세요.")
            touched = StockMovement.objects.filter(lot=lot).exclude(pk=receipt.stock_movement_id)
            if touched.exists():
                raise InventoryError(
                    f"LOT {lot.lot_number}은 이미 사용·조정·반품되어 판정을 바꿀 수 없습니다."
                )
        elif lot.status != LotStatus.QUARANTINE:
            raise InventoryError(
                f"LOT {lot.lot_number}의 상태({lot.get_status_display()})에서는 "
                "판정을 반영할 수 없습니다."
            )

        before = {"status": lot.status}
        lot.status = target
        lot.save(update_fields=["status"])
        AuditLog.objects.create(
            table_name="lots",
            record_id=str(lot.pk),
            action="UPDATE",
            before_json=before,
            after_json={
                "status": target,
                "judgment": result,
                "document_id": document_id,
                "judged_at": to_kst_text(judged_at or kst_now()),
            },
            reason=reason or f"입고 육안검사 {Judgment(result).label}",
            staff=staff,
        )
    return lot
