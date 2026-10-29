"""관리 설정(ADM) 서비스 — 묶음 ① 품목별 CCP(F10·F11)·공통 이력(F20), 묶음 ② 직원(F12~F15·F17)·
문서 권한(F18·F19)·가져오기(F21), 묶음 ③ 비활성 영향(F16). p16-s2-spec 2장·3.2·3.4·5장.

- 쓰기는 API가 연 한 트랜잭션 안: 본문 검사 → 대상 읽기 → 조건부 UPDATE(version) → 이력.
- 권한 검사 없음(D-257 Q2 b) — 현재 사용자(X-Staff-Id)는 이력의 "누가"로만 씀.
- 수불 품목은 `Item` 모델을 읽기만 한다. 배치 수는 계약 뷰 `v_doc_batch`.
- 직원 쓰기는 수불 `staff_admin`(스스로 커밋 안 함)만 부른다. 처음 설정(활성 직원 0명)만 현재 사용자
  없이 등록·다시 활성(R62) — 이력 누가 = 그 직원, action `bootstrap_*`(R63).
"""

from django.db import connection
from django.db.models import Q
from django.utils import timezone

from apps.core.trace import step
from apps.inventory import staff_admin
from apps.inventory.models import Item
from apps.staff import roles
from apps.staff import services as staff_services
from apps.staff.models import Staff

from . import errors, store
from .errors import detail
from .models import (
    MODES,
    PROCESSES,
    REASON_MAX,
    AdminChangeLog,
    CcpDefault,
    ItemCcp,
    RoleForm,
    RoleFormMember,
    RoleLeader,
)

PRODUCIBLE_TYPE = "SEMI"  # ADM-R03: 수불 PRODUCIBLE_ITEM_TYPES와 같음(반제품만)
ITEM_PROCESS_TYPE = "MANUFACTURE"  # 반제품 = 제조 배치
HISTORY_MAX = 200
HISTORY_TARGETS = {
    "item_ccp": ("item_ccp",),
    "staff": ("staff",),
    "roles": ("role_leader", "role_form", "roles_import"),
}


def _log(actor_id, target, target_id, action, before, after, reason=None):
    AdminChangeLog.objects.create(
        target=target,
        target_id=target_id,
        action=action,
        before_json=before,
        after_json=after,
        reason=reason,
        actor_id=actor_id,
        at=timezone.now(),
    )


# ---------------------------------------------------------------- 품목별 CCP (F10·F11)


def _defaults():
    return {d.process_type: d.processes for d in CcpDefault.objects.all()}


