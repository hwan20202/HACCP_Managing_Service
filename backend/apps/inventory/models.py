"""Production / inventory core models.

The tables are created by sql/0001_core.sql and sql/0002_production.sql (see migrations/), not by
Django. Every model here is managed=False: Django reads and writes the rows but never
creates or alters the tables. Changing a table means a new SQL migration (rule S6).

Rules that matter when writing code against these models:
- Quantities are integers scaled by 1,000,000 (*_e6, rule S3). Use apps.inventory.quantity.
- Datetimes are KST text (rule S4). KSTDateTimeField handles conversion.
- stock_movements is append-only and inventory is maintained by a DB trigger (I2, I3).
  Write a StockMovement to change stock; never write Inventory.
"""

from django.db import models

from .fields import KSTDateTimeField, LocalNow

# ---------------------------------------------------------------------------
# 1. Reference codes (seeded by the SQL migration)
# ---------------------------------------------------------------------------


class ItemType(models.Model):
    code = models.TextField(primary_key=True)
    name = models.TextField()
    code_prefix = models.TextField(null=True, blank=True)
    sort_order = models.IntegerField(default=0)

    class Meta:
        managed = False
        db_table = "item_types"
        ordering = ["sort_order"]

    def __str__(self):
        return self.name


class StockMovementType(models.Model):
    code = models.TextField(primary_key=True)
    name = models.TextField()
    direction = models.IntegerField()

    class Meta:
        managed = False
        db_table = "stock_movement_types"

    def __str__(self):
        return self.name


class HoldSourceType(models.Model):
    code = models.TextField(primary_key=True)
    name = models.TextField()
    requires_evidence = models.BooleanField(default=True)

    class Meta:
        managed = False
        db_table = "hold_source_types"

    def __str__(self):
        return self.name


class HoldDisposition(models.Model):
    code = models.TextField(primary_key=True)
    name = models.TextField()

    class Meta:
        managed = False
        db_table = "hold_dispositions"

    def __str__(self):
        return self.name


# ---------------------------------------------------------------------------
# 2. Master data
# ---------------------------------------------------------------------------


class Staff(models.Model):
    staff_code = models.TextField(unique=True)
    name = models.TextField()
    is_active = models.BooleanField(default=True)
    created_at = KSTDateTimeField(db_default=LocalNow(), editable=False)

    class Meta:
        managed = False
        db_table = "staff"

    def __str__(self):
        return f"{self.name} ({self.staff_code})"


class Supplier(models.Model):
    supplier_code = models.TextField(unique=True)
    name = models.TextField()
    is_active = models.BooleanField(default=True)
    created_at = KSTDateTimeField(db_default=LocalNow(), editable=False)

    class Meta:
        managed = False
        db_table = "suppliers"

    def __str__(self):
        return self.name


class Item(models.Model):
    item_type = models.ForeignKey(
        ItemType, models.PROTECT, to_field="code", db_column="item_type", related_name="items"
    )
    item_code = models.TextField(unique=True)
    short_code = models.TextField(unique=True, null=True, blank=True)
    name = models.TextField()
    base_unit = models.TextField()
    unit_weight_mg = models.BigIntegerField(null=True, blank=True)
    shelf_life_days = models.IntegerField(null=True, blank=True)
    # 소비기한 개월 ("제조일로부터 24개월"). Set months or days, not both. See shelf_life.py.
    shelf_life_months = models.IntegerField(null=True, blank=True)
    origin_country = models.TextField(null=True, blank=True)
    food_type = models.TextField(null=True, blank=True)
    minimum_stock_e6 = models.BigIntegerField(default=0)
    # False: 정제수 같은 공정용수 — LOT·재고·투입 기록 없음 (10/14 PM 미팅 C1, 0005)
    is_stock_managed = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    created_at = KSTDateTimeField(db_default=LocalNow(), editable=False)

    class Meta:
        managed = False
        db_table = "items"

    def __str__(self):
        return f"{self.item_code} {self.name}"


# ---------------------------------------------------------------------------
# 3. LOT
# ---------------------------------------------------------------------------


class LotKind(models.TextChoices):
    INCOMING = "INCOMING", "입고"
    PRODUCED = "PRODUCED", "생산"


class LotStatus(models.TextChoices):
    """Quality judgment only. Whether stock is left is inventory.quantity_e6; how it ran out
    (production use, return, disposal) is in stock_movements."""

    QUARANTINE = "QUARANTINE", "검사대기"
    AVAILABLE = "AVAILABLE", "사용가능"
    REJECTED = "REJECTED", "부적합"


