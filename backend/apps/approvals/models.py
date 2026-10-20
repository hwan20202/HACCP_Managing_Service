"""결재 도메인 테이블 (ERD v4: A3 approval_request, M5 approval · v7.2: A20·M16·M17·A21 역할 칸).

문서·양식은 문자열 참조("documents.Document")로만 연결한다.
이 앱은 apps.documents를 import하지 않는다.
"""

from django.db import models
from django.db.models import Q
from django.db.models.functions import Trim

from apps.staff.models import Staff

# 반려 사유 CHECK에서 comment__trim 을 쓰기 위해 등록한다(TRIM(comment) = '').
models.TextField.register_lookup(Trim)

REQUEST_STATUSES = ("in_progress", "approved", "rejected", "cancelled")  # ERD v7 M12
SLOT_STATES = ("pending", "approved", "rejected", "skipped")
SLOT_ROLES = ("owner", "leader")  # ERD v7.2 A20 — NULL = 직접 지정 칸(P14 이전)
DECIDED_STATES = ("approved", "rejected")


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
    """결재 슬롯(칸), 병렬 처리.

    직접 지정 칸(role NULL, P14 이전): 결재자 1명을 상신 때 지정.
    역할 칸(role = owner·leader, P14 — ERD v7.2): 상신 때 후보(ApprovalCandidate)를 고정하고,
    후보 중 1명이 처리하면 그 사람이 결재자(approver)가 된다. 대기·건너뜀이면 결재자 없음.
    """

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
    role = models.TextField(null=True, blank=True)  # ERD v7.2 A20
    approver = models.ForeignKey(
        Staff,
        models.PROTECT,
        null=True,  # ERD v7.2 M16 — 역할 칸은 처리 전 NULL
        blank=True,
        db_column="approver_id",
        related_name="+",
        db_index=False,
    )
    state = models.TextField(default="pending", db_default="pending")
    comment = models.TextField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "approval"
        constraints = [
            models.UniqueConstraint(fields=["request", "slot_no"], name="uq_approval_slot"),
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
            models.CheckConstraint(
                condition=Q(role__isnull=True) | Q(role__in=SLOT_ROLES), name="ck_approval_role"
            ),
            models.CheckConstraint(  # ERD v7.2 A20: 결재자 있음 규칙
                condition=Q(role__isnull=True, approver__isnull=False)
                | Q(role__isnull=False, approver__isnull=False, state__in=DECIDED_STATES)
                | (Q(role__isnull=False, approver__isnull=True) & ~Q(state__in=DECIDED_STATES)),
                name="ck_approval_approver",
            ),
        ]
        indexes = [models.Index(fields=["approver", "state"], name="ix_approval_inbox")]


class ApprovalCandidate(models.Model):
    """결재 후보(ERD v7.2 A21). 역할 칸만, 상신 때 그 칸 역할의 활성 보유자 전원. 바꾸지 않음."""

    pk = models.CompositePrimaryKey("approval", "staff")
    approval = models.ForeignKey(
        Approval,
        models.CASCADE,
        db_column="approval_id",
        related_name="candidates",
        db_index=False,  # PK(approval_id, staff_id)가 대신한다
    )
    staff = models.ForeignKey(
        Staff, models.PROTECT, db_column="staff_id", related_name="+", db_index=False
    )  # ix_approval_candidate_staff가 대신한다

    class Meta:
        db_table = "approval_candidate"
        indexes = [models.Index(fields=["staff"], name="ix_approval_candidate_staff")]
