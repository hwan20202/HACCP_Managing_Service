"""관리 설정(ADM) 표 — ERD v7.4 A26~A29(묶음 ① CCP·공통 이력)·A30~A33(묶음 ② 문서 권한).

- 품목·배치·직원은 수불 표(`inventory` managed=False 모델)를 FK로 가리킨다.
  PK로 쓰지 않고 대리 키 + UNIQUE(SQLite rowid에 NULL을 넣으면 다음 번호가 붙음 — D-264).
- `item_ccp`만 RunSQL로 만든다: `REFERENCES items(id) ON DELETE CASCADE` — 수불 `item_removal.py`의
  직접 SQL 삭제를 DB가 따라감(D-263 Q1 a). Django 상태는 아래 모델 그대로(SeparateDatabaseAndState).
- bool 열은 `IN (0, 1)` CHECK(D-267 B2 — BooleanField는 CHECK를 만들지 않음).
- `role_config`(A30)는 RunSQL + managed=False: 행 삭제를 막는 트리거(D-267 B3)가 있어
  Django 테스트의 표 비우기(flush) 대상에서 빼야 한다. 1행은 0004가 넣는다.
"""

from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Length, Trim

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
SLOTS = ("owner", "owner_leader", "leader", "none")  # roles.SLOT_CONFIGS 키와 같음
MEMBER_ROLES = ("owner", "writer")
LABEL_MAX = 20  # roles.LABEL_MAX와 같음

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


# ---------------------------------------------------------------- 문서 권한 (A30~A33, 묶음 ②)


class RoleVersion(models.Model):
    """A30 문서 권한 전체 버전 1행(id = 1). 저장(R32)·가져오기(R44)마다 +1."""

    id = models.IntegerField(primary_key=True)
    version = models.IntegerField(default=1)
    updated_at = models.DateTimeField()

    class Meta:
        db_table = "role_config"
        managed = False


class RoleLeader(models.Model):
    """A31 HACCP팀장 — 사람당 1행."""

    id = models.AutoField(primary_key=True)
    staff = models.OneToOneField(Staff, models.DO_NOTHING, db_column="staff_id", related_name="+")

    class Meta:
        db_table = "role_leader"


class RoleForm(models.Model):
    """A32 양식 행 — 양식 코드당 1행(버전 무관, D-265). label NULL = 기본 문구."""

    id = models.AutoField(primary_key=True)
    type_code = models.TextField(unique=True)
    slots = models.TextField()
    label_owner = models.TextField(null=True, blank=True)
    label_leader = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField()

    class Meta:
        db_table = "role_form"
        constraints = [
            models.CheckConstraint(
                condition=Q(type_code__length__gte=1, type_code__length__lte=40),
                name="ck_role_form_type_code",
            ),
            models.CheckConstraint(condition=Q(slots__in=SLOTS), name="ck_role_form_slots"),
            *[
                models.CheckConstraint(
                    condition=Q(**{f"{col}__isnull": True})
                    | Q(
                        **{
                            col: Trim(F(col)),
                            f"{col}__length__gte": 1,
                            f"{col}__length__lte": LABEL_MAX,
                        }
                    ),
                    name=f"ck_role_form_{col}",
                )
                for col in ("label_owner", "label_leader")
            ],
        ]


class RoleFormMember(models.Model):
    """A33 양식 × 역할(owner·writer) × 직원. 담당자·작성 권한자 겹침 허용(R34)."""

    id = models.AutoField(primary_key=True)
    role_form = models.ForeignKey(
        RoleForm, models.DO_NOTHING, db_column="role_form_id", related_name="members"
    )
    role = models.TextField()
    staff = models.ForeignKey(Staff, models.DO_NOTHING, db_column="staff_id", related_name="+")

    class Meta:
        db_table = "role_form_member"
        constraints = [
            models.CheckConstraint(condition=Q(role__in=MEMBER_ROLES), name="ck_role_member_role"),
            models.UniqueConstraint(
                fields=["role_form", "role", "staff"], name="ux_role_form_member"
            ),
        ]
        indexes = [models.Index(fields=["staff"], name="ix_role_form_member_staff")]
