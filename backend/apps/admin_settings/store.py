"""ADM 저장소 — 다른 단위(REQ)가 부르는 읽기·기록 함수(p16-s2-spec 3.1).

다른 단위를 import하지 않는다.
- ADM-F01 `ccp_for_batch`: 배치 CCP 적용 기록(A28). 기록이 있으면 그대로
  (R06 — 설정을 다시 읽지 않음), 없으면 품목 설정(own) → 공정 구분 기본(A26)으로 정해
  **기록하고** 돌려준다(R05). 호출자 트랜잭션 안.
- ADM-F03 `batch_ccp`: 여러 배치의 적용 기록(R08). 기록 없음 = None(생산 시작 전).
- ADM-F02 `role_rows`(묶음 ②): 문서 권한 원본(ROLE `load()`가 부름 — R30). SQL 2.
- ADM-F22 `ensure_form_rows`: 양식 설치 때 DOC가 부름 — 없는 양식 행만 기본 구성(R31).
- 아래 쓰기 도우미(`replace_people` 등)는 ADM 서비스·가져오기·개발 시드가 같은 트랜잭션에서 씀.
"""

from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from .models import PROCESSES, BatchCcpApplied, RoleForm, RoleFormMember, RoleLeader

CCP_TYPES = tuple(f"CCP-{p}" for p in PROCESSES)  # ADM-R09: 고정 3종, 1P→2B→3P

_DECIDE_SQL = (
    "SELECT d.ccp_1p, d.ccp_2b, d.ccp_3p, i.mode, i.ccp_1p, i.ccp_2b, i.ccp_3p"
    " FROM ccp_default d LEFT JOIN item_ccp i ON i.item_id = %s"
    " WHERE d.process_type = %s"
)


def _on(flags):
    return [p for p, on in zip(PROCESSES, flags, strict=True) if on]


def _decide(item_id, process_type):
    """R05: 품목 own이면 그 집합, 아니면 공정 구분 기본(기본 행이 없으면 없음). SQL 1."""
    with connection.cursor() as cursor:
        cursor.execute(_DECIDE_SQL, [item_id, process_type])
        row = cursor.fetchone()
    if row is None:
        return []
    if row[3] == "own":
        return _on(row[4:7])
    return _on(row[0:3])


def ccp_for_batch(batch_id, item_id, process_type):
    """F01: 기록 있으면 그것(SQL 1), 없으면 결정 + 기록(SQL 2). 반환 = 1P→2B→3P 목록."""
    row = BatchCcpApplied.objects.filter(batch_id=batch_id).first()
    if row is not None:
        return row.processes
    processes = _decide(item_id, process_type)
    try:
        with transaction.atomic():  # 저장점 — 동시 처음 시작이면 먼저 기록한 쪽을 따름
            BatchCcpApplied.objects.create(
                batch_id=batch_id, decided_at=timezone.now(), **BatchCcpApplied.flags(processes)
            )
    except IntegrityError:
        return BatchCcpApplied.objects.get(batch_id=batch_id).processes
    return processes


def batch_ccp(batch_ids):
    """F03: {batch_id: [..] | [] | None}. 빈 목록이면 SQL 없음, 아니면 1."""
    ids = sorted({int(i) for i in batch_ids})
    if not ids:
        return {}
    found = {r.batch_id: r.processes for r in BatchCcpApplied.objects.filter(batch_id__in=ids)}
    return {i: found.get(i) for i in ids}


# ---------------------------------------------------------------- 문서 권한 (묶음 ②)

# R31 기본 구성 — 지금 roles.json의 slots·labels(목록에 없는 양식은 owner_leader).
# 0004·F22가 같이 씀
DEFAULT_SLOTS = {"D01": "owner", "D02": "owner", "PROD-LOG": "none"}
DEFAULT_LABEL_OWNER = {"D10": "작성자"}


def default_form(type_code):
    """(slots, label_owner, label_leader)."""
    return DEFAULT_SLOTS.get(type_code, "owner_leader"), DEFAULT_LABEL_OWNER.get(type_code), None


_FORMS_SQL = (
    "SELECT c.version, f.id, f.type_code, f.slots, f.label_owner, f.label_leader"
    " FROM (SELECT 1) one LEFT JOIN role_config c ON c.id = 1"
    " LEFT JOIN role_form f ON 1 = 1 ORDER BY f.type_code"
)
_PEOPLE_SQL = (
    "SELECT 'leader', 0, s.id, s.staff_code, s.name, s.is_active"
    " FROM role_leader l JOIN staff s ON s.id = l.staff_id"
    " UNION ALL SELECT m.role, m.role_form_id, s.id, s.staff_code, s.name, s.is_active"
    " FROM role_form_member m JOIN staff s ON s.id = m.staff_id"
    " ORDER BY 3"
)