class ExpirationStatus(models.TextChoices):
    """소비기한 유무 (0007). 날짜가 비었다고 '없음'으로 보지 않는다."""

    KNOWN = "KNOWN", "있음"
    NONE = "NONE", "없음"
    UNKNOWN = "UNKNOWN", "미확인"


class Lot(models.Model):
    # Unique per item (UNIQUE(item_id, lot_number)): produced 반제품 LOTs (제조일 + 순번) can
    # repeat across products. (완제품 LOT 의 품목 약어는 완제품 채번을 다룰 때 — PM A1)
    # Identify a LOT by id, or by item + lot_number.
    lot_number = models.TextField()
    item = models.ForeignKey(Item, models.PROTECT, related_name="lots")
    lot_kind = models.TextField(choices=LotKind.choices)
    status = models.TextField(choices=LotStatus.choices)
    manufactured_date = models.DateField(null=True, blank=True)
    expiration_date = models.DateField(null=True, blank=True)
    # KNOWN <=> expiration_date (DB triggers, 0007). Left blank, save() sets KNOWN when there is a
    # date and UNKNOWN otherwise — NONE (소비기한 없음 확인) is only ever set explicitly.
    expiration_status = models.TextField(choices=ExpirationStatus.choices, blank=True, default="")
    created_at = KSTDateTimeField(db_default=LocalNow(), editable=False)
    # Refreshed by trigger trg_lots_updated_at on every UPDATE.
    updated_at = KSTDateTimeField(db_default=LocalNow(), editable=False)

    class Meta:
        managed = False
        db_table = "lots"
        unique_together = [("item", "lot_number")]

    def __str__(self):
        return self.lot_number

    def save(self, *args, **kwargs):
        if not self.expiration_status:
            self.expiration_status = (
                ExpirationStatus.KNOWN if self.expiration_date else ExpirationStatus.UNKNOWN
            )
        super().save(*args, **kwargs)


class LotNumberRule(models.Model):
    lot_kind = models.TextField(choices=LotKind.choices)
    item_type = models.ForeignKey(
        ItemType,
        models.PROTECT,
        to_field="code",
        db_column="item_type",
        null=True,
        blank=True,
        related_name="lot_number_rules",
    )
    pattern = models.TextField()
    effective_from = models.DateField()
    is_active = models.BooleanField(default=True)
    notes = models.TextField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "lot_number_rules"


class LotNumberSequence(models.Model):
    seq_key = models.TextField(primary_key=True)
    current_seq = models.IntegerField(default=0)
    updated_at = KSTDateTimeField(db_default=LocalNow())

    class Meta:
        managed = False
        db_table = "lot_number_sequences"


# ---------------------------------------------------------------------------
# 4. Stock movements / inventory (I1-I3)
# ---------------------------------------------------------------------------


class AppendOnlyError(Exception):
    """Raised when code tries to change rows the schema treats as immutable."""


class StockMovementQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise AppendOnlyError("stock_movements is append-only: add a CORRECTION movement (I2)")

    def delete(self):
        raise AppendOnlyError("stock_movements is append-only: add a CORRECTION movement (I2)")


class StockMovement(models.Model):
    lot = models.ForeignKey(Lot, models.PROTECT, related_name="movements")
    movement_type = models.ForeignKey(
        StockMovementType,
        models.PROTECT,
        to_field="code",
        db_column="movement_type_code",
        related_name="movements",
    )
    quantity_e6 = models.BigIntegerField()
    corrects_movement = models.ForeignKey(
        "self", models.PROTECT, null=True, blank=True, related_name="corrections"
    )
    staff = models.ForeignKey(Staff, models.PROTECT, related_name="stock_movements")
    occurred_at = KSTDateTimeField()
    reason = models.TextField(null=True, blank=True)
    idempotency_key = models.TextField(unique=True)
    created_at = KSTDateTimeField(db_default=LocalNow(), editable=False)

    objects = StockMovementQuerySet.as_manager()

    class Meta:
        managed = False
        db_table = "stock_movements"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise AppendOnlyError("stock_movements is append-only: add a CORRECTION movement (I2)")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise AppendOnlyError("stock_movements is append-only: add a CORRECTION movement (I2)")


class InventoryQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise AppendOnlyError("inventory is maintained by trigger trg_sm_inventory (I3)")

    def delete(self):
        raise AppendOnlyError("inventory is maintained by trigger trg_sm_inventory (I3)")


