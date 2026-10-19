"""Incoming receipt registration and cancellation (C2: one receipt = one LOT).

register_receipt():  lots(QUARANTINE) -> stock_movements(RECEIPT) -> incoming_receipts
                     -> audit_logs -> document_bridge hook (D01·D02·D03)
                     -> judgment (if given, linked to the D03)      (one transaction)
cancel_receipt():    stock_movements(CORRECTION_OUT, rest of the quantity) -> receipt CANCELLED
                     -> audit_logs -> document_bridge hook          (one transaction)
                     Refused while a LOT document is in approval / approved / being corrected.

Both run in transaction.atomic(), which settings turn into BEGIN IMMEDIATE (rule S5).
Messages in ReceivingError are shown to users, so they are in Korean.
"""

import datetime
from dataclasses import dataclass

from django.db import transaction

from . import document_bridge
from .errors import InventoryError, NotFound
from .expiration import incoming_number_date, resolve_status
from .fields import KST, kst_now
from .judgment import Judgment, apply_incoming_judgment
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
from .movements import not_stock_managed_error
from .quantity import from_e6, to_e6

# 반제품도 사 온다 (10/14 PM 미팅 D2). 구매 반제품 LOT 규칙은 INCOMING SEMI (0005, 가정)
RECEIVABLE_ITEM_TYPES = {"RAW", "PACKAGING", "SEMI"}


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
    # 소비기한 유무: KNOWN(있음) / NONE(없음) / UNKNOWN(미확인). Blank + a date -> KNOWN.
    # Raw materials must be KNOWN or NONE: KNOWN is numbered by 소비기한, NONE by 입고일 (0007).
    expiration_status: str | None = None
    # Visual inspection done with the receipt: PASS / FAIL. None = not decided yet (the LOT
    # stays QUARANTINE until the inspection record is completed).
    judgment: str | None = None
    # Visual inspection values entered with the receipt, passed to the document app's D03
    # (keys and options: document side 2.1/2.2). None = filled in later on the document.
    inspection: dict | None = None


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
    judgment = _receipt_judgment(data)
    quantity_e6 = _quantity_e6(data.quantity)
    if (
        data.manufactured_date
        and data.expiration_date
        and data.expiration_date < data.manufactured_date
    ):
        raise ReceivingError("소비기한이 제조일보다 빠를 수 없습니다.")
    expiration_status = resolve_status(
        data.expiration_status, data.expiration_date, error=ReceivingError
    )

    with transaction.atomic():
        existing = _existing_receipt(data.idempotency_key, data, quantity_e6)
        if existing:
            existing.documents = None
            return existing

        item = _active(Item, data.item_id, "품목")
        if item.item_type_id not in RECEIVABLE_ITEM_TYPES:
            raise ReceivingError(f"입고 대상 품목이 아닙니다: {item} ({item.item_type_id})")
        if not item.is_stock_managed:
            raise not_stock_managed_error(item)
        supplier = _active(Supplier, data.supplier_id, "공급처")
        staff = _active(Staff, data.staff_id, "담당자")
        occurred_at = _occurred_at(data.received_date)
        expiration_status, number_date = incoming_number_date(
            item, expiration_status, data.expiration_date, data.received_date, error=ReceivingError
        )

        lot = Lot.objects.create(
            lot_number=next_lot_number(
                lot_kind=LotKind.INCOMING,
                item=item,
                base_date=number_date,
                rule_date=data.received_date,
            ),
            item=item,
            lot_kind=LotKind.INCOMING,
            status=LotStatus.QUARANTINE,
            manufactured_date=data.manufactured_date,
            expiration_date=data.expiration_date,
            expiration_status=expiration_status,
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
        # Document app first (D01 · D02 · D03, the inspection values go into the new D03), then the
        # judgment, linked to that D03 (document side 2.1: LOT judgment is applied by inventory).
        documents = document_bridge.incoming_received(
            lot_id=lot.pk, staff_id=staff.pk, inspection=data.inspection
        )
        if judgment:
            apply_incoming_judgment(
                lot_id=lot.pk,
                result=judgment,
                staff_id=staff.pk,
                document_id=_inspection_document_id(documents),
            )
            lot.refresh_from_db(fields=["status", "updated_at"])
    # What the document app returned for this receipt (not stored; None for a repeated request).
    receipt.documents = documents
    return receipt


def _receipt_judgment(data):
    """The receipt's judgment: ReceiptInput.judgment, or the verdict of the inspection values
    entered with it. Both given -> they must agree (document side 2.1)."""
    judgment = data.judgment
    if judgment is not None and judgment not in Judgment.values:
        raise ReceivingError(f"육안검사 판정은 {Judgment.values} 중 하나여야 합니다.")
    if data.inspection is None:
        return judgment
    if not isinstance(data.inspection, dict):
        raise ReceivingError("육안검사 입력(inspection)은 항목: 값 형식이어야 합니다.")
    verdict = data.inspection.get("verdict")
    if judgment is not None and verdict not in (None, "", judgment):
        raise ReceivingError(f"입고 판정({judgment})과 육안검사 최종판정({verdict})이 다릅니다.")
    return judgment or verdict or None


def _inspection_document_id(documents):
    for document in (documents or {}).get("documents", []):
        if document.get("type_code") == "D03":
            return document.get("document_id")
    return None


def cancel_receipt(*, receipt_id: int, staff_id: int, reason: str) -> IncomingReceipt:
    """Cancel a receipt whose LOT is still untouched (stock = received quantity, net of any
    partial receipt corrections).

    The RECEIPT movement stays (I2); a CORRECTION_OUT of the rest of the quantity offsets it.
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
        corrected = sum(
            receipt.stock_movement.corrections.values_list("quantity_e6", flat=True), start=0
        )
        received = receipt.quantity_e6 - corrected
        if current != received:
            raise ReceivingError(
                "이미 사용·조정된 LOT은 입고 취소할 수 없습니다. "
                f"(입고 {from_e6(received)}, 현재 {from_e6(current)})"
            )

        blockers = document_bridge.receipt_cancel_blockers(lot_id=receipt.lot_id)
        if blockers:
            listed = ", ".join(f"{code}({status})" for code, status in blockers)
            raise ReceivingError(
                f"결재 중이거나 결재된 문서가 있는 LOT은 입고 취소할 수 없습니다: {listed}"
            )

        before = _receipt_snapshot(receipt)
        now = kst_now()
        StockMovement.objects.create(
            lot=receipt.lot,
            movement_type_id="CORRECTION_OUT",
            quantity_e6=received,
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
