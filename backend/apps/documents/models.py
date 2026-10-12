"""문서 도메인 테이블. 이름·제약은 ERD(dev-notes/erd/v6)와 같게 유지한다.

v5(P4): 작성완료 상태·작성 요구 키(document), 업무 대상 참조(document_ref, RunSQL·managed=False),
파일(file, document_file — 기능은 스프린트 3), 개선조치(deviation_action, deviation_checker).
v6(P6): 정정 중 상태(correcting), 정정 기록(document_correction).
Django는 on_delete를 DB의 ON DELETE로 만들지 않는다(ERD v5 메모, ORM이 처리).
"""

from django.db import models
from django.db.models import Q
from django.db.models.functions import Length

from apps.staff.models import Staff

STATUS_CHOICES = ("draft", "completed", "submitted", "approved", "rejected", "correcting")
FILE_MIME_TYPES = ("application/pdf", "image/jpeg", "image/png")
FILE_MAX_BYTES = 20 * 1024 * 1024


class TrimWhitespace(models.Transform):
    """trim(x, 공백·탭·줄바꿈) — 개선조치 이탈내용이 공백만인지 검사(ERD v5 A11)."""

    lookup_name = "trim_ws"
    function = "TRIM"
    template = "TRIM(%(expressions)s, ' ' || char(9) || char(10) || char(13))"


models.TextField.register_lookup(Length)
models.TextField.register_lookup(TrimWhitespace)


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
    # ERD v5 A8: 작성 요구 키 'D01|lot:88'. NULL = 사용자가 직접 만든 문서
    record_key = models.TextField(null=True, blank=True)
    # ERD v5 A7: 작성완료 기록 (작성 재개 시 비움)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        Staff,
        models.PROTECT,
        null=True,
        blank=True,
        db_column="completed_by",
        related_name="+",
        db_index=False,
    )
    # ERD v3 A6: 낙관적 잠금 버전. 모든 쓰기마다 +1 (ISS-001)
    version = models.IntegerField(default=1, db_default=1)
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
            models.CheckConstraint(
                condition=Q(completed_at__isnull=True, completed_by__isnull=True)
                | Q(completed_at__isnull=False, completed_by__isnull=False),
                name="ck_document_completed_pair",
            ),
            models.CheckConstraint(
                condition=~Q(status="completed") | Q(completed_at__isnull=False),
                name="ck_document_completed_required",
            ),
            models.CheckConstraint(
                # ERD v6 M11: 정정 중도 작성완료 기록 없음(P6-S2-Q6)
                condition=~Q(status__in=("draft", "correcting")) | Q(completed_at__isnull=True),
                name="ck_document_draft_not_completed",
            ),
            # 작성 요구 문서 1건(삭제 문서 포함). get_or_create_document의 ON CONFLICT 대상
            models.UniqueConstraint(
                fields=["record_key"],
                condition=Q(record_key__isnull=False),
                name="ux_document_record_key",
            ),
        ]
        indexes = [
            models.Index(
                fields=["-work_date", "-document_id"],
                condition=Q(deleted_at__isnull=True),
                name="ix_document_list",
            ),
        ]