class Inventory(models.Model):
    """Current quantity per LOT. Read-only from the application (I3)."""

    lot = models.OneToOneField(Lot, models.PROTECT, primary_key=True, related_name="inventory")
    quantity_e6 = models.BigIntegerField(default=0)
    updated_at = KSTDateTimeField(db_default=LocalNow(), editable=False)

    objects = InventoryQuerySet.as_manager()

    class Meta:
        managed = False
        db_table = "inventory"

    def save(self, *args, **kwargs):
        raise AppendOnlyError("inventory is maintained by trigger trg_sm_inventory (I3)")

    def delete(self, *args, **kwargs):
        raise AppendOnlyError("inventory is maintained by trigger trg_sm_inventory (I3)")


# ---------------------------------------------------------------------------
# 5. Incoming receipts (one receipt = one LOT)
# ---------------------------------------------------------------------------


class ReceiptStatus(models.TextChoices):
    COMPLETED = "COMPLETED", "완료"
    CANCELLED = "CANCELLED", "취소"


class IncomingReceipt(models.Model):
    lot = models.OneToOneField(Lot, models.PROTECT, related_name="incoming_receipt")
    supplier = models.ForeignKey(Supplier, models.PROTECT, related_name="incoming_receipts")
    supplier_lot_number = models.TextField(null=True, blank=True)
    received_date = models.DateField()
    quantity_e6 = models.BigIntegerField()
    staff = models.ForeignKey(Staff, models.PROTECT, related_name="incoming_receipts")
    stock_movement = models.OneToOneField(
        StockMovement, models.PROTECT, related_name="incoming_receipt"
    )
    receipt_status = models.TextField(
        choices=ReceiptStatus.choices, default=ReceiptStatus.COMPLETED
    )
    cancelled_at = KSTDateTimeField(null=True, blank=True)
    cancel_reason = models.TextField(null=True, blank=True)
    created_at = KSTDateTimeField(db_default=LocalNow(), editable=False)

    class Meta:
        managed = False
        db_table = "incoming_receipts"


# ---------------------------------------------------------------------------
# 6. Holds (I5) — sql/0003_holds.sql. One table for LOT and batch holds; a batch hold is
#    propagated to the batch's output LOTs (source_type PROPAGATED, parent_hold). See holds.py.
# ---------------------------------------------------------------------------


class Hold(models.Model):
    lot = models.ForeignKey(Lot, models.PROTECT, null=True, blank=True, related_name="holds")
    batch = models.ForeignKey(
        "ProductionBatch", models.PROTECT, null=True, blank=True, related_name="holds"
    )
    source_type = models.ForeignKey(
        HoldSourceType,
        models.PROTECT,
        to_field="code",
        db_column="source_type",
        related_name="holds",
    )
    # document.document_id of the evidence document (record, not version). No FK: avoids a
    # migration cycle with the document app (0001 header C6).
    source_document_id = models.BigIntegerField(null=True, blank=True)
    parent_hold = models.ForeignKey(
        "self", models.PROTECT, null=True, blank=True, related_name="propagated_holds"
    )
    reason = models.TextField()
    held_by = models.ForeignKey(
        Staff, models.PROTECT, db_column="held_by", related_name="holds_placed"
    )
    held_at = KSTDateTimeField()
    released_by = models.ForeignKey(
        Staff,
        models.PROTECT,
        db_column="released_by",
        null=True,
        blank=True,
        related_name="holds_released",
    )
    released_at = KSTDateTimeField(null=True, blank=True)
    disposition = models.ForeignKey(
        HoldDisposition,
        models.PROTECT,
        to_field="code",
        db_column="disposition",
        null=True,
        blank=True,
        related_name="holds",
    )
    release_reason = models.TextField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "holds"

    @property
    def is_open(self):
        return self.released_at is None


# ---------------------------------------------------------------------------
# 7. Audit log
# ---------------------------------------------------------------------------


class AuditLog(models.Model):
    table_name = models.TextField()
    record_id = models.TextField()
    action = models.TextField(
        choices=[("INSERT", "INSERT"), ("UPDATE", "UPDATE"), ("DELETE", "DELETE")]
    )
    before_json = models.JSONField(null=True, blank=True)
    after_json = models.JSONField(null=True, blank=True)
    reason = models.TextField(null=True, blank=True)
    staff = models.ForeignKey(Staff, models.PROTECT, related_name="audit_logs")
    occurred_at = KSTDateTimeField(db_default=LocalNow())

    class Meta:
        managed = False
        db_table = "audit_logs"


# ---------------------------------------------------------------------------
# 8. Production (sql/0002_production.sql)
#    Usages and outputs are append-only (DB triggers); fix them by correcting the linked
#    stock movement. Batches are never deleted: cancel instead.
# ---------------------------------------------------------------------------


