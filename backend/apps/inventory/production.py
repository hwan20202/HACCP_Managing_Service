"""Production services: batches, material usage, output LOTs (sql/0002_production.sql).

MVP 범위 (10/15): 입고부터 제조 완료된 벌크(반제품) 산출까지. 물류 소분·포장·출고와 포장배치는
제외한다 — 새 포장배치는 만들 수 없고(0006 트리거), 예전 포장배치에는 시작·투입·산출을 더할 수
없다(취소·완료로 닫기만). 한 제조배치의 산출은 제조 시작일로 채번한 LOT 하나: 산출을 추가하면
같은 LOT 에 수량이 더해진다.

Flow (사후 입력 중심 — a batch can be created and completed on the same screen):

    create_batch()     PLANNED      batch number B-{item_code}-{yyMMdd}{A..}
    start_batch()      IN_PROGRESS  started_at; manufactured_date = 생산 시작일 (LOT·소비기한 기준);
                                    document app is told (CCP 일지 작성 요구)
    add_usage()        PRODUCTION_USE movement + production_material_usages row
    add_output()       PRODUCTION_OUTPUT movement + production_outputs row. The first output
                                    creates the batch's PRODUCED LOT; later ones add to it
    complete_batch()   COMPLETED    needs output (net > 0). From PLANNED (사후 입력) it also
                                    tells the document app, as start_batch would have
    cancel_batch()     CANCELLED    only when every usage / output has been corrected to 0

제조일(manufactured_date) = 생산 시작일 (10/14 PM 미팅 B1·B2·C2). LOT 번호와 소비기한은 이 날짜로
정한다. 사후 입력(계획 상태에서 바로 산출)은 배치 등록 때 제조일을 넣어야 산출할 수 있다.
근무조(shift)는 10/14 폐지: 서비스·API 에서 받지 않는다 (DB 열은 문서 뷰 계약 때문에 NULL 로 남김).

A batch on hold (holds.py) takes no new usage or output until the hold is released.

Usage and output rows are append-only (DB triggers). A wrong entry is fixed by correcting its
stock movement with movements.correct_movement(); the views net it out (v_batch_usages).

Every function runs in one transaction (BEGIN IMMEDIATE, rule S5). add_usage / add_output are
idempotent per idempotency_key: the same request again returns the first row.
Messages in InventoryError are shown to users, so they are in Korean.
"""

from django.db import connection, transaction

from . import document_bridge
from .errors import InventoryError, NotFound
from .fields import kst_now
from .holds import open_batch_hold
from .lot_numbers import _next_seq, next_lot_number, seq_to_letters
from .models import (
    AuditLog,
    BatchStatus,
    Bom,
    BomLine,
    BomLineAlternative,
    Item,
    Lot,
    LotKind,
    LotStatus,
    ProcessType,
    ProductionBatch,
    ProductionMaterialUsage,
    ProductionOutput,
    StockMovement,
)
from .movements import (
    _check_outflow,
    _key,
    _lot,
    _occurred_at,
    _quantity_e6,
    _reason,
    _staff,
    current_stock_e6,
)
from .shelf_life import expiration_for

OPEN_STATUSES = {BatchStatus.PLANNED, BatchStatus.IN_PROGRESS}
# 제조배치를 만들 수 있는 품목 유형. 현재 기준정보 분류(v6.1: 자사 제조품 = 3코드 반제품,
# 4코드 완제품 = 판매 단위)에 따른 구현 제한이며 확정 업무 규칙은 아님 — 분류가 바뀌면 여기만 고침
PRODUCIBLE_ITEM_TYPES = {"SEMI"}
PACKAGING_OUT_OF_SCOPE = "포장배치는 이번 범위(입고 ~ 제조 벌크 산출)에서 제외되었습니다."


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _batch(batch_id, *, lock_open=False):
    batch = ProductionBatch.objects.select_related("item").filter(pk=batch_id).first()
    if batch is None:
        raise NotFound(f"생산 배치를 찾을 수 없습니다. (id={batch_id})")
    if lock_open and batch.process_type == ProcessType.PACKAGING:
        raise InventoryError(f"{PACKAGING_OUT_OF_SCOPE} 투입·산출을 추가할 수 없습니다.")
    if lock_open and batch.status not in OPEN_STATUSES:
        raise InventoryError(
            f"배치 {batch.batch_number}은(는) {batch.get_status_display()} 상태라 "
            "투입·산출을 추가할 수 없습니다."
        )
    if lock_open and (hold := open_batch_hold(batch)):
        raise InventoryError(
            f"배치 {batch.batch_number}은(는) 보류 중이라 투입·산출을 추가할 수 없습니다. "
            f"(보류 사유: {hold.reason})"
        )
    return batch


