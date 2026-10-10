"""Stock movement services other than incoming receipts.

    record_opening_balance  기초재고 이관   new LOT + OPENING_BALANCE (go-live stock)
    adjust_stock            재고조정       ADJUST_IN / ADJUST_OUT, reason required
    return_to_supplier      공급처 반품     RETURN_TO_SUPPLIER
    dispose                 폐기           DISPOSAL
    correct_movement        정정           CORRECTION_IN / CORRECTION_OUT against one movement

Every function runs in one transaction (BEGIN IMMEDIATE, rule S5) and is idempotent per
idempotency_key: sending the same request again returns the first movement.

Back-dated outflows are checked against the LOT's balance from that time on, so the running
balance in the stock ledger never goes below zero.
"""

import datetime

from django.db import transaction

from .errors import InventoryError, NotFound
from .fields import KST, kst_now, to_kst_text
from .lot_numbers import next_lot_number
from .models import (
    AuditLog,
    Inventory,
    Item,
    Lot,
    LotKind,
    LotStatus,
    Staff,
    StockMovement,
)
from .quantity import from_e6, to_e6

INCOMING_ITEM_TYPES = {"RAW", "PACKAGING"}
OPENING_STATUSES = {LotStatus.AVAILABLE, LotStatus.QUARANTINE, LotStatus.REJECTED}
# Corrections for receipts go through receiving.cancel_receipt, which keeps the receipt row in step.
NOT_CORRECTABLE = {"RECEIPT", "CORRECTION_IN", "CORRECTION_OUT"}
DIRECTION = {"ADJUST_IN": 1, "ADJUST_OUT": -1, "RETURN_TO_SUPPLIER": -1, "DISPOSAL": -1}


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _staff(staff_id):
    staff = Staff.objects.filter(pk=staff_id).first()
    if staff is None:
        raise NotFound(f"담당자를 찾을 수 없습니다. (id={staff_id})")
    if not staff.is_active:
        raise InventoryError(f"사용 중지된 담당자입니다: {staff}")
    return staff


def _lot(lot_id):
    lot = Lot.objects.select_related("item").filter(pk=lot_id).first()
    if lot is None:
        raise NotFound(f"LOT을 찾을 수 없습니다. (id={lot_id})")
    return lot


def _quantity_e6(quantity):
    try:
        value = to_e6(quantity)
    except (TypeError, ValueError) as error:
        raise InventoryError(f"수량을 확인하세요: {quantity!r} (소수점 6자리까지)") from error
    if value <= 0:
        raise InventoryError("수량은 0보다 커야 합니다.")
    return value


def _reason(reason, label="사유"):
    reason = (reason or "").strip()
    if not reason:
        raise InventoryError(f"{label}를 입력하세요.")
    return reason


def _occurred_at(value):
    """None -> now. A date -> 00:00:00 of that day. Future times are rejected."""
    now = kst_now()
    if value is None:
        return now
    if isinstance(value, datetime.datetime):
        value = value.astimezone(KST) if value.tzinfo else value.replace(tzinfo=KST)
        value = value.replace(microsecond=0)
    elif isinstance(value, datetime.date):
        value = datetime.datetime.combine(value, datetime.time(), tzinfo=KST)
    else:
        raise InventoryError(f"발생 일시를 확인하세요: {value!r}")
    if value > now:
        raise InventoryError("발생 일시가 현재 이후일 수 없습니다.")
    return value


def _key(prefix, idempotency_key):
    if not idempotency_key:
        raise InventoryError("요청 키(idempotency_key)가 필요합니다.")
    return f"{prefix}:{idempotency_key}"


def _replay(key, lot_id, type_code, quantity_e6):
    """Return the movement already recorded for this key, or None."""
    movement = StockMovement.objects.filter(idempotency_key=key).first()
    if movement is None:
        return None
    same = (
        (lot_id is None or movement.lot_id == lot_id)
        and movement.movement_type_id == type_code
        and (quantity_e6 is None or movement.quantity_e6 == quantity_e6)
    )
    if not same:
        raise InventoryError("같은 요청 키로 다른 내용의 처리가 이미 등록되어 있습니다.")
    return movement


def current_stock_e6(lot_id):
    return (
        Inventory.objects.filter(lot_id=lot_id).values_list("quantity_e6", flat=True).first() or 0
    )


def _available_from(lot_id, occurred_at):
    """Largest outflow possible at occurred_at without any running balance going negative."""
    stamp = to_kst_text(occurred_at)
    rows = (
        StockMovement.objects.filter(lot_id=lot_id)
        .order_by("occurred_at", "pk")
        .values_list("occurred_at", "quantity_e6", "movement_type__direction")
    )
    balance, before, after = 0, None, []
    for when, quantity, direction in rows:
        balance += quantity * direction
        if to_kst_text(when) <= stamp:
            before = balance
        else:
            after.append(balance)
    return min([before or 0, *after])


