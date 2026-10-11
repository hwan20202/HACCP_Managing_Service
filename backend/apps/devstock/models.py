"""수불 개발용 임시 테이블 (ERD v5 A13, D-050 Q1, P4-S3-Q1).

수불 앱이 공유한 스키마(2026-10-11) 중 문서 쪽이 쓰는 컬럼만 둔다. 개발·테스트 설정에서만 설치한다.
수불 앱이 같은 이름·PK로 실제 테이블을 만들면 이 앱을 빼고 개발 DB를 다시 만든다(P4-S3-Q7).
품목 테이블 이름 `items`는 가정이다(수불 확인 필요, P4-S3-Q3).
"""

from django.db import models
from django.db.models import Q

LOT_KINDS = ("INCOMING", "PRODUCED")
LOT_STATUSES = ("QUARANTINE", "AVAILABLE", "CONSUMED", "REJECTED", "DISPOSED")
PROCESS_TYPES = ("MANUFACTURE", "PACKAGING")
BATCH_STATUSES = ("PLANNED", "IN_PROGRESS", "COMPLETED", "CANCELLED")


class Item(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.TextField()

    class Meta:
        db_table = "items"


class Lot(models.Model):
    id = models.AutoField(primary_key=True)
    lot_number = models.TextField(unique=True)
    item = models.ForeignKey(
        Item, models.PROTECT, db_column="item_id", related_name="+", db_index=False
    )  # ERD v5에 없는 인덱스(수불 실제 테이블 기준)
    lot_kind = models.TextField()
    status = models.TextField()
    manufactured_date = models.DateField(null=True, blank=True)
    expiration_date = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "lots"
        constraints = [
            models.CheckConstraint(condition=Q(lot_kind__in=LOT_KINDS), name="ck_lot_kind"),
            models.CheckConstraint(condition=Q(status__in=LOT_STATUSES), name="ck_lot_status"),
        ]


class ProductionBatch(models.Model):
    id = models.AutoField(primary_key=True)
    batch_number = models.TextField(unique=True)
    process_type = models.TextField()
    item = models.ForeignKey(
        Item, models.PROTECT, db_column="item_id", related_name="+", db_index=False
    )  # ERD v5에 없는 인덱스(수불 실제 테이블 기준)
    status = models.TextField()
    manufactured_date = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "production_batches"
        constraints = [
            models.CheckConstraint(
                condition=Q(process_type__in=PROCESS_TYPES), name="ck_batch_process_type"
            ),
            models.CheckConstraint(condition=Q(status__in=BATCH_STATUSES), name="ck_batch_status"),
        ]


# ------------------------------------------------ P5 개발용 보완 (ERD v5 A15·A16, D-069)
# 수불 입고 기록·생산 계획에는 있지만 위 임시 테이블에는 없는 값. REQ는 이 테이블을 직접 읽지 않고
# 뷰 v_doc_incoming_lot·v_doc_batch(마이그레이션 0003, RunSQL)만 읽는다.
# 입고일 형식·매입처 길이는 DB CHECK 대신 개발 API에서 검사한다(REQ-S3-Q2).

MATERIAL_KINDS = ("원료", "부자재")
UNITS = ("kg", "g", "box", "ea")
ORIGINS = ("국내", "수입")


class DevLotReceipt(models.Model):
    lot = models.OneToOneField(
        Lot, models.CASCADE, primary_key=True, db_column="lot_id", related_name="+"
    )
    material_kind = models.TextField()
    supplier_name = models.TextField()
    received_date = models.DateField(db_index=False)
    quantity = models.FloatField()
    unit = models.TextField()
    origin = models.TextField(null=True, blank=True)
    touched_at = models.DateTimeField(null=True, blank=True)  # 재호출 자기 쓰기(REQ-S2-Q13)

    class Meta:
        db_table = "dev_lot_receipts"
        indexes = [models.Index(fields=["received_date"], name="ix_dev_lot_receipts_date")]
        constraints = [
            models.CheckConstraint(
                condition=Q(material_kind__in=MATERIAL_KINDS), name="ck_receipt_material_kind"
            ),
            models.CheckConstraint(condition=Q(quantity__gt=0), name="ck_receipt_quantity"),
            models.CheckConstraint(condition=Q(unit__in=UNITS), name="ck_receipt_unit"),
            models.CheckConstraint(
                condition=Q(origin__isnull=True) | Q(origin__in=ORIGINS), name="ck_receipt_origin"
            ),
        ]


class DevBatchPlan(models.Model):
    production_batch = models.OneToOneField(
        ProductionBatch,
        models.CASCADE,
        primary_key=True,
        db_column="production_batch_id",
        related_name="+",
    )
    quantity_kg = models.FloatField()
    touched_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "dev_batch_plans"
        constraints = [
            models.CheckConstraint(condition=Q(quantity_kg__gte=0), name="ck_plan_quantity_kg")
        ]
