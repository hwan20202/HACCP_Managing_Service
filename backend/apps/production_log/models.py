"""P15 PLG 생산 기준정보 — ERD v7.3(D-244). 생산일지 문서 자체는 DOC 표를 쓴다.

이 앱은 apps.inventory·doc_requirements.sources를 import하지 않는다(사람은 apps.staff 연결 모듈).
"""

from django.db import models
from django.db.models import Q
from django.db.models.functions import Length

from apps.staff.models import Staff

KINDS = ["CCP-1P", "CCP-2B", "CCP-3P", "INNER", "OUTER", "GEN"]
MODES = ["JUDGE", "TEMP_TIME", "QTY"]
DUR_UNITS = ["분", "시간", "일"]
TARGETS = ["process", "template"]


class TrimWhitespace(models.Transform):
    """trim(x, 공백·탭·줄바꿈) — DOC와 같은 정의(이름이 공백만인지 검사)."""

    lookup_name = "trim_ws"
    function = "TRIM"
    template = "TRIM(%(expressions)s, ' ' || char(9) || char(10) || char(13))"


models.TextField.register_lookup(Length)
models.TextField.register_lookup(TrimWhitespace)

ACTIONS = [
    "create",
    "update",
    "deactivate",
    "reactivate",
    "delete",
    "copy",
    "register",
    "overwrite",
]


def _name_checks(prefix, max_len):
    return [
        models.CheckConstraint(
            condition=Q(name__length__gte=1, name__length__lte=max_len) & ~Q(name__trim_ws=""),
            name=f"ck_{prefix}_name",
        ),
        models.CheckConstraint(condition=Q(name_key__length__gte=1), name=f"ck_{prefix}_name_key"),
    ]


class Process(models.Model):
    """공정 목록. 기본 제공 5종(kind ≠ GEN)은 잠금, 일반(GEN)은 입력 방식 필수."""

    process_id = models.AutoField(primary_key=True)
    name = models.TextField()
    name_key = models.TextField()  # 앱이 계산: 공백 정리·소문자(PLG-R13). 중복 판정용
    kind = models.TextField()
    mode = models.TextField(null=True, blank=True)
    is_builtin = models.BooleanField(default=False)
    description = models.TextField(null=True, blank=True)
    std_duration_value = models.FloatField(null=True, blank=True)
    std_duration_unit = models.TextField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(  # NULL = 시스템(기본 제공 시드)
        Staff,
        models.PROTECT,
        null=True,
        blank=True,
        db_column="created_by",
        related_name="+",
        db_index=False,
    )
    created_at = models.DateTimeField()
    updated_by = models.ForeignKey(
        Staff,
        models.PROTECT,
        null=True,
        blank=True,
        db_column="updated_by",
        related_name="+",
        db_index=False,
    )
    updated_at = models.DateTimeField()
    version = models.IntegerField(default=1, db_default=1)

    class Meta:
        db_table = "process"
        constraints = [
            *_name_checks("process", 40),
            models.CheckConstraint(condition=Q(kind__in=KINDS), name="ck_process_kind"),
            models.CheckConstraint(
                condition=Q(mode__isnull=True) | Q(mode__in=MODES), name="ck_process_mode"
            ),
            models.CheckConstraint(  # 일반 = 입력 방식 있음, 기본 제공 = 없음(기능이 정함)
                condition=(Q(kind="GEN") & Q(mode__isnull=False))
                | (~Q(kind="GEN") & Q(mode__isnull=True)),
                name="ck_process_kind_mode",
            ),
            models.CheckConstraint(
                condition=(Q(kind="GEN") & Q(is_builtin=False))
                | (~Q(kind="GEN") & Q(is_builtin=True)),
                name="ck_process_builtin",
            ),
            models.CheckConstraint(
                condition=Q(is_builtin=False) | Q(is_active=True), name="ck_process_builtin_active"
            ),
            models.CheckConstraint(
                condition=Q(description__isnull=True) | Q(description__length__lte=300),
                name="ck_process_description",
            ),
            models.CheckConstraint(
                condition=(Q(std_duration_value__isnull=True) & Q(std_duration_unit__isnull=True))
                | (  # NULL과 비교하면 CHECK가 통과하므로 isnull=False를 꼭 같이 둔다(check T11)
                    Q(std_duration_value__isnull=False, std_duration_value__gt=0)
                    & Q(std_duration_unit__isnull=False, std_duration_unit__in=DUR_UNITS)
                ),
                name="ck_process_std_duration",
            ),
            models.CheckConstraint(condition=Q(version__gte=1), name="ck_process_version"),
            models.UniqueConstraint(
                fields=["kind"], condition=~Q(kind="GEN"), name="ux_process_builtin"
            ),
            models.UniqueConstraint(
                fields=["name_key"], condition=Q(is_active=True), name="ux_process_name"
            ),
        ]