def _check_outflow(lot, quantity_e6, occurred_at):
    available = _available_from(lot.pk, occurred_at)
    if quantity_e6 > available:
        raise InventoryError(
            f"재고가 부족합니다. LOT {lot.lot_number}: 요청 {from_e6(quantity_e6)}, "
            f"가능 {from_e6(available)} {lot.item.base_unit}"
        )


def _set_lot_status(lot, status, staff, reason):
    if lot.status == status:
        return
    before = {"status": lot.status}
    lot.status = status
    lot.save(update_fields=["status"])
    AuditLog.objects.create(
        table_name="lots",
        record_id=str(lot.pk),
        action="UPDATE",
        before_json=before,
        after_json={"status": status},
        reason=reason,
        staff=staff,
    )


def _status_before_disposed(lot):
    """Status the LOT had before it was marked DISPOSED (from the audit log)."""
    log = (
        AuditLog.objects.filter(
            table_name="lots", record_id=str(lot.pk), after_json__status=LotStatus.DISPOSED
        )
        .order_by("-pk")
        .first()
    )
    return (log and log.before_json.get("status")) or LotStatus.AVAILABLE


def _create(lot, type_code, quantity_e6, staff, occurred_at, key, reason=None, corrects=None):
    return StockMovement.objects.create(
        lot=lot,
        movement_type_id=type_code,
        quantity_e6=quantity_e6,
        corrects_movement=corrects,
        staff=staff,
        occurred_at=occurred_at,
        reason=reason,
        idempotency_key=key,
    )


# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------


def record_opening_balance(
    *,
    item_id,
    quantity,
    staff_id,
    occurred_at,
    idempotency_key,
    lot_number=None,
    manufactured_date=None,
    expiration_date=None,
    status=LotStatus.AVAILABLE,
    reason=None,
):
    """Create a LOT for stock that existed before go-live and record OPENING_BALANCE.

    lot_number: the existing LOT number. Blank -> numbered by the INCOMING rule
    (RAW / PACKAGING only). occurred_at: usually the go-live date (required).
    """
    if occurred_at is None:
        raise InventoryError("기초재고 기준일을 입력하세요.")
    if status not in OPENING_STATUSES:
        raise InventoryError(f"기초재고 LOT 상태는 {sorted(OPENING_STATUSES)} 중 하나여야 합니다.")
    quantity_e6 = _quantity_e6(quantity)
    key = _key("OPENING", idempotency_key)
    if manufactured_date and expiration_date and expiration_date < manufactured_date:
        raise InventoryError("소비기한이 제조일보다 빠를 수 없습니다.")

    with transaction.atomic():
        existing = _replay(key, None, "OPENING_BALANCE", quantity_e6)
        if existing:
            return existing
        item = Item.objects.filter(pk=item_id).first()
        if item is None:
            raise NotFound(f"품목을 찾을 수 없습니다. (id={item_id})")
        staff = _staff(staff_id)
        when = _occurred_at(occurred_at)
        kind = LotKind.INCOMING if item.item_type_id in INCOMING_ITEM_TYPES else LotKind.PRODUCED
        lot_number = (lot_number or "").strip()
        if not lot_number:
            if kind != LotKind.INCOMING:
                raise InventoryError("반제품·완제품의 기초재고는 기존 LOT 번호를 입력하세요.")
            lot_number = next_lot_number(lot_kind=kind, item=item, base_date=when.date())
        if Lot.objects.filter(item=item, lot_number=lot_number).exists():
            raise InventoryError(f"이미 있는 LOT 번호입니다: {item.item_code} / {lot_number}")
        lot = Lot.objects.create(
            lot_number=lot_number,
            item=item,
            lot_kind=kind,
            status=status,
            manufactured_date=manufactured_date,
            expiration_date=expiration_date,
        )
        return _create(
            lot, "OPENING_BALANCE", quantity_e6, staff, when, key, reason or "기초재고 이관"
        )


