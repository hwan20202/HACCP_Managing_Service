"""Holds (보류) on LOTs and production batches — sql/0003_holds.sql (10/11 A1 '다' 안, 가정).

    hold_lot()      open hold on one LOT  -> the LOT is not usable (v_lot_availability, I5)
    hold_batch()    open hold on a batch  -> propagated hold on each of its output LOTs, and no new
                    usage / output on the batch while it is open (production.py checks)
    release_hold()  close a hold with a disposition (RELEASE / REWORK / RETURN / DISPOSE).
                    Releasing a batch hold also releases its still-open propagated LOT holds.
                    A propagated hold can be released on its own first (LOT by LOT handling).

The disposition is a record only: returning or disposing the stock is a separate movement
(movements.return_to_supplier / dispose).

Source types that need evidence (hold_source_types.requires_evidence: CCP, INCOMING_INSPECTION,
FINISHED_INSPECTION) need source_document_id = the document app's document_id. The document app
is expected to call hold_batch() when a CCP deviation is recorded (to be agreed). A release
condition on the document side (e.g. 개선조치 완료) is not checked yet.

Every function runs in one transaction (BEGIN IMMEDIATE, rule S5). Messages are user-facing.
"""

from django.db import transaction

from .errors import InventoryError, NotFound
from .models import (
    AuditLog,
    Hold,
    HoldDisposition,
    HoldSourceType,
    Lot,
    ProductionBatch,
    ProductionOutput,
)
from .movements import _occurred_at, _reason, _staff

PROPAGATED = "PROPAGATED"


def _source_type(code, source_document_id):
    source = HoldSourceType.objects.filter(pk=code).first()
    if source is None or code == PROPAGATED:
        choices = sorted(
            HoldSourceType.objects.exclude(pk=PROPAGATED).values_list("code", flat=True)
        )
        raise InventoryError(f"보류 사유 구분은 {choices} 중 하나입니다. (입력: {code!r})")
    if source.requires_evidence and not source_document_id:
        raise InventoryError(f"'{source.name}' 보류는 근거 문서(document_id)가 필요합니다.")
    return source


def _audit(hold, action, staff, reason):
    AuditLog.objects.create(
        table_name="holds",
        record_id=str(hold.pk),
        action=action,
        after_json={
            "lot_id": hold.lot_id,
            "batch_id": hold.batch_id,
            "source_type": hold.source_type_id,
            "parent_hold_id": hold.parent_hold_id,
            "disposition": hold.disposition_id,
        },
        reason=reason,
        staff=staff,
    )


def _existing(**target):
    return Hold.objects.filter(released_at__isnull=True, parent_hold__isnull=True, **target).first()


def hold_lot(*, lot_id, source_type, reason, staff_id, source_document_id=None, held_at=None):
    """Open a hold on a LOT. If the LOT already has an open direct hold, that one is returned."""
    reason = _reason(reason, "보류 사유")
    with transaction.atomic():
        lot = Lot.objects.filter(pk=lot_id).first()
        if lot is None:
            raise NotFound(f"LOT을 찾을 수 없습니다. (id={lot_id})")
        source = _source_type(source_type, source_document_id)
        staff = _staff(staff_id)
        existing = _existing(lot=lot)
        if existing:
            return existing
        hold = Hold.objects.create(
            lot=lot,
            source_type=source,
            source_document_id=source_document_id,
            reason=reason,
            held_by=staff,
            held_at=_occurred_at(held_at),
        )
        _audit(hold, "INSERT", staff, reason)
    return hold


def hold_batch(*, batch_id, source_type, reason, staff_id, source_document_id=None, held_at=None):
    """Open a hold on a batch and propagate it to the batch's output LOTs.

    If the batch already has an open hold, that one is returned (no second propagation).
    """
    reason = _reason(reason, "보류 사유")
    with transaction.atomic():
        batch = ProductionBatch.objects.filter(pk=batch_id).first()
        if batch is None:
            raise NotFound(f"생산 배치를 찾을 수 없습니다. (id={batch_id})")
        source = _source_type(source_type, source_document_id)
        staff = _staff(staff_id)
        existing = _existing(batch=batch)
        if existing:
            return existing
        when = _occurred_at(held_at)
        hold = Hold.objects.create(
            batch=batch,
            source_type=source,
            source_document_id=source_document_id,
            reason=reason,
            held_by=staff,
            held_at=when,
        )
        _audit(hold, "INSERT", staff, reason)
        lot_ids = (
            ProductionOutput.objects.filter(batch=batch).values_list("lot_id", flat=True).distinct()
        )
        for lot in Lot.objects.filter(pk__in=list(lot_ids)):
            child = Hold.objects.create(
                lot=lot,
                source_type_id=PROPAGATED,
                parent_hold=hold,
                source_document_id=source_document_id,
                reason=f"배치 {batch.batch_number} 보류: {reason}",
                held_by=staff,
                held_at=when,
            )
            _audit(child, "INSERT", staff, child.reason)
    return hold


def release_hold(*, hold_id, disposition, reason, staff_id, released_at=None):
    """Release an open hold. A batch hold also releases its still-open propagated holds."""
    reason = _reason(reason, "해제 사유")
    with transaction.atomic():
        hold = Hold.objects.select_related("batch").filter(pk=hold_id).first()
        if hold is None:
            raise NotFound(f"보류를 찾을 수 없습니다. (id={hold_id})")
        if hold.released_at is not None:
            raise InventoryError("이미 해제된 보류입니다.")
        result = HoldDisposition.objects.filter(pk=disposition).first()
        if result is None:
            choices = sorted(HoldDisposition.objects.values_list("code", flat=True))
            raise InventoryError(f"처분은 {choices} 중 하나입니다. (입력: {disposition!r})")
        staff = _staff(staff_id)
        when = _occurred_at(released_at)
        targets = [hold]
        if hold.batch_id:
            targets += list(hold.propagated_holds.filter(released_at__isnull=True))
        for target in targets:
            target.released_by = staff
            target.released_at = when
            target.disposition = result
            target.release_reason = (
                reason if target is hold else f"배치 {hold.batch.batch_number} 보류 해제: {reason}"
            )
            target.save(
                update_fields=["released_by", "released_at", "disposition", "release_reason"]
            )
            _audit(target, "UPDATE", staff, target.release_reason)
    return hold


def open_batch_hold(batch):
    """The open hold on the batch, or None (used by production.py to block usage / output)."""
    return Hold.objects.filter(batch=batch, released_at__isnull=True).first()