def _audit(batch, action, staff, before=None, reason=None):
    AuditLog.objects.create(
        table_name="production_batches",
        record_id=str(batch.pk),
        action=action,
        before_json=before,
        after_json={
            "status": batch.status,
            "manufactured_date": (
                batch.manufactured_date.isoformat() if batch.manufactured_date else None
            ),
        },
        reason=reason,
        staff=staff,
    )


def _next_batch_number(item, base_date):
    """B-{item_code}-{yyMMdd}{A,B,..} (10/11 미팅 A4 제안, 가정)."""
    prefix = f"B-{item.item_code}-{base_date:%y%m%d}"
    for _ in range(1000):
        candidate = prefix + seq_to_letters(_next_seq(f"BATCH:{prefix}"))
        if not ProductionBatch.objects.filter(batch_number=candidate).exists():
            return candidate
    raise InventoryError(f"배치 번호를 만들 수 없습니다: {prefix}")


def batch_output_lot(batch):
    """The batch's output LOT, or None before the first output.

    Batches made before 10/15 may have several (1:N 시절, 예전 포장배치). They take no more output.
    """
    lot_ids = list(
        ProductionOutput.objects.filter(batch=batch).values_list("lot_id", flat=True).distinct()
    )
    if len(lot_ids) > 1:
        raise InventoryError(
            f"배치 {batch.batch_number}은(는) 산출 LOT이 여러 개인 예전 기록이라 "
            "산출을 추가할 수 없습니다."
        )
    return Lot.objects.get(pk=lot_ids[0]) if lot_ids else None


def _default_bom(item, on_date):
    return (
        Bom.objects.filter(item=item, is_active=True, effective_from__lte=on_date)
        .order_by("-effective_from", "-version")
        .first()
    )


def _net(model, batch):
    """Sum of (quantity - corrections) for the batch's usage or output rows."""
    view = "v_batch_usages" if model is ProductionMaterialUsage else "v_batch_outputs"
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT COALESCE(SUM(net_quantity_e6), 0), COUNT(*) FROM {view} WHERE batch_id = %s",
            [batch.pk],
        )
        return cursor.fetchone()


def _usable(lot):
    with connection.cursor() as cursor:
        cursor.execute("SELECT is_usable FROM v_lot_availability WHERE lot_id = %s", [lot.pk])
        row = cursor.fetchone()
    return bool(row and row[0])


# ---------------------------------------------------------------------------
# Batches
# ---------------------------------------------------------------------------


def create_batch(
    *,
    item_id,
    staff_id,
    process_type=ProcessType.MANUFACTURE,
    planned_date=None,
    planned_quantity=None,
    manufactured_date=None,
    bom_id=None,
    notes=None,
):
    """New PLANNED manufacturing batch for a 반제품 (bulk). The BOM defaults to the item's active
    one. Packaging batches are out of scope (10/15)."""
    if process_type == ProcessType.PACKAGING:
        raise InventoryError(PACKAGING_OUT_OF_SCOPE)
    if process_type != ProcessType.MANUFACTURE:
        raise InventoryError("공정 구분은 MANUFACTURE(제조)만 가능합니다.")
    planned_e6 = _quantity_e6(planned_quantity) if planned_quantity not in (None, "") else None
    today = kst_now().date()
    if manufactured_date and manufactured_date > today:
        raise InventoryError("제조일이 오늘 이후일 수 없습니다.")

    with transaction.atomic():
        item = Item.objects.filter(pk=item_id).first()
        if item is None:
            raise NotFound(f"품목을 찾을 수 없습니다. (id={item_id})")
        if not item.is_active:
            raise InventoryError(f"사용 중지된 품목입니다: {item}")
        if item.item_type_id not in PRODUCIBLE_ITEM_TYPES:
            raise InventoryError(
                f"현재 기준정보 분류에서 제조배치는 반제품 품목만 만들 수 있습니다: {item} "
                f"({item.item_type_id})"
            )
        staff = _staff(staff_id)
        base_date = manufactured_date or planned_date or today
        if bom_id:
            bom = Bom.objects.filter(pk=bom_id).first()
            if bom is None or bom.item_id != item.pk:
                raise InventoryError("이 품목의 BOM이 아닙니다.")
        else:
            bom = _default_bom(item, base_date)
        batch = ProductionBatch.objects.create(
            batch_number=_next_batch_number(item, base_date),
            process_type=process_type,
            item=item,
            bom=bom,
            status=BatchStatus.PLANNED,
            planned_date=planned_date,
            planned_quantity_e6=planned_e6,
            manufactured_date=manufactured_date,
            staff=staff,
            notes=(notes or "").strip() or None,
        )
        _audit(batch, "INSERT", staff)
    return batch