def _batch_counts():
    """품목별 생산 전·생산 중 배치 수(제조). SQL 1."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT item_id, status, COUNT(*) FROM v_doc_batch"
            " WHERE process_type = %s AND status IN ('PLANNED', 'IN_PROGRESS')"
            " GROUP BY item_id, status",
            [ITEM_PROCESS_TYPE],
        )
        rows = cursor.fetchall()
    counts = {}
    for item_id, status, n in rows:
        counts.setdefault(item_id, {"PLANNED": 0, "IN_PROGRESS": 0})[status] = n
    return counts


def _state(setting):
    """설정 행 → {mode, processes, version}. 행 없음 = 기본 따름·버전 0(R01·R10)."""
    if setting is None:
        return {"mode": "default", "processes": [], "version": 0}
    return {"mode": setting.mode, "processes": setting.processes, "version": setting.version}


def _row(item, setting, default, counts):
    state = _state(setting)
    count = counts.get(item.pk, {})
    return {
        "item_id": item.pk,
        "item_code": item.item_code,
        "name": item.name,
        "is_active": item.is_active,
        **state,
        "effective": state["processes"] if state["mode"] == "own" else list(default),
        "planned_batches": count.get("PLANNED", 0),
        "running_batches": count.get("IN_PROGRESS", 0),
    }


def list_item_ccp(q="", include_inactive=False, only_own=False):
    """F10(A01): 반제품 + 설정 + 배치 수. SQL 4(기본·품목·설정·배치 수)."""
    with step("ADM-CCP-LST-01", "ADM", "반제품·설정 읽기"):
        defaults = _defaults()
        default = defaults.get(ITEM_PROCESS_TYPE, [])
        items = Item.objects.filter(item_type_id=PRODUCIBLE_TYPE)
        if not include_inactive:
            items = items.filter(is_active=True)
        text = (q or "").strip()
        if text:
            items = items.filter(Q(name__icontains=text) | Q(item_code__icontains=text))
        items = list(items.order_by("item_code"))
        settings = {s.item_id: s for s in ItemCcp.objects.filter(item_id__in=[i.pk for i in items])}
        if only_own:
            items = [i for i in items if getattr(settings.get(i.pk), "mode", None) == "own"]
    with step("ADM-CCP-LST-02", "ADM", "생산 전·생산 중 배치 수(v_doc_batch)"):
        counts = _batch_counts()
    return {
        "default": {k: v for k, v in defaults.items()},
        "items": [_row(i, settings.get(i.pk), default, counts) for i in items],
    }


def _check_body(body):
    """R01·R02·R10·R11. 반환 (mode, processes, reason, expected_version)."""
    problems = []
    unknown = sorted(set(body) - {"mode", "processes", "reason", "expected_version"})
    for key in unknown:
        problems.append(detail(key, "unknown_key", "알 수 없는 항목입니다."))
    mode = body.get("mode")
    if mode not in MODES:
        problems.append(detail("mode", "invalid", "default 또는 own"))
    processes = body.get("processes", [])
    if not isinstance(processes, list) or any(p not in PROCESSES for p in processes):
        problems.append(detail("processes", "invalid_process", "1P·2B·3P만 고를 수 있습니다."))
        processes = []
    elif len(set(processes)) != len(processes):
        problems.append(detail("processes", "invalid_process", "같은 공정이 두 번 있습니다."))
    elif mode == "default" and processes:
        problems.append(
            detail("processes", "invalid_process", "기본 따름이면 공정을 보내지 않습니다.")
        )
    reason = body.get("reason")
    if reason is not None and not isinstance(reason, str):
        problems.append(detail("reason", "invalid", "글자여야 합니다."))
        reason = None
    reason = (reason or "").strip() or None
    if reason is not None and len(reason) > REASON_MAX:
        problems.append(detail("reason", "too_long", f"{REASON_MAX}자 이하"))
    expected = body.get("expected_version")
    if isinstance(expected, bool) or not isinstance(expected, int) or expected < 0:
        problems.append(detail("expected_version", "required", "0 이상의 정수(설정 없음 = 0)"))
    if problems:
        raise errors.ValidationFailed(details=problems)
    ordered = [p for p in PROCESSES if p in processes]
    return mode, ordered, reason, expected


def save_item_ccp(actor_id, item_id, body):
    """F11(A02): 조건부 저장. 같은 값이면 저장·이력 없음(changed False)."""
    with step("ADM-CCP-SAV-01", "ADM", "요청 확인"):
        if not isinstance(body, dict):
            raise errors.ValidationFailed(details=[detail("", "invalid", "객체여야 합니다.")])
        mode, processes, reason, expected = _check_body(body)
    with step("ADM-CCP-SAV-02", "ADM", "품목·설정 읽기"):
        item = Item.objects.filter(pk=item_id).first()
        if item is None:
            raise errors.ItemNotFound()
        if item.item_type_id != PRODUCIBLE_TYPE:
            raise errors.ValidationFailed(
                details=[detail("item_id", "not_producible", "반제품만 설정할 수 있습니다.")]
            )
        setting = ItemCcp.objects.filter(item_id=item_id).first()
        before = _state(setting)
        if before["version"] != expected:
            raise errors.VersionConflict()
    after_value = {"mode": mode, "processes": processes}
    before_value = {"mode": before["mode"], "processes": before["processes"]}
    if after_value == before_value:
        default = _defaults().get(ITEM_PROCESS_TYPE, [])
        return {"item": _row(item, setting, default, _batch_counts()), "changed": False}
    with step("ADM-CCP-SAV-03", "ADM", "조건부 저장(version)"):
        now = timezone.now()
        flags = ItemCcp.flags(processes)
        if setting is None:
            setting = ItemCcp.objects.create(
                item_id=item_id, mode=mode, version=1, updated_at=now, **flags
            )
        else:
            n = ItemCcp.objects.filter(pk=setting.pk, version=expected).update(
                mode=mode, version=expected + 1, updated_at=now, **flags
            )
            if n != 1:
                raise errors.VersionConflict()
            setting.refresh_from_db()
    with step("ADM-CCP-SAV-04", "ADM", "이력"):
        _log(
            actor_id,
            "item_ccp",
            item_id,
            "set" if mode == "own" else "default",
            before_value,
            after_value,
            reason,
        )
    default = _defaults().get(ITEM_PROCESS_TYPE, [])
    return {"item": _row(item, setting, default, _batch_counts()), "changed": True}


# ---------------------------------------------------------------- 이력 (F20)


def _labels(rows):
    """대상 이름 — 품목·직원 "이름(코드)", 양식 행 = 양식 코드, 팀장·가져오기 = 고정 문구.

    지워진 품목이면 None. SQL은 그 대상이 있을 때만(품목 1·직원 1·양식 1).
    """
    out = {}
    item_ids = {r.target_id for r in rows if r.target == "item_ccp"}
    if item_ids:
        found = Item.objects.filter(pk__in=item_ids).values_list("pk", "name", "item_code")
        out.update({("item_ccp", pk): f"{name}({code})" for pk, name, code in found})
    staff_ids = {r.target_id for r in rows if r.target == "staff"}
    if staff_ids:
        found = Staff.objects.filter(pk__in=staff_ids).values_list("pk", "name", "staff_code")
        out.update({("staff", pk): f"{name}({code})" for pk, name, code in found})
    form_ids = {r.target_id for r in rows if r.target == "role_form"}
    if form_ids:
        found = RoleForm.objects.filter(pk__in=form_ids).values_list("pk", "type_code")
        out.update({("role_form", pk): code for pk, code in found})
    out[("role_leader", 0)] = "HACCP팀장"
    out[("roles_import", 0)] = "문서 권한 가져오기"
    return out


def history(target, target_id=None, limit=HISTORY_MAX):
    """F20(A11): 최신순, 사람 이름·대상 이름(label) 붙임. SQL 2 + 대상 종류마다 1."""
    with step("ADM-HIS-01", "ADM", "변경 이력"):
        if target not in HISTORY_TARGETS:
            raise errors.ValidationFailed(
                details=[detail("target", "invalid", "item_ccp·staff·roles")]
            )
        if target_id is not None and (
            isinstance(target_id, bool) or not isinstance(target_id, int) or target_id < 0
        ):
            raise errors.ValidationFailed(details=[detail("target_id", "invalid", "0 이상 정수")])
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= HISTORY_MAX:
            raise errors.ValidationFailed(details=[detail("limit", "invalid", f"1~{HISTORY_MAX}")])
        rows = AdminChangeLog.objects.filter(target__in=HISTORY_TARGETS[target])
        if target_id is not None:
            rows = rows.filter(target_id=target_id)
        rows = list(rows.order_by("-at", "-pk")[:limit])
        names = staff_services.names_of({r.actor_id for r in rows})
        labels = _labels(rows)
        return {
            "items": [
                {
                    "log_id": r.pk,
                    "label": labels.get((r.target, r.target_id)),
                    # 검토 B5: 다른 API처럼 한국 시각
                    "at": timezone.localtime(r.at).isoformat(timespec="seconds"),
                    "actor": {"id": r.actor_id, "name": names.get(r.actor_id)},
                    "target": r.target,
                    "target_id": r.target_id,
                    "action": r.action,
                    "before": r.before_json,
                    "after": r.after_json,
                    "reason": r.reason,
                }
                for r in rows
            ]
        }


# ---------------------------------------------------------------- 직원 (F12~F15·F17, 묶음 ②)


def _person(staff):
    return {
        "id": staff.pk,
        "staff_code": staff.staff_code,
        "name": staff.name,
        "is_active": staff.is_active,
        "created_at": staff.created_at.isoformat() if staff.created_at else None,
    }


def _role_index(rows):
    """F02 행 → 직원 id별 {is_leader, owner_of, writer_of}(비활성 포함)."""
    index = {}

    def at(sid):
        return index.setdefault(sid, {"is_leader": False, "owner_of": [], "writer_of": []})

    for p in rows["leaders"]:
        at(p["id"])["is_leader"] = True
    for type_code, form in sorted(rows["forms"].items()):
        for p in form["owners"]:
            at(p["id"])["owner_of"].append(type_code)
        for p in form["writers"]:
            at(p["id"])["writer_of"].append(type_code)
    return index


STAFF_STATES = ("active", "inactive", "all")
NO_ROLES = {"is_leader": False, "owner_of": [], "writer_of": []}


def staff_list(q="", state="all"):
    """F12(A03): 직원 + 역할 요약 + setup{no_active_staff}. 현재 사용자 없이도 읽음(R69). SQL 4."""
    with step("ADM-STF-LST-01", "ADM", "직원·역할 요약 읽기"):
        if state not in STAFF_STATES:
            raise errors.ValidationFailed(
                details=[detail("state", "invalid", "active·inactive·all")]
            )
        people = Staff.objects.order_by("id")
        if state != "all":
            people = people.filter(is_active=state == "active")
        text = (q or "").strip()
        if text:
            people = people.filter(Q(name__icontains=text) | Q(staff_code__icontains=text))
        index = _role_index(store.role_rows())
        items = [{**_person(p), "roles": index.get(p.pk, NO_ROLES)} for p in people]
        return {
            "setup": {"no_active_staff": staff_admin.active_count() == 0},
            "items": items,
        }


def suggest_staff_code():
    """F13(A04): R21."""
    with step("ADM-STF-COD-01", "ADM", "코드 제안"):
        return {"code": staff_admin.next_code()}


def _staff_error(error):
    if error.code == "not_found":
        return errors.StaffNotFound()
    return errors.ValidationFailed(details=[detail(error.field, error.code, error.message)])


def _only_keys(body, allowed):
    if not isinstance(body, dict):
        raise errors.ValidationFailed(details=[detail("", "invalid", "객체여야 합니다.")])
    unknown = sorted(set(body) - set(allowed))
    if unknown:
        raise errors.ValidationFailed(
            details=[detail(k, "unknown_key", "알 수 없는 항목입니다.") for k in unknown]
        )


def _bootstrap_allowed():
    """R62: 같은 트랜잭션(BEGIN IMMEDIATE)에서 활성 직원 0명일 때만 현재 사용자 없이."""
    if staff_admin.active_count() != 0:
        raise errors.ValidationFailed(
            details=[detail("X-Staff-Id", "setup_finished", errors.SETUP_FINISHED)]
        )


def create_staff(actor_id, body):
    """F14(A05): {name, staff_code}. actor_id None = 처음 설정(R62·R63). 반환 {staff}."""
    with step("ADM-STF-NEW-01", "ADM", "요청 확인"):
        _only_keys(body, ("name", "staff_code"))
    with step("ADM-STF-NEW-02", "ADM", "처음 설정 판정(현재 사용자 없을 때)") as s:
        if actor_id is None:
            _bootstrap_allowed()
            s.note("활성 직원 0명 — 처음 설정")
        else:
            s.skip("현재 사용자 있음")
    with step("ADM-STF-NEW-03", "ADM", "수불 staff_admin.create"):
        try:
            staff = staff_admin.create(body.get("name"), body.get("staff_code"))
        except staff_admin.StaffAdminError as error:
            raise _staff_error(error) from None
    with step("ADM-STF-NEW-04", "ADM", "이력"):
        _log(
            actor_id if actor_id is not None else staff.pk,
            "staff",
            staff.pk,
            "create" if actor_id is not None else "bootstrap_create",
            None,
            {"staff_code": staff.staff_code, "name": staff.name},
        )
    return {"staff": {**_person(Staff.objects.get(pk=staff.pk)), "roles": NO_ROLES}}


def _staff_out(staff_id):
    index = _role_index(store.role_rows())
    return {**_person(Staff.objects.get(pk=staff_id)), "roles": index.get(staff_id, NO_ROLES)}


def rename_staff(actor_id, staff_id, body):
    """F15(A06): {name}만(staff_code 등 다른 키 unknown_key — R22). 같은 이름이면 이력 없음."""
    with step("ADM-STF-REN-01", "ADM", "요청 확인"):
        _only_keys(body, ("name",))
        if "name" not in body:
            raise errors.ValidationFailed(details=[detail("name", "required", "이름")])
    with step("ADM-STF-REN-02", "ADM", "수불 staff_admin.rename"):
        try:
            staff, before = staff_admin.rename(staff_id, body["name"])
        except staff_admin.StaffAdminError as error:
            raise _staff_error(error) from None
    changed = before != staff.name
    with step("ADM-STF-REN-03", "ADM", "이력") as s:
        if changed:
            _log(actor_id, "staff", staff_id, "rename", {"name": before}, {"name": staff.name})
        else:
            s.skip("같은 이름")
    return {"staff": _staff_out(staff_id), "changed": changed}


def set_staff_active(actor_id, staff_id, body):
    """F17(A08): {active, confirm_impact?}. 비활성은 확인 필수(R25)·마지막 활성 직원 불가(R65).

    actor_id None = 처음 설정 — 다시 활성만, 활성 직원 0명일 때만(R62). 같은 값이면 이력 없음.
    """
    with step("ADM-STF-ACT-01", "ADM", "요청 확인"):
        _only_keys(body, ("active", "confirm_impact"))
        active = body.get("active")
        if not isinstance(active, bool):
            raise errors.ValidationFailed(details=[detail("active", "required", "true·false")])
        confirm = body.get("confirm_impact", False)
        if not isinstance(confirm, bool):
            raise errors.ValidationFailed(
                details=[detail("confirm_impact", "invalid", "true·false")]
            )
    with step("ADM-STF-ACT-02", "ADM", "대상·판정"):
        try:
            current = staff_admin.get(staff_id)
        except staff_admin.StaffAdminError as error:
            raise _staff_error(error) from None
        if actor_id is None:
            if not active:
                raise staff_services.StaffHeaderMissing()  # 비활성은 현재 사용자 필요(R27)
            _bootstrap_allowed()
        elif not active and current.is_active:
            if not confirm:
                raise errors.ValidationFailed(
                    details=[
                        detail(
                            "confirm_impact",
                            "confirm_required",
                            "영향을 확인한 뒤 confirm_impact: true로 보내세요.",
                        )
                    ]
                )
            if staff_admin.active_count() <= 1:
                raise errors.ValidationFailed(
                    details=[
                        detail(
                            "active",
                            "last_active_staff",
                            "마지막 활성 직원은 비활성할 수 없습니다.",
                        )
                    ]
                )
    with step("ADM-STF-ACT-03", "ADM", "수불 staff_admin.set_active"):
        staff, before = staff_admin.set_active(staff_id, active)
    changed = before != staff.is_active
    with step("ADM-STF-ACT-04", "ADM", "이력") as s:
        if changed:
            if actor_id is None:
                action, who = "bootstrap_activate", staff_id
            else:
                action, who = ("activate" if active else "deactivate"), actor_id
            _log(who, "staff", staff_id, action, {"is_active": before}, {"is_active": active})
        else:
            s.skip("같은 값")
    return {"staff": _staff_out(staff_id), "changed": changed}


# ---------------------------------------------------------------- 비활성 영향 (F16, 묶음 ③)


def _orphaned(rows, now, staff_id, active_forms):
    """이 사람을 빼면 활성 보유자가 0명이 되는 곳(S1a Q10 — 3.4 orphaned).

    effect: submit_blocked(그 역할 칸이 있는 양식은 상신 막힘) · write_leader_only(결재 칸에
    담당자가 없는 양식 — 담당자 0명이면 작성은 HACCP팀장·작성 권한자만). 팀장 0명은 type_code
    None 한 줄 + 팀장 칸이 있는 활성 양식 목록. 이미 비활성인 사람은 효과가 없어 빈 목록.
    """
    if staff_id not in now.people:
        return []

    def without(people):
        return [{**p, "is_active": False} if p["id"] == staff_id else p for p in people]

    after = roles._resolve(
        {
            **rows,
            "leaders": without(rows["leaders"]),
            "forms": {
                t: {**f, "owners": without(f["owners"]), "writers": without(f["writers"])}
                for t, f in rows["forms"].items()
            },
        }
    )
    names = dict(active_forms)
    out = []
    if now.leaders and not after.leaders:
        out.append(
            {
                "type_code": None,
                "name": "HACCP팀장",
                "role": "leader",
                "effect": "submit_blocked",
                "forms": [
                    t for t, _n in active_forms if t in now.forms and "leader" in now.forms[t].slots
                ],
            }
        )
    for type_code, _name in active_forms:
        form_now, form_after = now.forms.get(type_code), after.forms.get(type_code)
        if form_now is None or not form_now.owners or form_after.owners:
            continue
        out.append(
            {
                "type_code": type_code,
                "name": names[type_code],
                "role": "owner",
                "effect": "submit_blocked" if "owner" in form_now.slots else "write_leader_only",
            }
        )
    return out


def staff_impact(staff_id, current_user_id=None):
    """F16(A07): 비활성 영향(3.4). 읽기만 — 처음 설정의 다시 활성 행에서도 씀(R61, 헤더 없이)."""
    from apps.approvals import services as apr
    from apps.documents import services as doc

    with step("ADM-STF-IMP-01", "ADM", "대상"):
        try:
            person = staff_admin.get(staff_id)
        except staff_admin.StaffAdminError as error:
            raise _staff_error(error) from None
    with step("ADM-STF-IMP-02", "ADM", "문서 권한·0명이 되는 곳"):
        rows = store.role_rows()
        active = _active_forms()
        role = _role_index(rows).get(staff_id, NO_ROLES)
        now = roles._resolve(rows)
        orphaned = _orphaned(rows, now, staff_id, active)
    with step("ADM-STF-IMP-03", "ADM", "결재 대기(APR)"):
        slots = apr.pending_slots_of(staff_id)
    with step("ADM-STF-IMP-04", "ADM", "개선조치 확인·지정 점검자(DOC)"):
        checks = doc.pending_checks_of(staff_id)
        inspector = doc.inspector_docs_of(staff_id)
    return {
        "staff": _person(person),
        "roles": role,
        "pending_approvals": slots["count"],
        "sole_approvals": slots["sole"],
        "pending_checks": checks,
        "inspector_docs": inspector,
        "orphaned": orphaned,
        "active_leaders": len(now.leaders),
        "last_active": person.is_active and staff_admin.active_count() <= 1,
        "is_current_user": current_user_id is not None and current_user_id == staff_id,
    }


# ---------------------------------------------------------------- 문서 권한 (F18·F19)


def _active_forms():
    """DOC 활성 양식(최신 버전) [(type_code, name)] — 순서는 DOC 목록 그대로. SQL 1."""
    from apps.documents import services as doc

    return [(t["type_code"], t["name"]) for t in doc.list_templates()]


def _person_out(p):
    return {
        "id": p["id"],
        "staff_code": p["staff_code"],
        "name": p["name"],
        "is_active": p["is_active"],
    }


def roles_for_edit():
    """F18(A09): 문서 권한(비활성 사람 포함) + 활성 양식 순서 + 경고 + setup(R38). SQL 3."""
    with step("ADM-ROL-GET-01", "ADM", "문서 권한·활성 양식 읽기"):
        rows = store.role_rows()
        active = _active_forms()
    with step("ADM-ROL-GET-02", "ADM", "경고 계산(같은 행으로)"):
        config = roles._resolve(rows)
        summary_setup = roles.setup(config, active)
        forms = []
        for type_code, name in active:
            row = rows["forms"].get(type_code)
            form = config.forms.get(type_code)
            forms.append(
                {
                    "type_code": type_code,
                    "name": name,
                    "slots": row["slots"] if row else None,
                    "labels": dict(form.labels) if form else {},
                    "owners": [_person_out(p) for p in row["owners"]] if row else [],
                    "writers": [_person_out(p) for p in row["writers"]] if row else [],
                    "warnings": [
                        w
                        for w in config.warnings
                        if w.get("type_code") == type_code
                        or str(w.get("where", "")).startswith(f"forms.{type_code}.")
                    ],
                }
            )
        return {
            "version": rows["version"],
            "setup": summary_setup,
            "leaders": [_person_out(p) for p in rows["leaders"]],
            "forms": forms,
            "warnings": config.warnings,
        }


def _id_list(value, path, problems):
    if not isinstance(value, list) or any(
        isinstance(v, bool) or not isinstance(v, int) for v in value
    ):
        problems.append(detail(path, "invalid", "직원 id 정수 목록"))
        return None
    if len(set(value)) != len(value):
        problems.append(detail(path, "duplicate", "같은 직원이 두 번 있습니다."))
        return None
    return sorted(value)


def _check_roles_body(body):
    """ADM-ROL-01: R31·R34 형식. 반환 (expected, leaders|None, {type_code: {owner?, writer?}})."""
    _only_keys(body, ("expected_version", "leaders", "forms"))
    problems = []
    expected = body.get("expected_version")
    if isinstance(expected, bool) or not isinstance(expected, int) or expected < 1:
        problems.append(detail("expected_version", "required", "1 이상의 정수"))
    leaders = None
    if "leaders" in body:
        leaders = _id_list(body["leaders"], "leaders", problems)
    forms = {}
    raw_forms = body.get("forms", {})
    if not isinstance(raw_forms, dict):
        problems.append(detail("forms", "invalid", "양식 코드 → {owners, writers}"))
        raw_forms = {}
    for type_code, form in raw_forms.items():
        where = f"forms.{type_code}"
        if not isinstance(form, dict):
            problems.append(detail(where, "invalid", "객체여야 합니다."))
            continue
        for key in sorted(set(form) - {"owners", "writers"}):
            problems.append(
                detail(f"{where}.{key}", "unknown_key", "담당자·작성 권한자만 바꿉니다.")
            )
        wanted = {}
        for role, key in (("owner", "owners"), ("writer", "writers")):
            if key in form:
                ids = _id_list(form[key], f"{where}.{key}", problems)
                if ids is not None:
                    wanted[role] = ids
        forms[type_code] = wanted
    if problems:
        raise errors.ValidationFailed(details=problems)
    return expected, leaders, forms


def save_roles(actor_id, body):
    """F19(A10): 팀장 + 보낸 양식들의 담당자·작성 권한자 전체, 전체 버전 조건부(R32~R37).

    바뀐 곳이 없으면 저장·버전·이력 없음(changes 빈 목록).
    """
    with step("ADM-ROL-SAV-01", "ADM", "본문 검사"):
        expected, leaders, forms = _check_roles_body(body)
    with step("ADM-ROL-SAV-02", "ADM", "버전·지금 문서 권한 읽기"):
        rows = store.role_rows()
        if rows["version"] != expected:
            raise errors.VersionConflict()
    with step("ADM-ROL-SAV-03", "ADM", "직원 확인(없는 id·새로 넣는 비활성)"):
        problems = []
        unknown_forms = [t for t in forms if t not in rows["forms"]]
        for type_code in unknown_forms:
            problems.append(detail(f"forms.{type_code}", "unknown_form", "없는 양식입니다."))
        wanted_ids = set(leaders or [])
        for form in forms.values():
            for ids in form.values():
                wanted_ids.update(ids)
        found = dict(Staff.objects.filter(pk__in=wanted_ids).values_list("id", "is_active"))
        before = {("leader", None): {p["id"] for p in rows["leaders"]}}
        for type_code, row in rows["forms"].items():
            before[("owner", type_code)] = {p["id"] for p in row["owners"]}
            before[("writer", type_code)] = {p["id"] for p in row["writers"]}
        after = {}
        if leaders is not None:
            after[("leader", None)] = set(leaders)
        for type_code, form in forms.items():
            if type_code in unknown_forms:
                continue
            for role, ids in form.items():
                after[(role, type_code)] = set(ids)
        for (role, type_code), ids in after.items():
            path = "leaders" if role == "leader" else f"forms.{type_code}.{role}s"
            for sid in sorted(ids):
                if sid not in found:
                    problems.append(detail(path, "unknown_staff", f"없는 직원 {sid}"))
                elif not found[sid] and sid not in before[(role, type_code)]:
                    problems.append(
                        detail(
                            path, "inactive_staff", f"비활성 직원 {sid}은 새로 넣을 수 없습니다."
                        )
                    )
        if problems:
            raise errors.ValidationFailed(details=problems)
    changes = [
        {
            "role": role,
            "type_code": type_code,
            "before": sorted(before[(role, type_code)]),
            "after": sorted(ids),
        }
        for (role, type_code), ids in sorted(
            after.items(), key=lambda kv: (kv[0][1] or "", kv[0][0])
        )
        if ids != before[(role, type_code)]
    ]
    with step("ADM-ROL-SAV-04", "ADM", "바뀐 팀장·양식 사람만 다시 쓰기") as s:
        for change in changes:
            if change["role"] == "leader":
                store.replace_leaders(change["after"])
            else:
                form_id = rows["forms"][change["type_code"]]["id"]
                store.replace_members(form_id, change["role"], change["after"])
        s.note(f"바뀐 곳 {len(changes)}")
    version = rows["version"]
    with step("ADM-ROL-SAV-05", "ADM", "버전 +1(조건부)") as s:
        if changes:
            version = store.bump_role_version(expected)
            if version is None:
                raise errors.VersionConflict()
        else:
            s.skip("바뀐 곳 없음")
    with step("ADM-ROL-SAV-06", "ADM", "이력(바뀐 곳마다)") as s:
        for change in changes:
            if change["role"] == "leader":
                target, target_id, extra = "role_leader", 0, {}
            else:
                target = "role_form"
                target_id = rows["forms"][change["type_code"]]["id"]
                extra = {"role": change["role"]}
            _log(
                actor_id,
                target,
                target_id,
                "change",
                {**extra, "staff_ids": change["before"]},
                {**extra, "staff_ids": change["after"]},
            )
        if not changes:
            s.skip("바뀐 곳 없음")
    with step("ADM-ROL-SAV-07", "ADM", "경고 계산(0명 역할 — R35)"):
        config = roles._resolve(store.role_rows())
        warnings = config.warnings
    return {"version": version, "changes": changes, "warnings": warnings}


# ---------------------------------------------------------------- 가져오기 (F21)


class ImportFailed(Exception):
    """import_roles 실패(종료 코드 2) — message와 줄 목록."""

    def __init__(self, message, lines=()):
        super().__init__(message)
        self.message, self.lines = message, list(lines)


def import_roles(data, actor_code, replace=False):
    """F21(R41~R44): roles.json 모양 data → 문서 권한. 호출자 트랜잭션 안. 반환 보고 dict.

    - 형식 오류·actor 없음/비활성·없는 직원 코드 하나라도 → ImportFailed(아무것도 안 넣음)
    - 사람이 이미 있으면 replace 없이는 거부. replace면 팀장과 파일에 있는 양식의 사람만
      파일대로(파일에 없는 양식의 담당자·작성 권한자는 그대로 — R43, D-270 B1)
    - 파일의 slots·labels를 그 양식 행에 반영, 양식 행 없는 양식은 경고 후 건너뜀
    - 버전 +1, 이력 roles_import 1행(누가 = actor)
    """
    problems = roles.validate_file_data(data)
    if problems:
        raise ImportFailed("역할 파일 형식 오류", problems)
    actor = Staff.objects.filter(staff_code=actor_code or "").first()
    if actor is None or not actor.is_active:
        raise ImportFailed("--actor는 활성 직원 코드여야 합니다(R44)", [str(actor_code or "")])
    codes = set(data["haccp_leaders"])
    for form in data["forms"].values():
        codes.update(form["owners"])
        codes.update(form.get("writers", []))
    ids = dict(Staff.objects.filter(staff_code__in=codes).values_list("staff_code", "id"))
    missing = sorted(codes - set(ids))
    if missing:
        raise ImportFailed("staff에 없는 직원 코드(R42) — 먼저 직원을 등록하세요", missing)
    store.ensure_role_version()
    rows = store.role_rows()
    has_people = bool(rows["leaders"]) or any(
        f["owners"] or f["writers"] for f in rows["forms"].values()
    )
    if has_people and not replace:
        raise ImportFailed("문서 권한에 이미 사람이 있습니다 — 바꾸려면 --replace(R43)")
    target_ids = [rows["forms"][t]["id"] for t in data["forms"] if t in rows["forms"]]
    RoleLeader.objects.all().delete()
    RoleFormMember.objects.filter(role_form_id__in=target_ids).delete()
    RoleLeader.objects.bulk_create([RoleLeader(staff_id=ids[c]) for c in data["haccp_leaders"]])
    skipped, applied = [], []
    for type_code, form in data["forms"].items():
        row = rows["forms"].get(type_code)
        if row is None:
            skipped.append(type_code)
            continue
        labels = form.get("labels", {})
        RoleForm.objects.filter(pk=row["id"]).update(
            slots=form["slots"],
            label_owner=(labels.get("owner") or "").strip() or None,
            label_leader=(labels.get("leader") or "").strip() or None,
        )
        RoleFormMember.objects.bulk_create(
            [
                RoleFormMember(role_form_id=row["id"], role="owner", staff_id=ids[c])
                for c in form["owners"]
            ]
            + [
                RoleFormMember(role_form_id=row["id"], role="writer", staff_id=ids[c])
                for c in form.get("writers", [])
            ]
        )
        applied.append(type_code)
    version = store.bump_role_version()
    inactive = sorted(c for c in codes if not Staff.objects.get(pk=ids[c]).is_active)
    _log(
        actor.pk,
        "roles_import",
        0,
        "import",
        None,
        {
            "leaders": len(data["haccp_leaders"]),
            "forms": applied,
            "skipped": skipped,
            "replace": bool(replace),
        },
    )
    return {
        "version": version,
        "forms": applied,
        "skipped": skipped,
        "inactive_codes": inactive,
        "leaders": len(data["haccp_leaders"]),
    }