def _outflow_or_adjust(type_code, prefix, *, lot_id, quantity, reason, staff_id, key, at):
    reason = _reason(reason)
    key = _key(prefix, key)
    with transaction.atomic():
        lot = _lot(lot_id)
        quantity_e6 = current_stock_e6(lot.pk) if quantity is None else _quantity_e6(quantity)
        existing = _replay(key, lot.pk, type_code, None if quantity is None else quantity_e6)
        if existing:
            return existing
        if quantity_e6 <= 0:
            raise InventoryError(f"LOT {lot.lot_number}의 재고가 없습니다.")
        staff = _staff(staff_id)
        when = _occurred_at(at)
        if DIRECTION[type_code] < 0:
            _check_outflow(lot, quantity_e6, when)
        movement = _create(lot, type_code, quantity_e6, staff, when, key, reason)
        if type_code in {"RETURN_TO_SUPPLIER", "DISPOSAL"} and current_stock_e6(lot.pk) == 0:
            _set_lot_status(lot, LotStatus.DISPOSED, staff, reason)
        return movement


def adjust_stock(
    *, lot_id, direction, quantity, reason, staff_id, idempotency_key, occurred_at=None
):
    """direction: 'IN' (ADJUST_IN) or 'OUT' (ADJUST_OUT). Reason is required."""
    codes = {"IN": "ADJUST_IN", "OUT": "ADJUST_OUT"}
    if direction not in codes:
        raise InventoryError("조정 방향은 IN 또는 OUT 이어야 합니다.")
    if quantity is None:
        raise InventoryError("조정 수량을 입력하세요.")
    return _outflow_or_adjust(
        codes[direction],
        "ADJUST",
        lot_id=lot_id,
        quantity=quantity,
        reason=reason,
        staff_id=staff_id,
        key=idempotency_key,
        at=occurred_at,
    )


def return_to_supplier(
    *, lot_id, reason, staff_id, idempotency_key, quantity=None, occurred_at=None
):
    """quantity None -> the whole remaining stock. Empty LOT afterwards -> status DISPOSED."""
    return _outflow_or_adjust(
        "RETURN_TO_SUPPLIER",
        "RETURN",
        lot_id=lot_id,
        quantity=quantity,
        reason=reason,
        staff_id=staff_id,
        key=idempotency_key,
        at=occurred_at,
    )


def dispose(*, lot_id, reason, staff_id, idempotency_key, quantity=None, occurred_at=None):
    """quantity None -> the whole remaining stock. Empty LOT afterwards -> status DISPOSED."""
    return _outflow_or_adjust(
        "DISPOSAL",
        "DISPOSAL",
        lot_id=lot_id,
        quantity=quantity,
        reason=reason,
        staff_id=staff_id,
        key=idempotency_key,
        at=occurred_at,
    )


def correct_movement(*, movement_id, reason, staff_id, idempotency_key, quantity=None):
    """Offset all or part of a mistaken movement with a CORRECTION in the opposite direction.

    The original stays (I2). quantity None -> everything not yet corrected. The correction is
    dated at the original's time so the ledger shows the corrected balance from that point.
    Receipts are corrected with receiving.cancel_receipt instead.
    """
    reason = _reason(reason, "정정 사유")
    key = _key("CORRECTION", idempotency_key)
    with transaction.atomic():
        original = (
            StockMovement.objects.select_related("lot__item", "movement_type")
            .filter(pk=movement_id)
            .first()
        )
        if original is None:
            raise NotFound(f"수불 기록을 찾을 수 없습니다. (id={movement_id})")
        if original.movement_type_id in NOT_CORRECTABLE:
            hint = (
                " 입고는 입고 취소를 사용하세요." if original.movement_type_id == "RECEIPT" else ""
            )
            raise InventoryError(f"이 유형은 정정할 수 없습니다: {original.movement_type}.{hint}")
        type_code = "CORRECTION_OUT" if original.movement_type.direction > 0 else "CORRECTION_IN"
        corrected = sum(original.corrections.values_list("quantity_e6", flat=True), start=0)
        remaining = original.quantity_e6 - corrected
        quantity_e6 = remaining if quantity is None else _quantity_e6(quantity)
        existing = _replay(
            key, original.lot_id, type_code, None if quantity is None else quantity_e6
        )
        if existing:
            return existing
        if quantity_e6 <= 0 or quantity_e6 > remaining:
            raise InventoryError(
                f"정정 가능한 수량을 넘었습니다. (원 기록 {from_e6(original.quantity_e6)}, "
                f"남은 정정 가능 {from_e6(remaining)})"
            )
        staff = _staff(staff_id)
        lot = original.lot
        if type_code == "CORRECTION_OUT":
            _check_outflow(lot, quantity_e6, original.occurred_at)
        movement = _create(
            lot, type_code, quantity_e6, staff, original.occurred_at, key, reason, original
        )
        if lot.status == LotStatus.DISPOSED and current_stock_e6(lot.pk) > 0:
            _set_lot_status(lot, _status_before_disposed(lot), staff, f"정정: {reason}")
        return movement
