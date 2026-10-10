"""Incoming receipt registration and cancellation (C2: one receipt = one LOT).

register_receipt():  lots(QUARANTINE) -> stock_movements(RECEIPT) -> incoming_receipts
                     -> audit_logs -> document_bridge hook          (one transaction)
cancel_receipt():    stock_movements(CORRECTION_OUT, full quantity) -> receipt CANCELLED
                     -> audit_logs -> document_bridge hook          (one transaction)

Both run in transaction.atomic(), which settings turn into BEGIN IMMEDIATE (rule S5).
Messages in ReceivingError are shown to users, so they are in Korean.
"""

import datetime
from dataclasses import dataclass

from django.db import transaction

from . import document_bridge
from .errors import InventoryError, NotFound
from .fields import KST, kst_now
from .lot_numbers import next_lot_number
from .models import (
    AuditLog,
    IncomingReceipt,
    Inventory,
    Item,
    Lot,
    LotKind,
    LotStatus,
    ReceiptStatus,
    Staff,
    StockMovement,
    Supplier,
)
from .quantity import from_e6, to_e6

RECEIVABLE_ITEM_TYPES = {"RAW", "PACKAGING"}


class ReceivingError(InventoryError):
    """A receipt request that cannot be applied. The message is user-facing (Korean)."""


class ReceiptNotFound(ReceivingError, NotFound):
    pass


@dataclass(frozen=True)
class ReceiptInput:
    item_id: int
    supplier_id: int
    staff_id: int
    received_date: datetime.date
    quantity: object  # Decimal / int / str in the item's base unit, converted with to_e6
    idempotency_key: str  # one per form submission (e.g. a UUID made by the screen)
    supplier_lot_number: str | None = None
    manufactured_date: datetime.date | None = None
    expiration_date: datetime.date | None = None


def _active(model, pk, label):
    obj = model.objects.filter(pk=pk).first()
    if obj is None:
        raise ReceivingError(f"{label}을(를) 찾을 수 없습니다. (id={pk})")
    if not obj.is_active:
        raise ReceivingError(f"사용 중지된 {label}입니다: {obj}")
    return obj


def _quantity_e6(quantity):
    try:
        value = to_e6(quantity)
    except (TypeError, ValueError) as error:
        raise ReceivingError(f"수량을 확인하세요: {quantity!r} (소수점 6자리까지)") from error
    if value <= 0:
        raise ReceivingError("수량은 0보다 커야 합니다.")
    return value


def _occurred_at(received_date):
    """Today -> now. A past date (late entry) -> 00:00:00 of that day, so the receipt sorts
    before anything else done with the LOT on that day in the stock ledger."""
    now = kst_now()
    if received_date > now.date():
        raise ReceivingError("입고일이 오늘 이후일 수 없습니다.")
    if received_date == now.date():
        return now
    return datetime.datetime.combine(received_date, datetime.time(), tzinfo=KST)


def _receipt_snapshot(receipt):
    return {
        "lot_id": receipt.lot_id,
        "supplier_id": receipt.supplier_id,
        "supplier_lot_number": receipt.supplier_lot_number,
        "received_date": receipt.received_date.isoformat(),
        "quantity_e6": receipt.quantity_e6,
        "staff_id": receipt.staff_id,
        "stock_movement_id": receipt.stock_movement_id,
        "receipt_status": receipt.receipt_status,
        "cancel_reason": receipt.cancel_reason,
    }


def _existing_receipt(idempotency_key, data, quantity_e6):
    """Same submission sent twice (double click, retry): return the first result."""
    movement = StockMovement.objects.filter(idempotency_key=f"RECEIPT:{idempotency_key}").first()
    if movement is None:
        return None
    receipt = IncomingReceipt.objects.select_related("lot").get(stock_movement=movement)
    if receipt.lot.item_id != data.item_id or receipt.quantity_e6 != quantity_e6:
        raise ReceivingError("같은 요청 키로 다른 내용의 입고가 이미 등록되어 있습니다.")
    return receipt