def start_batch(*, batch_id, staff_id, started_at=None, manufactured_date=None):
    """PLANNED -> IN_PROGRESS. Starting an already started batch returns it unchanged.

    manufactured_date (생산 시작일) defaults to the start day; a date set at creation is kept."""
    with transaction.atomic():
        batch = _batch(batch_id)
        if batch.status == BatchStatus.IN_PROGRESS:
            return batch
        if batch.status != BatchStatus.PLANNED:
            raise InventoryError(f"계획 상태의 배치만 시작할 수 있습니다: {batch.batch_number}")
        if batch.process_type == ProcessType.PACKAGING:
            raise InventoryError(PACKAGING_OUT_OF_SCOPE)
        staff = _staff(staff_id)
        when = _occurred_at(started_at)
        before = {"status": batch.status}
        batch.status = BatchStatus.IN_PROGRESS
        batch.started_at = when
        batch.manufactured_date = manufactured_date or batch.manufactured_date or when.date()
        if batch.manufactured_date > when.date():
            raise InventoryError("제조일(생산 시작일)이 시작 시각보다 늦을 수 없습니다.")
        batch.save(update_fields=["status", "started_at", "manufactured_date"])
        _audit(batch, "UPDATE", staff, before, "생산 시작")
        document_bridge.batch_started(batch_id=batch.pk, staff_id=staff.pk)
    return batch


def complete_batch(*, batch_id, staff_id, completed_at=None):
    """IN_PROGRESS (or PLANNED, for after-the-fact entry) -> COMPLETED."""
    with transaction.atomic():
        batch = _batch(batch_id)
        if batch.status == BatchStatus.COMPLETED:
            return batch
        if batch.status not in OPEN_STATUSES:
            raise InventoryError(f"취소된 배치는 완료할 수 없습니다: {batch.batch_number}")
        staff = _staff(staff_id)
        output_e6, _rows = _net(ProductionOutput, batch)
        if output_e6 <= 0:
            raise InventoryError("산출이 없는 배치는 완료할 수 없습니다. 산출을 먼저 등록하세요.")
        when = _occurred_at(completed_at)
        if not batch.manufactured_date:  # an output exists, so add_output already required it
            raise InventoryError("제조일(생산 시작일)이 없는 배치는 완료할 수 없습니다.")
        skipped_start = batch.status == BatchStatus.PLANNED
        before = {"status": batch.status}
        batch.status = BatchStatus.COMPLETED
        batch.completed_at = when
        batch.started_at = batch.started_at or when
        batch.save(update_fields=["status", "completed_at", "started_at"])
        _audit(batch, "UPDATE", staff, before, "생산 완료")
        if skipped_start:  # entered after the fact: the document app still needs its records
            document_bridge.batch_started(batch_id=batch.pk, staff_id=staff.pk)
    return batch


def cancel_batch(*, batch_id, staff_id, reason):
    """Cancel a batch that has nothing left in it (every usage / output corrected to 0)."""
    reason = _reason(reason, "취소 사유")
    with transaction.atomic():
        batch = _batch(batch_id)
        if batch.status == BatchStatus.CANCELLED:
            return batch
        if batch.status == BatchStatus.COMPLETED:
            raise InventoryError("완료된 배치는 취소할 수 없습니다. 투입·산출을 정정하세요.")
        staff = _staff(staff_id)
        used_e6, _ = _net(ProductionMaterialUsage, batch)
        output_e6, _ = _net(ProductionOutput, batch)
        if used_e6 or output_e6:
            raise InventoryError(
                "투입·산출 기록이 남아 있는 배치는 취소할 수 없습니다. "
                "먼저 수불 정정으로 0을 만드세요."
            )
        before = {"status": batch.status}
        batch.status = BatchStatus.CANCELLED
        batch.cancelled_at = kst_now()
        batch.cancel_reason = reason
        batch.save(update_fields=["status", "cancelled_at", "cancel_reason"])
        _audit(batch, "UPDATE", staff, before, reason)
    return batch


