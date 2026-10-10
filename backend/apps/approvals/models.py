"""결재 도메인 테이블 (ERD v4: A3 approval_request, M5 approval).

문서·양식은 문자열 참조("documents.Document")로만 연결한다.
이 앱은 apps.documents를 import하지 않는다.
"""

from django.db import models
from django.db.models import Q
from django.db.models.functions import Trim

from apps.staff.models import Staff

# 반려 사유 CHECK에서 comment__trim 을 쓰기 위해 등록한다(TRIM(comment) = '').
models.TextField.register_lookup(Trim)

REQUEST_STATUSES = ("in_progress", "approved", "rejected")
SLOT_STATES = ("pending", "approved", "rejected", "skipped")


class ApprovalRequest(models.Model):
    request_id = models.AutoField(primary_key=True)
    document = models.ForeignKey(
        "documents.Document",
        models.PROTECT,
        db_column="document_id",
        related_name="+",
        db_index=False,  # UNIQUE(document_id, attempt)가 앞부분을 덮는다
    )
    attempt = models.IntegerField()
    status = models.TextField()
    document_version = models.IntegerField()
    template = models.ForeignKey(
        "documents.DocumentTemplate",
        models.PROTECT,
        db_column="template_id",
        related_name="+",
        db_index=False,
    )
    subject = models.TextField(null=True, blank=True)
    work_date = models.DateField()
    snapshot_json = models.JSONField()
    requested_by = models.ForeignKey(
        Staff, models.PROTECT, db_column="requested_by", related_name="+", db_index=False
    )
    requested_at = models.DateTimeField()
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "approval_request"
        constraints = [
            models.UniqueConstraint(fields=["document", "attempt"], name="uq_request_attempt"),
            models.UniqueConstraint(
                fields=["document"], condition=Q(status="in_progress"), name="ux_request_open"
            ),
            models.CheckConstraint(condition=Q(attempt__gte=1), name="ck_request_attempt"),
            models.CheckConstraint(
                condition=Q(status__in=REQUEST_STATUSES), name="ck_request_status"
            ),
            models.CheckConstraint(
                condition=Q(status="in_progress", closed_at__isnull=True)
                | (~Q(status="in_progress") & Q(closed_at__isnull=False)),
                name="ck_request_closed",
            ),
        ]


class Approval(models.Model):
    """결재 슬롯. 슬롯 하나에 결재자 1명, 병렬 처리."""

    approval_id = models.AutoField(primary_key=True)
    request = models.ForeignKey(
        ApprovalRequest,
        models.PROTECT,
        db_column="request_id",
        related_name="slots",
        db_index=False,  # UNIQUE(request_id, slot_no)가 덮는다
    )
    slot_no = models.IntegerField()
    label = models.TextField(null=True, blank=True)
    approver = models.ForeignKey(
        Staff, models.PROTECT, db_column="approver_id", related_name="+", db_index=False
    )
    state = models.TextField(default="pending", db_default="pending")
    comment = models.TextField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "approval"
        constraints = [
            models.UniqueConstraint(fields=["request", "slot_no"], name="uq_approval_slot"),
            models.UniqueConstraint(fields=["request", "approver"], name="uq_approval_approver"),
            models.CheckConstraint(condition=Q(slot_no__gte=1), name="ck_approval_slot_no"),
            models.CheckConstraint(condition=Q(state__in=SLOT_STATES), name="ck_approval_state"),
            models.CheckConstraint(
                condition=Q(state="pending", decided_at__isnull=True)
                | (~Q(state="pending") & Q(decided_at__isnull=False)),
                name="ck_approval_decided",
            ),
            models.CheckConstraint(
                condition=~Q(state="rejected") | (Q(comment__isnull=False) & ~Q(comment__trim="")),
                name="ck_approval_reject_comment",
            ),
        ]
        indexes = [models.Index(fields=["approver", "state"], name="ix_approval_inbox")]