def role_rows():
    """F02: {version, leaders:[사람], forms:{type_code:{id, slots, labels, owners, writers}}}.

    사람 = {id, staff_code, name, is_active} — 비활성 포함(효과를 빼는 것은 ROLE). SQL 2.
    labels는 NULL이 아닌 문구만({"owner": "작성자"}). 버전 행이 없으면 version 0.
    """
    with connection.cursor() as cursor:
        cursor.execute(_FORMS_SQL)
        form_rows = cursor.fetchall()
        cursor.execute(_PEOPLE_SQL)
        people = cursor.fetchall()
    version = form_rows[0][0] if form_rows and form_rows[0][0] is not None else 0
    forms, by_id = {}, {}
    for _v, form_id, type_code, slots, label_owner, label_leader in form_rows:
        if form_id is None:
            continue
        labels = {k: v for k, v in (("owner", label_owner), ("leader", label_leader)) if v}
        form = {"id": form_id, "slots": slots, "labels": labels, "owners": [], "writers": []}
        forms[type_code] = by_id[form_id] = form
    leaders = []
    for role, form_id, sid, code, name, active in people:
        person = {"id": sid, "staff_code": code, "name": name, "is_active": bool(active)}
        if role == "leader":
            leaders.append(person)
        elif form_id in by_id:
            by_id[form_id]["owners" if role == "owner" else "writers"].append(person)
    return {"version": version, "leaders": leaders, "forms": forms}


def ensure_role_version():
    """버전 1행이 없으면 넣는다(0004가 넣지만 개발·테스트 DB 보정용). SQL 1."""
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO role_config (id, version, updated_at) VALUES (1, 1, %s)"
            " ON CONFLICT(id) DO NOTHING",
            [connection.ops.adapt_datetimefield_value(timezone.now())],
        )


def ensure_form_rows(type_codes):
    """F22(R31): 없는 양식 코드만 기본 구성으로 넣는다(있으면 그대로, 이력 없음).

    반환: 새로 넣은 코드.
    """
    codes = sorted({c for c in type_codes if c})
    if not codes:
        return []
    have = set(RoleForm.objects.filter(type_code__in=codes).values_list("type_code", flat=True))
    now = connection.ops.adapt_datetimefield_value(timezone.now())
    added = []
    with connection.cursor() as cursor:
        for code in codes:
            if code in have:
                continue
            slots, label_owner, label_leader = default_form(code)
            cursor.execute(
                "INSERT INTO role_form (type_code, slots, label_owner, label_leader, created_at)"
                " VALUES (%s, %s, %s, %s, %s) ON CONFLICT(type_code) DO NOTHING",
                [code, slots, label_owner, label_leader, now],
            )
            if cursor.rowcount:
                added.append(code)
    return added


def bump_role_version(expected=None):
    """버전 +1(expected가 있으면 조건부 — R32). 반환: 새 버전, 조건이 안 맞으면 None. SQL 1~2."""
    now = connection.ops.adapt_datetimefield_value(timezone.now())
    with connection.cursor() as cursor:
        if expected is None:
            cursor.execute(
                "UPDATE role_config SET version = version + 1, updated_at = %s WHERE id = 1", [now]
            )
        else:
            cursor.execute(
                "UPDATE role_config SET version = version + 1, updated_at = %s"
                " WHERE id = 1 AND version = %s",
                [now, expected],
            )
        if cursor.rowcount != 1:
            return None
        cursor.execute("SELECT version FROM role_config WHERE id = 1")
        return cursor.fetchone()[0]


def replace_leaders(staff_ids):
    """팀장 집합을 이 목록으로(빠진 사람 지우고 새 사람 넣기)."""
    wanted = set(staff_ids)
    have = set(RoleLeader.objects.values_list("staff_id", flat=True))
    RoleLeader.objects.filter(staff_id__in=have - wanted).delete()
    RoleLeader.objects.bulk_create([RoleLeader(staff_id=i) for i in sorted(wanted - have)])


def replace_members(form_id, role, staff_ids):
    """양식 행 하나의 한 역할(owner·writer) 사람 집합을 이 목록으로."""
    wanted = set(staff_ids)
    rows = RoleFormMember.objects.filter(role_form_id=form_id, role=role)
    have = set(rows.values_list("staff_id", flat=True))
    rows.filter(staff_id__in=have - wanted).delete()
    RoleFormMember.objects.bulk_create(
        [RoleFormMember(role_form_id=form_id, role=role, staff_id=i) for i in sorted(wanted - have)]
    )
