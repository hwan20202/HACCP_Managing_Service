"""문서 도메인 테이블. 이름·제약은 ERD v2(dev-notes/erd/v2)와 같게 유지한다."""

from django.db import models
from django.db.models import Q

from apps.staff.models import Staff

STATUS_CHOICES = ("draft", "submitted", "approved", "rejected")


class DocumentTemplate(models.Model):
    template_id = models.AutoField(primary_key=True)
    type_code = models.TextField()
    version = models.IntegerField()
    name = models.TextField()
    schema_json = models.JSONField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField()

    class Meta:
        db_table = "document_template"
        constraints = [
            models.UniqueConstraint(
                fields=["type_code", "version"], name="uq_template_type_version"
            ),
        ]


# FK 인덱스는 ERD v2에 없으므로 만들지 않는다(db_index=False). 필요해지면 ERD 변경으로 추가한다.


class Document(models.Model):
    document_id = models.AutoField(primary_key=True)
    template = models.ForeignKey(
        DocumentTemplate,
        models.PROTECT,
        db_column="template_id",
        related_name="documents",
        db_index=False,
    )
    subject = models.TextField(null=True, blank=True)
    work_date = models.DateField()
    assignee = models.ForeignKey(
        Staff,
        models.PROTECT,
        null=True,
        blank=True,
        db_column="assignee_id",
        related_name="+",
        db_index=False,
    )
    created_by = models.ForeignKey(
        Staff, models.PROTECT, db_column="created_by", related_name="+", db_index=False
    )
    due_at = models.DateTimeField(null=True, blank=True)
    status = models.TextField(default="draft")
    submitted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        Staff,
        models.PROTECT,
        null=True,
        blank=True,
        db_column="deleted_by",
        related_name="+",
        db_index=False,
    )

    class Meta:
        db_table = "document"
        constraints = [
            models.CheckConstraint(
                condition=Q(status__in=STATUS_CHOICES), name="ck_document_status"
            ),
            models.CheckConstraint(
                condition=Q(deleted_at__isnull=True, deleted_by__isnull=True)
                | Q(deleted_at__isnull=False, deleted_by__isnull=False),
                name="ck_document_deleted_pair",
            ),
        ]
        indexes = [
            models.Index(
                fields=["-work_date", "-document_id"],
                condition=Q(deleted_at__isnull=True),
                name="ix_document_list",
            ),
        ]


class DocSection(models.Model):
    section_id = models.AutoField(primary_key=True)
    document = models.ForeignKey(
        Document,
        models.CASCADE,
        db_column="document_id",
        related_name="sections",
        db_index=False,
    )
    section_def = models.TextField()
    row_no = models.IntegerField()
    values_json = models.JSONField(default=dict)
    recorded_at = models.DateTimeField(null=True, blank=True)
    recorded_by = models.ForeignKey(
        Staff,
        models.PROTECT,
        null=True,
        blank=True,
        db_column="recorded_by",
        related_name="+",
        db_index=False,
    )

    class Meta:
        db_table = "doc_section"
        constraints = [
            models.UniqueConstraint(
                fields=["document", "section_def", "row_no"], name="uq_section_row"
            ),
        ]
        # ux_section_round(JSON 식 + 부분 조건)는 마이그레이션의 RunSQL로 만든다(ERD v2 M7).