class DocumentCorrection(models.Model):
    """정정 기록(ERD v6 A17). 열린 정정(closed_at NULL)이 있으면 정정 진행 중, 문서마다 1개.

    승인 회차를 FK로 가리키지 않는다(DOC → APR 의존 없음, P6-NFR-02).
    """

    correction_id = models.AutoField(primary_key=True)
    document = models.ForeignKey(
        Document,
        models.PROTECT,
        db_column="document_id",
        related_name="corrections",
        db_index=False,
    )
    started_at = models.DateTimeField()
    started_by = models.ForeignKey(
        Staff, models.PROTECT, db_column="started_by", related_name="+", db_index=False
    )
    reason = models.TextField()
    # 정정 시작 직후 문서 버전 — 정정 취소 조건(D-075)
    start_version = models.IntegerField()
    # 정정 전 작성완료 기록 — 정정 취소 때 복원(P6-S2-Q6)
    prev_completed_at = models.DateTimeField(null=True, blank=True)
    prev_completed_by = models.ForeignKey(
        Staff,
        models.PROTECT,
        null=True,
        blank=True,
        db_column="prev_completed_by",
        related_name="+",
        db_index=False,
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    outcome = models.TextField(null=True, blank=True)  # approved / cancelled

    class Meta:
        db_table = "document_correction"
        constraints = [
            models.CheckConstraint(
                condition=Q(reason__length__gte=1, reason__length__lte=200)
                & ~Q(reason__trim_ws=""),
                name="ck_correction_reason",
            ),
            models.CheckConstraint(
                condition=Q(start_version__gte=1), name="ck_correction_start_version"
            ),
            models.CheckConstraint(
                condition=Q(prev_completed_at__isnull=True, prev_completed_by__isnull=True)
                | Q(prev_completed_at__isnull=False, prev_completed_by__isnull=False),
                name="ck_correction_prev_pair",
            ),
            # outcome IN (...)만으로는 NULL을 못 막는다(SQLite CHECK) — IS NOT NULL 명시(ERD v6 V16)
            models.CheckConstraint(
                condition=Q(closed_at__isnull=True, outcome__isnull=True)
                | Q(
                    closed_at__isnull=False,
                    outcome__isnull=False,
                    outcome__in=("approved", "cancelled"),
                ),
                name="ck_correction_closed_pair",
            ),
            models.UniqueConstraint(
                fields=["document"],
                condition=Q(closed_at__isnull=True),
                name="ux_correction_open",
            ),
        ]
        indexes = [
            models.Index(fields=["document", "started_at"], name="ix_correction_document"),
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
            # ERD v5 A14: document_ref 복합 FK (section_id, document_id)의 대상
            models.UniqueConstraint(fields=["section_id", "document"], name="ux_section_document"),
        ]
        # ux_section_round(JSON 식 + 부분 조건)는 마이그레이션의 RunSQL로 만든다(ERD v2 M7).


# ---------------------------------------------------------------- v5 (P4)


class DocumentRef(models.Model):
    """업무 대상 참조(ERD v5 A9). 테이블은 마이그레이션 RunSQL로 만든다(managed=False, P4-S3-Q6).

    lot_id·production_batch_id·item_id는 수불 테이블의 DB FK지만 Django에서는 정수로 둔다
    (수불 앱 교체 때 이 앱 마이그레이션이 영향받지 않게, P4-S3-Q2). 구조 변경은 항상 RunSQL로.
    """

    ref_id = models.AutoField(primary_key=True)
    document_id = models.IntegerField()
    section_id = models.IntegerField(null=True)
    lot_id = models.IntegerField(null=True)
    production_batch_id = models.IntegerField(null=True)
    item_id = models.IntegerField(null=True)
    process_code = models.TextField(null=True)
    label = models.TextField(null=True)
    created_at = models.DateTimeField()

    class Meta:
        db_table = "document_ref"
        managed = False


class File(models.Model):
    """파일 1개(ERD v5 M9). 기능(올리기·연결)은 스프린트 3(D-058)."""

    file_id = models.AutoField(primary_key=True)
    storage_path = models.TextField(unique=True)
    original_name = models.TextField()
    mime_type = models.TextField()
    size_bytes = models.IntegerField()
    sha256 = models.TextField()
    uploaded_by = models.ForeignKey(
        Staff, models.PROTECT, db_column="uploaded_by", related_name="+", db_index=False
    )
    uploaded_at = models.DateTimeField()
    retained_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "file"
        constraints = [
            models.CheckConstraint(
                condition=Q(original_name__length__gte=1, original_name__length__lte=255),
                name="ck_file_name",
            ),
            models.CheckConstraint(condition=Q(mime_type__in=FILE_MIME_TYPES), name="ck_file_mime"),
            models.CheckConstraint(
                condition=Q(size_bytes__gte=1, size_bytes__lte=FILE_MAX_BYTES), name="ck_file_size"
            ),
            models.CheckConstraint(condition=Q(sha256__length=64), name="ck_file_sha256"),
        ]


class DocumentFile(models.Model):
    """문서 ↔ 파일 연결(ERD v5 A10). 같은 파일 중복 연결 불가(PK)."""

    pk = models.CompositePrimaryKey("document", "file")
    document = models.ForeignKey(
        Document, models.PROTECT, db_column="document_id", related_name="+", db_index=False
    )
    file = models.ForeignKey(
        File, models.PROTECT, db_column="file_id", related_name="links", db_index=False
    )
    linked_by = models.ForeignKey(
        Staff, models.PROTECT, db_column="linked_by", related_name="+", db_index=False
    )
    linked_at = models.DateTimeField()

    class Meta:
        db_table = "document_file"
        indexes = [models.Index(fields=["file"], name="ix_document_file_file")]


class DeviationAction(models.Model):
    """개선조치(ERD v5 A11). 문서 상태와 무관하게 수정한다(D-054). 확인 기능은 ISS-008."""

    deviation_id = models.AutoField(primary_key=True)
    document = models.ForeignKey(
        Document, models.PROTECT, db_column="document_id", related_name="+", db_index=False
    )
    section = models.ForeignKey(
        DocSection,
        models.SET_NULL,
        null=True,
        blank=True,
        db_column="section_id",
        related_name="+",
        db_index=False,
    )
    description = models.TextField()
    action_result = models.TextField(null=True, blank=True)
    actor = models.ForeignKey(
        Staff,
        models.PROTECT,
        null=True,
        blank=True,
        db_column="actor_id",
        related_name="+",
        db_index=False,
    )
    checked_by = models.ForeignKey(
        Staff,
        models.PROTECT,
        null=True,
        blank=True,
        db_column="checked_by",
        related_name="+",
        db_index=False,
    )
    checked_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        Staff, models.PROTECT, db_column="created_by", related_name="+", db_index=False
    )
    created_at = models.DateTimeField()
    updated_by = models.ForeignKey(
        Staff, models.PROTECT, db_column="updated_by", related_name="+", db_index=False
    )
    updated_at = models.DateTimeField()
    version = models.IntegerField(default=1, db_default=1)
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
        db_table = "deviation_action"
        constraints = [
            models.CheckConstraint(
                condition=Q(description__length__gte=1, description__length__lte=500)
                & ~Q(description__trim_ws=""),
                name="ck_deviation_description",
            ),
            models.CheckConstraint(
                condition=Q(action_result__isnull=True) | Q(action_result__length__lte=1000),
                name="ck_deviation_result",
            ),
            models.CheckConstraint(
                condition=Q(checked_by__isnull=True, checked_at__isnull=True)
                | Q(checked_by__isnull=False, checked_at__isnull=False),
                name="ck_deviation_checked_pair",
            ),
            models.CheckConstraint(
                condition=Q(deleted_at__isnull=True, deleted_by__isnull=True)
                | Q(deleted_at__isnull=False, deleted_by__isnull=False),
                name="ck_deviation_deleted_pair",
            ),
            models.CheckConstraint(condition=Q(version__gte=1), name="ck_deviation_version"),
        ]
        indexes = [
            models.Index(
                fields=["document"],
                condition=Q(deleted_at__isnull=True),
                name="ix_deviation_document",
            ),
        ]


class DeviationChecker(models.Model):
    """개선조치 확인 슬롯 지정자(ERD v5 A12). 슬롯 1개에 여러 명."""

    pk = models.CompositePrimaryKey("deviation", "staff")
    deviation = models.ForeignKey(
        DeviationAction,
        models.CASCADE,
        db_column="deviation_id",
        related_name="checkers",
        db_index=False,  # PK(deviation_id, staff_id)가 대신한다
    )
    staff = models.ForeignKey(
        Staff, models.PROTECT, db_column="staff_id", related_name="+", db_index=False
    )  # ix_deviation_checker_staff가 대신한다

    class Meta:
        db_table = "deviation_checker"
        indexes = [models.Index(fields=["staff"], name="ix_deviation_checker_staff")]