class ProcessTemplate(models.Model):
    """공정 템플릿(공정 순서 묶음). 이름은 사용자가 품목명·분류로 짓는다(품목 연결 없음)."""

    process_template_id = models.AutoField(primary_key=True)
    name = models.TextField()
    name_key = models.TextField()
    is_active = models.BooleanField(default=True)
    used_count = models.IntegerField(default=0, db_default=0)  # 불러온 횟수(삭제 가능 판단)
    last_used_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        Staff, models.PROTECT, db_column="created_by", related_name="+", db_index=False
    )
    created_at = models.DateTimeField()
    updated_by = models.ForeignKey(
        Staff, models.PROTECT, db_column="updated_by", related_name="+", db_index=False
    )
    updated_at = models.DateTimeField()
    version = models.IntegerField(default=1, db_default=1)

    class Meta:
        db_table = "process_template"
        constraints = [
            *_name_checks("process_template", 40),
            models.CheckConstraint(condition=Q(used_count__gte=0), name="ck_process_template_used"),
            models.CheckConstraint(
                condition=Q(used_count=0) | Q(last_used_at__isnull=False),
                name="ck_process_template_last_used",
            ),
            models.CheckConstraint(condition=Q(version__gte=1), name="ck_process_template_version"),
            models.UniqueConstraint(
                fields=["name_key"], condition=Q(is_active=True), name="ux_process_template_name"
            ),
        ]


class ProcessTemplateStep(models.Model):
    """템플릿의 공정 1개 = 1행. overrides_json = 공정 기본값과 다른 값만(PLG-F06)."""

    step_id = models.AutoField(primary_key=True)
    template = models.ForeignKey(
        ProcessTemplate,
        models.CASCADE,
        db_column="process_template_id",
        related_name="steps",
        db_index=False,  # UNIQUE(template, seq)가 덮는다
    )
    process = models.ForeignKey(
        Process,
        models.PROTECT,
        db_column="process_id",
        related_name="+",
        db_index=False,
    )
    seq = models.IntegerField()
    overrides_json = models.JSONField(default=dict)

    class Meta:
        db_table = "process_template_step"
        constraints = [
            models.CheckConstraint(condition=Q(seq__gte=1), name="ck_template_step_seq"),
            models.UniqueConstraint(fields=["template", "seq"], name="uq_template_step_seq"),
            models.UniqueConstraint(
                fields=["template", "process"], name="uq_template_step_process"
            ),
        ]
        indexes = [  # 공정 삭제 가능 여부·쓰는 템플릿 수(PLG-R15·F08)
            models.Index(fields=["process"], name="ix_template_step_process"),
        ]


class MasterChangeLog(models.Model):
    """공정·템플릿 변경 이력(PLG-R12). 대상이 지워져도 남으므로 대상 FK는 두지 않는다."""

    log_id = models.AutoField(primary_key=True)
    target = models.TextField()
    target_id = models.IntegerField()
    action = models.TextField()
    before_json = models.JSONField(null=True, blank=True)
    after_json = models.JSONField(null=True, blank=True)
    actor = models.ForeignKey(
        Staff, models.PROTECT, db_column="actor_id", related_name="+", db_index=False
    )
    document = models.ForeignKey(  # 생산일지에서 등록·덮어쓴 경우
        "documents.Document",
        models.PROTECT,
        null=True,
        blank=True,
        db_column="document_id",
        related_name="+",
        db_index=False,
    )
    at = models.DateTimeField()

    class Meta:
        db_table = "master_change_log"
        constraints = [
            models.CheckConstraint(condition=Q(target__in=TARGETS), name="ck_master_log_target"),
            models.CheckConstraint(condition=Q(action__in=ACTIONS), name="ck_master_log_action"),
            models.CheckConstraint(condition=Q(target_id__gte=1), name="ck_master_log_target_id"),
        ]
        indexes = [
            models.Index(fields=["target", "target_id", "-at"], name="ix_master_log_target"),
        ]