def register_receipt(data: ReceiptInput) -> IncomingReceipt:
    if not data.idempotency_key:
        raise ReceivingError("요청 키(idempotency_key)가 필요합니다.")
    quantity_e6 = _quantity_e6(data.quantity)
    if (
        data.manufactured_date
        and data.expiration_date
        and data.expiration_date < data.manufactured_date
    ):
        raise ReceivingError("소비기한이 제조일보다 빠를 수 없습니다.")

    with transaction.atomic():
        existing = _existing_receipt(data.idempotency_key, data, quantity_e6)
        if existing:
            return existing

        item = _active(Item, data.item_id, "품목")
        if item.item_type_id not in RECEIVABLE_ITEM_TYPES:
            raise ReceivingError(f"입고 대상 품목이 아닙니다: {item} ({item.item_type_id})")
        supplier = _active(Supplier, data.supplier_id, "공급처")
        staff = _active(Staff, data.staff_id, "담당자")
        occurred_at = _occurred_at(data.received_date)

        lot = Lot.objects.create(
            lot_number=next_lot_number(
                lot_kind=LotKind.INCOMING, item=item, base_date=data.received_date
            ),
            item=item,
            lot_kind=LotKind.INCOMING,
            status=LotStatus.QUARANTINE,
            manufactured_date=data.manufactured_date,
            expiration_date=data.expiration_date,
        )
        movement = StockMovement.objects.create(
            lot=lot,
            movement_type_id="RECEIPT",
            quantity_e6=quantity_e6,
            staff=staff,
            occurred_at=occurred_at,
            idempotency_key=f"RECEIPT:{data.idempotency_key}",
        )
        receipt = IncomingReceipt.objects.create(
            lot=lot,
            supplier=supplier,
            supplier_lot_number=(data.supplier_lot_number or "").strip() or None,
            received_date=data.received_date,
            quantity_e6=quantity_e6,
            staff=staff,
            stock_movement=movement,
        )
        AuditLog.objects.create(
            table_name="incoming_receipts",
            record_id=str(receipt.pk),
            action="INSERT",
            after_json=_receipt_snapshot(receipt),
            staff=staff,
        )
        document_bridge.incoming_received(lot_id=lot.pk)
    return receipt


def cancel_receipt(*, receipt_id: int, staff_id: int, reason: str) -> IncomingReceipt:
    """Cancel a receipt whose LOT is still untouched (stock = received quantity).

    The RECEIPT movement stays (I2); a CORRECTION_OUT of the full quantity offsets it.
    Cancelling an already cancelled receipt returns it unchanged.
    """
    reason = (reason or "").strip()
    if not reason:
        raise ReceivingError("취소 사유를 입력하세요.")

    with transaction.atomic():
        receipt = (
            IncomingReceipt.objects.select_related("lot", "stock_movement")
            .filter(pk=receipt_id)
            .first()
        )
        if receipt is None:
            raise ReceiptNotFound(f"입고 건을 찾을 수 없습니다. (id={receipt_id})")
        if receipt.receipt_status == ReceiptStatus.CANCELLED:
            return receipt
        staff = _active(Staff, staff_id, "담당자")

        stock = Inventory.objects.filter(lot=receipt.lot).values_list("quantity_e6", flat=True)
        current = stock.first() or 0
        if current != receipt.quantity_e6:
            raise ReceivingError(
                "이미 사용·조정된 LOT은 입고 취소할 수 없습니다. "
                f"(입고 {from_e6(receipt.quantity_e6)}, 현재 {from_e6(current)})"
            )

        before = _receipt_snapshot(receipt)
        now = kst_now()
        StockMovement.objects.create(
            lot=receipt.lot,
            movement_type_id="CORRECTION_OUT",
            quantity_e6=receipt.quantity_e6,
            corrects_movement=receipt.stock_movement,
            staff=staff,
            occurred_at=now,
            reason=f"입고 취소: {reason}",
            # One cancellation per receipt; the unique key also stops a concurrent double cancel.
            idempotency_key=f"RECEIPT_CANCEL:{receipt.pk}",
        )
        receipt.receipt_status = ReceiptStatus.CANCELLED
        receipt.cancelled_at = now
        receipt.cancel_reason = reason
        receipt.save(update_fields=["receipt_status", "cancelled_at", "cancel_reason"])
        AuditLog.objects.create(
            table_name="incoming_receipts",
            record_id=str(receipt.pk),
            action="UPDATE",
            before_json=before,
            after_json=_receipt_snapshot(receipt),
            reason=reason,
            staff=staff,
        )
        document_bridge.incoming_receipt_cancelled(
            lot_id=receipt.lot_id, reason=reason, staff_id=staff.pk
        )
    return receipt