# ---------------------------------------------------------------------------
# Usage / output
# ---------------------------------------------------------------------------


def _component_quantity(quantity_e6, source_unit, target_unit):
    """Convert mass units exactly; other units must match the BOM component unit."""
    if source_unit == target_unit:
        return quantity_e6
    factors = {"kg": 1000, "g": 1}
    if source_unit not in factors or target_unit not in factors:
        raise InventoryError("대체 원료와 BOM 구성 품목의 단위를 환산할 수 없습니다.")
    value, remainder = divmod(quantity_e6 * factors[source_unit], factors[target_unit])
    if remainder:
        raise InventoryError("대체 원료 환산 수량은 기준단위 소수점 6자리 이내여야 합니다.")
    return value


def add_usage(
    *,
    batch_id,
    lot_id,
    quantity,
    staff_id,
    idempotency_key,
    occurred_at=None,
    bom_line_id=None,
):
    """Record an input LOT used by the batch (actual quantity, in the LOT item's base unit).

    The LOT must be usable (AVAILABLE, no open hold), not expired on the day of use and have
    enough stock at that time (back-dated entries are checked against later movements).
    """
    quantity_e6 = _quantity_e6(quantity)
    key = _key("USE", idempotency_key)
    with transaction.atomic():
        existing = ProductionMaterialUsage.objects.filter(stock_movement__idempotency_key=key)
        if existing.exists():
            usage = existing.get()
            if (usage.batch_id, usage.lot_id, usage.quantity_e6) != (
                batch_id,
                lot_id,
                quantity_e6,
            ):
                raise InventoryError("같은 요청 키로 다른 내용의 투입이 이미 등록되어 있습니다.")
            return usage
        batch = _batch(batch_id, lock_open=True)
        lot = _lot(lot_id)
        staff = _staff(staff_id)
        when = _occurred_at(occurred_at)
        if lot.item_id == batch.item_id:
            raise InventoryError("산출 품목과 같은 품목은 투입할 수 없습니다.")
        if not _usable(lot):
            raise InventoryError(
                f"사용할 수 없는 LOT입니다: {lot.item.item_code} / {lot.lot_number} "
                f"({lot.get_status_display()} 또는 보류 중)"
            )
        if lot.expiration_date and lot.expiration_date < when.date():
            raise InventoryError(
                f"소비기한이 지난 LOT입니다: {lot.lot_number} (소비기한 {lot.expiration_date})"
            )
        bom_line = None
        if bom_line_id:
            bom_line = BomLine.objects.filter(pk=bom_line_id).first()
            if bom_line is None or bom_line.bom_id != batch.bom_id:
                raise InventoryError("배치의 BOM 구성이 아닙니다.")
            if (
                bom_line.component_item_id != lot.item_id
                and not BomLineAlternative.objects.filter(
                    bom_line=bom_line, item_id=lot.item_id
                ).exists()
            ):
                raise InventoryError("BOM 구성 품목과 투입 LOT의 품목이 다릅니다.")
            _component_quantity(quantity_e6, lot.item.base_unit, bom_line.component_item.base_unit)
        _check_outflow(lot, quantity_e6, when)
        movement = StockMovement.objects.create(
            lot=lot,
            movement_type_id="PRODUCTION_USE",
            quantity_e6=quantity_e6,
            staff=staff,
            occurred_at=when,
            reason=f"생산 투입 {batch.batch_number}",
            idempotency_key=key,
        )
        return ProductionMaterialUsage.objects.create(
            batch=batch,
            lot=lot,
            quantity_e6=quantity_e6,
            stock_movement=movement,
            bom_line=bom_line,
        )


