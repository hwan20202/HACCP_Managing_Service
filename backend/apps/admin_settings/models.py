"""관리 설정(ADM) 표 — ERD v7.4 A26~A29(묶음 ① CCP·공통 이력). 문서 권한 A30~A33은 묶음 ②.

- 품목·배치·직원은 수불 표(`inventory` managed=False 모델)를 FK로 가리킨다.
  PK로 쓰지 않고 대리 키 + UNIQUE(SQLite rowid에 NULL을 넣으면 다음 번호가 붙음 — D-264).
- `item_ccp`만 RunSQL로 만든다: `REFERENCES items(id) ON DELETE CASCADE` — 수불 `item_removal.py`의
  직접 SQL 삭제를 DB가 따라감(D-263 Q1 a). Django 상태는 아래 모델 그대로(SeparateDatabaseAndState).
- bool 열은 `IN (0, 1)` CHECK(D-267 B2 — BooleanField는 CHECK를 만들지 않음).
"""

from django.db import models
from django.db.models import Q
from django.db.models.functions import Length

from apps.inventory.models import Item, ProductionBatch, Staff

PROCESSES = ("1P", "2B", "3P")  # ADM-R02·R09: 고정 3종, 이 순서
PROCESS_TYPES = ("MANUFACTURE", "PACKAGING")
MODES = ("default", "own")
TARGETS = ("item_ccp", "staff", "role_leader", "role_form", "roles_import")
ACTIONS = (
    "set",
    "default",
    "create",
    "rename",
    "deactivate",
    "activate",
    "change",
    "import",
    "bootstrap_create",
    "bootstrap_activate",
)
REASON_MAX = 100

models.TextField.register_lookup(Length)


def _bool_checks(prefix):
    return [
        models.CheckConstraint(
            condition=Q(**{f"ccp_{p.lower()}__in": (0, 1)}), name=f"ck_{prefix}_{p.lower()}"
        )
        for p in PROCESSES
    ]


class CcpSet(models.Model):
    """공정 집합 bool 3열(ADM-R02 — 순서·중복이 생길 수 없음, D-264 E-Q1 a)."""

    ccp_1p = models.BooleanField(default=False)
    ccp_2b = models.BooleanField(default=False)
    ccp_3p = models.BooleanField(default=False)

    class Meta:
        abstract = True

    @property
    def processes(self):
        return [p for p in PROCESSES if getattr(self, f"ccp_{p.lower()}")]

    @staticmethod
    def flags(processes):
        chosen = set(processes)
        return {f"ccp_{p.lower()}": p in chosen for p in PROCESSES}


class CcpDefault(CcpSet):
    """A26 전체 기본 CCP — 공정 구분별 1행. 마이그레이션으로만 바꿈(ADM-R04)."""

    process_type = models.TextField(primary_key=True)
    updated_at = models.DateTimeField()

    class Meta:
        db_table = "ccp_default"
        constraints = [
            models.CheckConstraint(
                condition=Q(process_type__in=PROCESS_TYPES), name="ck_ccp_default_type"
            ),
            *_bool_checks("ccp_default"),
        ]


class ItemCcp(CcpSet):
    """A27 품목 CCP 설정 — 품목당 0·1행(ADM-R01). 기본 따름으로 되돌려도 행을 지우지 않음."""

    id = models.AutoField(primary_key=True)
    item = models.OneToOneField(Item, models.CASCADE, db_column="item_id", related_name="+")
    mode = models.TextField()
    version = models.IntegerField(default=1)
    updated_at = models.DateTimeField()

    class Meta:
        db_table = "item_ccp"
        constraints = [
            models.CheckConstraint(condition=Q(mode__in=MODES), name="ck_item_ccp_mode"),
            models.CheckConstraint(condition=Q(version__gte=1), name="ck_item_ccp_version"),
            models.CheckConstraint(
                condition=Q(mode="own") | Q(ccp_1p=False, ccp_2b=False, ccp_3p=False),
                name="ck_item_ccp_default_empty",
            ),
            *_bool_checks("item_ccp"),
        ]


class BatchCcpApplied(CcpSet):
    """A28 배치 CCP 적용 기록 — 처음 생산 시작 때 결정한 집합(ADM-R05·R06). 빈 집합 = CCP 없음."""

    id = models.AutoField(primary_key=True)
    batch = models.OneToOneField(
        ProductionBatch, models.PROTECT, db_column="batch_id", related_name="+"
    )
    decided_at = models.DateTimeField()

    class Meta:
        db_table = "batch_ccp_applied"
        constraints = [*_bool_checks("batch_ccp")]


class AdminChangeLog(models.Model):
    """A29 관리 설정 변경 이력(A25 master_change_log 모양 — D-263 Q2 a). 대상 FK 없음."""

    log_id = models.AutoField(primary_key=True)
    target = models.TextField()
    target_id = models.IntegerField()
    action = models.TextField()
    before_json = models.JSONField(null=True, blank=True)
    after_json = models.JSONField(null=True, blank=True)
    reason = models.TextField(null=True, blank=True)
    at = models.DateTimeField()
    actor = models.ForeignKey(
        Staff, models.PROTECT, db_column="actor_id", related_name="+", db_index=False
    )

    class Meta:
        db_table = "admin_change_log"
        constraints = [
            models.CheckConstraint(condition=Q(target__in=TARGETS), name="ck_admin_log_target"),
            models.CheckConstraint(condition=Q(action__in=ACTIONS), name="ck_admin_log_action"),
            models.CheckConstraint(
                condition=Q(reason__isnull=True)
                | Q(reason__length__gte=1, reason__length__lte=REASON_MAX),
                name="ck_admin_log_reason",
            ),
        ]
        indexes = [
            models.Index(fields=["target", "target_id", "-at"], name="ix_admin_log_target"),
            models.Index(fields=["actor", "at"], name="ix_admin_log_actor"),
        ]