class Bom(models.Model):
    item = models.ForeignKey(Item, models.PROTECT, related_name="boms")
    version = models.IntegerField()
    base_quantity_e6 = models.BigIntegerField()
    effective_from = models.DateField()
    is_active = models.BooleanField(default=True)
    notes = models.TextField(null=True, blank=True)
    created_by = models.ForeignKey(
        Staff,
        models.PROTECT,
        db_column="created_by",
        null=True,
        blank=True,
        related_name="boms_created",
    )
    created_at = KSTDateTimeField(db_default=LocalNow(), editable=False)

    class Meta:
        managed = False
        db_table = "boms"


class BomLine(models.Model):
    bom = models.ForeignKey(Bom, models.PROTECT, related_name="lines")
    line_no = models.IntegerField()
    component_item = models.ForeignKey(Item, models.PROTECT, related_name="bom_usages")
    quantity_e6 = models.BigIntegerField()
    notes = models.TextField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "bom_lines"


class BomLineAlternative(models.Model):
    bom_line = models.ForeignKey(BomLine, models.PROTECT, related_name="alternatives")
    item = models.ForeignKey(Item, models.PROTECT, related_name="bom_alternatives")

    class Meta:
        managed = False
        db_table = "bom_line_alternatives"


class ProcessType(models.TextChoices):
    MANUFACTURE = "MANUFACTURE", "제조"
    # 예전 기록 조회용. 새 포장배치는 MVP 범위 밖 (10/15, 0006 트리거로 막음)
    PACKAGING = "PACKAGING", "포장"


class BatchStatus(models.TextChoices):
    PLANNED = "PLANNED", "계획"
    IN_PROGRESS = "IN_PROGRESS", "진행"
    COMPLETED = "COMPLETED", "완료"
    CANCELLED = "CANCELLED", "취소"


class ProductionBatch(models.Model):
    batch_number = models.TextField(unique=True)
    process_type = models.TextField(choices=ProcessType.choices)
    item = models.ForeignKey(Item, models.PROTECT, related_name="production_batches")
    bom = models.ForeignKey(
        Bom, models.PROTECT, null=True, blank=True, related_name="production_batches"
    )
    status = models.TextField(choices=BatchStatus.choices)
    planned_date = models.DateField(null=True, blank=True)
    planned_quantity_e6 = models.BigIntegerField(null=True, blank=True)
    manufactured_date = models.DateField(null=True, blank=True)
    # 근무조: 10/14 PM 미팅으로 폐지. 문서 뷰(v_doc_batch) 계약 때문에 열만 남김 (항상 NULL)
    shift = models.TextField(null=True, blank=True)
    started_at = KSTDateTimeField(null=True, blank=True)
    completed_at = KSTDateTimeField(null=True, blank=True)
    staff = models.ForeignKey(Staff, models.PROTECT, related_name="production_batches")
    notes = models.TextField(null=True, blank=True)
    cancelled_at = KSTDateTimeField(null=True, blank=True)
    cancel_reason = models.TextField(null=True, blank=True)
    created_at = KSTDateTimeField(db_default=LocalNow(), editable=False)
    # Refreshed by trigger trg_batches_updated_at on every UPDATE.
    updated_at = KSTDateTimeField(db_default=LocalNow(), editable=False)

    class Meta:
        managed = False
        db_table = "production_batches"

    def __str__(self):
        return self.batch_number


class ProductionMaterialUsage(models.Model):
    batch = models.ForeignKey(ProductionBatch, models.PROTECT, related_name="usages")
    lot = models.ForeignKey(Lot, models.PROTECT, related_name="production_usages")
    quantity_e6 = models.BigIntegerField()
    stock_movement = models.OneToOneField(
        StockMovement, models.PROTECT, related_name="production_usage"
    )
    bom_line = models.ForeignKey(
        BomLine, models.PROTECT, null=True, blank=True, related_name="usages"
    )
    created_at = KSTDateTimeField(db_default=LocalNow(), editable=False)

    class Meta:
        managed = False
        db_table = "production_material_usages"


class ProductionOutput(models.Model):
    batch = models.ForeignKey(ProductionBatch, models.PROTECT, related_name="outputs")
    lot = models.ForeignKey(Lot, models.PROTECT, related_name="production_outputs")
    quantity_e6 = models.BigIntegerField()
    stock_movement = models.OneToOneField(
        StockMovement, models.PROTECT, related_name="production_output"
    )
    created_at = KSTDateTimeField(db_default=LocalNow(), editable=False)

    class Meta:
        managed = False
        db_table = "production_outputs"