def add_output(
    *,
    batch_id,
    quantity,
    staff_id,
    idempotency_key,
    occurred_at=None,
    lot_number=None,
    expiration_date=None,
):
    """Put output quantity in stock under the batch's single LOT (10/15: 1 배치 = 1 산출 LOT).

    The first output creates the LOT; later outputs add to the same LOT, so entering output in
    several parts does not create more LOTs. lot_number / expiration_date can only be set by the
    first output (later ones may repeat the same values or leave them out).
    LOT number: the PRODUCED rule (제조일 + 생산 순번) unless one is given.
    The base date is the batch's manufacturing date = 생산 시작일. A batch that was not started
    (사후 입력) must have it set at creation; the output time is not used as a fallback.
    Expiration: given, else manufacturing date + the item's shelf life (shelf_life.py), else none.
    The new LOT is AVAILABLE (no product inspection flow yet).
    """
    quantity_e6 = _quantity_e6(quantity)
    key = _key("OUTPUT", idempotency_key)
    with transaction.atomic():
        existing = ProductionOutput.objects.filter(stock_movement__idempotency_key=key)
        if existing.exists():
            output = existing.select_related("lot").get()
            if (output.batch_id, output.quantity_e6) != (batch_id, quantity_e6):
                raise InventoryError("같은 요청 키로 다른 내용의 산출이 이미 등록되어 있습니다.")
            return output
        batch = _batch(batch_id, lock_open=True)
        staff = _staff(staff_id)
        when = _occurred_at(occurred_at)
        item = batch.item
        if not batch.manufactured_date:
            raise InventoryError(
                "제조일(생산 시작일)이 없습니다. 배치를 시작하거나 배치에 제조일을 입력하세요."
            )
        made = batch.manufactured_date
        if made > when.date():
            raise InventoryError("산출일이 제조일(생산 시작일)보다 빠를 수 없습니다.")
        lot_number = (lot_number or "").strip()
        lot = batch_output_lot(batch)
        if lot is not None:  # 산출 추가: 같은 LOT 에 더한다
            if lot_number and lot_number != lot.lot_number:
                raise InventoryError(
                    f"이 배치의 산출 LOT은 {lot.lot_number} 하나입니다. "
                    "산출을 추가하면 같은 LOT에 더해집니다."
                )
            if expiration_date is not None and expiration_date != lot.expiration_date:
                raise InventoryError(
                    f"산출 추가는 이 배치 LOT의 소비기한({lot.expiration_date})을 따릅니다."
                )
        else:
            if lot_number:
                if Lot.objects.filter(item=item, lot_number=lot_number).exists():
                    raise InventoryError(
                        f"이미 있는 LOT 번호입니다: {item.item_code} / {lot_number}"
                    )
            else:
                lot_number = next_lot_number(lot_kind=LotKind.PRODUCED, item=item, base_date=made)
            if expiration_date is None:
                expiration_date = expiration_for(item, made)
            if expiration_date and expiration_date < made:
                raise InventoryError("소비기한이 제조일보다 빠를 수 없습니다.")
            lot = Lot.objects.create(
                lot_number=lot_number,
                item=item,
                lot_kind=LotKind.PRODUCED,
                status=LotStatus.AVAILABLE,
                manufactured_date=made,
                expiration_date=expiration_date,
            )
        movement = StockMovement.objects.create(
            lot=lot,
            movement_type_id="PRODUCTION_OUTPUT",
            quantity_e6=quantity_e6,
            staff=staff,
            occurred_at=when,
            reason=f"생산 산출 {batch.batch_number}",
            idempotency_key=key,
        )
        return ProductionOutput.objects.create(
            batch=batch, lot=lot, quantity_e6=quantity_e6, stock_movement=movement
        )


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


def fefo_candidates(*, item_id, quantity, on_date=None):
    """Usable LOTs of the item to cover `quantity`, earliest expiration first (FEFO).

    Returns [(lot, take_e6, stock_e6)]; the takes add up to the quantity or to all usable stock
    when there is not enough (the caller shows the shortfall). Expired LOTs are left out.
    LOTs without a 소비기한 date (NONE 없음 / UNKNOWN 미확인) come after the dated ones, oldest
    received (or made) first. They stay usable: no NONE / UNKNOWN use block (10/15 scope).
    """
    needed = _quantity_e6(quantity)
    on_date = on_date or kst_now().date()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT l.id, inv.quantity_e6
            FROM lots l
            JOIN v_lot_availability a     ON a.lot_id = l.id
            JOIN inventory inv            ON inv.lot_id = l.id
            LEFT JOIN incoming_receipts r ON r.lot_id = l.id
            WHERE l.item_id = %s AND a.is_usable = 1 AND inv.quantity_e6 > 0
              AND (l.expiration_date IS NULL OR l.expiration_date >= %s)
            ORDER BY l.expiration_date IS NULL, l.expiration_date,
                     COALESCE(r.received_date, l.manufactured_date) IS NULL,
                     COALESCE(r.received_date, l.manufactured_date), l.id
            """,
            [item_id, on_date.isoformat()],
        )
        rows = cursor.fetchall()
    lots = Lot.objects.in_bulk([lot_id for lot_id, _ in rows])
    picks = []
    for lot_id, stock_e6 in rows:
        if needed <= 0:
            break
        take = min(stock_e6, needed)
        picks.append((lots[lot_id], take, stock_e6))
        needed -= take
    return picks


def standard_requirements(*, bom_id, quantity=None, quantity_e6=None):
    """One-level BOM requirement for a quantity of the output item: [(bom_line, need_e6)]."""
    if quantity_e6 is None:
        quantity_e6 = _quantity_e6(quantity)
    bom = Bom.objects.filter(pk=bom_id).first()
    if bom is None:
        raise NotFound(f"BOM을 찾을 수 없습니다. (id={bom_id})")
    lines = BomLine.objects.filter(bom=bom).select_related("component_item").order_by("line_no")
    return [(line, line.quantity_e6 * quantity_e6 // bom.base_quantity_e6) for line in lines]


def batch_summary(batch_id):
    """Batch with usage / output rows (net of corrections) for detail screens."""
    batch = _batch(batch_id)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT usage_id, lot_id, lot_number, item_id, quantity_e6, net_quantity_e6,"
            " stock_movement_id, bom_line_id FROM v_batch_usages WHERE batch_id = %s"
            " ORDER BY usage_id",
            [batch.pk],
        )
        columns = [c[0] for c in cursor.description]
        usages = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
        cursor.execute(
            "SELECT output_id, lot_id, lot_number, item_id, quantity_e6, net_quantity_e6,"
            " stock_movement_id FROM v_batch_outputs WHERE batch_id = %s ORDER BY output_id",
            [batch.pk],
        )
        columns = [c[0] for c in cursor.description]
        outputs = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
    for row in outputs:
        row["stock_e6"] = current_stock_e6(row["lot_id"])
    items = Item.objects.in_bulk({row["item_id"] for row in usages + outputs})
    for row in usages + outputs:
        row["item"] = items[row["item_id"]]
    lot_ids = list(dict.fromkeys(row["lot_id"] for row in outputs))
    output_lot = None
    if len(lot_ids) == 1:  # 10/15 이후 배치는 항상 하나 (예전 다중 LOT 기록은 outputs 로만)
        first = next(row for row in outputs if row["lot_id"] == lot_ids[0])
        output_lot = {
            "lot_id": first["lot_id"],
            "lot_number": first["lot_number"],
            "net_quantity_e6": sum(row["net_quantity_e6"] for row in outputs),
            "stock_e6": first["stock_e6"],
        }
    return {
        "batch": batch,
        "usages": usages,
        "outputs": outputs,
        "output_lot": output_lot,
        "bom_check": _bom_check(batch, usages, outputs),
    }


def _bom_check(batch, usages, outputs):
    """BOM standard vs actual per component, scaled to the output (or the plan if no output).

    Returns None without a BOM. Rows: line, standard_e6, actual_e6 (net usage of LOTs of the
    primary component or an explicitly linked allowed alternative (converted to its base unit)),
    stock_managed. A component that is not stock-managed (정제수 등, 10/14 PM 미팅 C1) has no
    LOTs, so its actual_e6 is None: the amount used is written in the 생산일지, not here.
    """
    if not batch.bom_id:
        return None
    produced = sum(row["net_quantity_e6"] for row in outputs)
    basis = produced if produced > 0 else batch.planned_quantity_e6
    used = {}
    alternatives = {}
    for alternative in BomLineAlternative.objects.filter(bom_line__bom_id=batch.bom_id):
        alternatives.setdefault(alternative.bom_line_id, set()).add(alternative.item_id)
    lines = standard_requirements(bom_id=batch.bom_id, quantity_e6=basis) if basis else []
    for row in usages:
        for line, _ in lines:
            # Explicit links own the quantity; unlinked primary inputs retain legacy matching.
            linked = row["bom_line_id"] == line.pk
            primary = row["bom_line_id"] is None and row["item_id"] == line.component_item_id
            allowed = row["item_id"] == line.component_item_id or row[
                "item_id"
            ] in alternatives.get(line.pk, set())
            if primary or (linked and allowed):
                amount = _component_quantity(
                    row["net_quantity_e6"], row["item"].base_unit, line.component_item.base_unit
                )
                used[line.pk] = used.get(line.pk, 0) + amount
    return {
        "basis_e6": basis,
        "basis": "output" if produced > 0 else "plan",
        "lines": [
            {
                "line": line,
                "standard_e6": need,
                "actual_e6": (
                    used.get(line.pk, 0) if line.component_item.is_stock_managed else None
                ),
                "stock_managed": line.component_item.is_stock_managed,
            }
            for line, need in lines
        ],
    }
