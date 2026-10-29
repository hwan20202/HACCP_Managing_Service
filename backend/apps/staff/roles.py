"""역할(P14 → P16) — HACCP팀장·양식별 담당자·작성 권한자·결재 칸 구성. 원본은 DB(ADM 문서 권한).

- 작성 권한자(``writers``, D-198 — 명세 ROLE-C08): 양식별, 작성(ROLE-R07, r13 D-201)과
  상신·재상신(ROLE-R01). 결재 칸 후보가 아니다.
- 작성(R07) = 담당자·작성 권한자·팀장 + 그 문서 점검자(점검자 값은 DOC가 넘김 — 이 모듈은
  문서를 읽지 않는다). 점검자 지정(R08) = 담당자·팀장.

- P16 묶음 ②(ADM-R30·R36): 원본 = ``adm.store.role_rows()``(문서 권한 표 — SQL 2). 저장 즉시 다음
  호출부터 적용(재시작 없음). 설정 파일·보관본·형식 오류 경로(옛 409)는 없앴다(Q5 a).
  ``roles.json``은 ``import_roles`` 입력용 — 형식 검사 ``validate_file_data``만 남긴다(R41).
- 사람은 ``staff.id``로 저장되고, 쓸 때마다 그 순간의 활성 여부로 효과를 정한다 — 비활성 직원은
  역할에서 빠진 것으로 보고 경고만(R-W2, ADM-R24). ``scope()`` 안에서는 한 번만 읽는다.
- 이 모듈은 ``staff``·ADM 저장소만 읽고 다른 단위(DOC·APR·WF·REQ)를 import하지 않는다(ROLE-NFR-01).
  흐름: dev-notes/admin/p16-s2-flows.md 4.3.
"""

import contextvars
from contextlib import contextmanager
from dataclasses import dataclass, field

from apps.admin_settings import store as adm_store
from apps.core.http import ApiError
from apps.core.trace import step

SLOT_CONFIGS = {
    "owner": ("owner",),
    "owner_leader": ("owner", "leader"),
    "leader": ("leader",),
    "none": (),  # P15: 결재 없는 양식(생산일지) — 결재선 없음, 작성 권한만
}
ROLE_NAMES = ("owner", "leader")
DEFAULT_LABELS = {"owner": "담당자", "leader": "HACCP팀장"}
LABEL_MAX = 20


class RoleRequired(ApiError):
    status = 403
    code = "ROLE_REQUIRED"
    message = "이 양식의 담당자나 HACCP팀장만 할 수 있습니다."
    SUBMIT = ("owner", "writer", "leader")  # ROLE-R01(r11 D-198) — 정정 시작(R04)은 기본값
    SUBMIT_MESSAGE = "이 양식의 담당자·작성 권한자나 HACCP팀장만 상신할 수 있습니다."

    def __init__(self, required=("owner", "leader"), message=None):
        super().__init__(
            message, [{"path": "", "code": "role_required", "required": list(required)}]
        )


class NoApprovalLine(ApiError):
    status = 409
    code = "NO_APPROVAL_LINE"
    message = "결재선을 만들 수 없습니다."
    MESSAGES = {
        "no_config": "이 양식의 결재 칸 구성이 문서 권한에 없습니다.",
        "no_candidates": "결재 칸을 처리할 사람이 없습니다(역할 보유자 0명).",
        "no_approval": "결재 없는 양식입니다.",  # P15 slots none
    }

    def __init__(self, reason, type_code=None):
        super().__init__(
            self.MESSAGES.get(reason, self.message),
            [{"path": "", "code": reason, "reason": reason, "type_code": type_code}],
        )


@dataclass(frozen=True)
class FormRole:
    owners: frozenset
    slots: tuple
    labels: dict
    writers: frozenset = frozenset()  # 작성 권한자(D-198·D-201) — 작성·상신, 결재 후보 아님


@dataclass
class RoleConfig:
    """쓸 때 만든 역할(그 순간의 활성 직원 기준 — 리뷰 A1, ROLE-C04)."""

    leaders: frozenset = frozenset()
    forms: dict = field(default_factory=dict)  # type_code → FormRole
    warnings: list = field(default_factory=list)  # [{code, type_code?, staff_code?, message}]
    people: dict = field(default_factory=dict)  # 활성 staff_id → {id, staff_code, name}
    version: int = 0
    empty: bool = True  # 문서 권한에 사람이 0명(비활성 포함) — setup 경고(R38)


_scoped = contextvars.ContextVar("haccp_roles_scope", default=None)


@contextmanager
def scope():
    """한 작업(상신·목록·묶음 화면) 안에서는 역할을 한 번만 만든다(SQL 2개).

    역할은 쓸 때마다 그 순간의 DB로 만든다(R36). 한 작업 안에서 여러 번 물어도
    같은 결과를 쓰고 질의를 한 번만 하도록 묶는다. 바깥 scope가 있으면 그것을 쓴다.
    """
    if _scoped.get() is not None:
        yield
        return
    token = _scoped.set([])  # 처음 load() 때 채운다(쓰지 않으면 읽지 않음)
    try:
        yield
    finally:
        _scoped.reset(token)


def load():
    """지금의 역할(DB). scope 안에서는 한 번."""
    held = _scoped.get()
    if held:
        return held[0]
    with step("ROLE-CFG-01", "ROLE", "문서 권한 읽기(adm.store.role_rows)"):
        rows = adm_store.role_rows()
    config = _resolve(rows)
    if held is not None:
        held.append(config)
    return config


# ---------------------------------------------------------------- 파일 형식 검사 (가져오기 — R41)


def validate_file_data(data):
    """R-E1 형식 검사(``import_roles``만 씀). 반환: 문제 목록(빈 목록 = 정상)."""
    if not isinstance(data, dict):
        return ["최상위는 JSON 객체여야 합니다."]
    problems = []
    if data.get("version") != 1:
        problems.append("version은 1이어야 합니다.")
    for key in sorted(set(data) - {"version", "haccp_leaders", "forms"}):
        problems.append(f"알 수 없는 키: {key}")
    leaders = data.get("haccp_leaders")
    if not _code_list(leaders):
        problems.append("haccp_leaders는 직원 코드 문자열 목록(중복 없음)이어야 합니다.")
    forms = data.get("forms")
    if not isinstance(forms, dict):
        problems.append("forms는 양식 유형 → 설정 객체여야 합니다.")
        return problems
    for type_code, form in forms.items():
        where = f"forms.{type_code}"
        if not isinstance(form, dict):
            problems.append(f"{where}는 객체여야 합니다.")
            continue
        for key in sorted(set(form) - {"owners", "writers", "slots", "labels"}):
            problems.append(f"{where}: 알 수 없는 키 {key}")
        if not _code_list(form.get("owners")):
            problems.append(f"{where}.owners는 직원 코드 문자열 목록(중복 없음)이어야 합니다.")
        if "writers" in form and not _code_list(form["writers"]):
            problems.append(f"{where}.writers는 직원 코드 문자열 목록(중복 없음)이어야 합니다.")
        if form.get("slots") not in SLOT_CONFIGS:
            problems.append(f"{where}.slots는 owner·owner_leader·leader·none 중 하나여야 합니다.")
        labels = form.get("labels", {})
        if not isinstance(labels, dict) or set(labels) - set(ROLE_NAMES):
            problems.append(f"{where}.labels는 owner·leader 키만 가질 수 있습니다.")
        else:
            for role, label in labels.items():
                if not isinstance(label, str) or not 1 <= len(label.strip()) <= LABEL_MAX:
                    problems.append(f"{where}.labels.{role}는 1~{LABEL_MAX}자 글자여야 합니다.")
    return problems


def _code_list(value):
    return (
        isinstance(value, list)
        and all(isinstance(v, str) and v.strip() for v in value)
        and len(set(value)) == len(value)
    )


def _resolve(rows):
    """ROLE-CFG-04·05: 비활성 빼기(R-W2), 칸 후보 검사(R-W5)."""
    config = RoleConfig(version=rows["version"])
    with step("ROLE-CFG-04", "ROLE", "비활성 빼기") as s:

        def ids(people, where):
            out = set()
            for p in people:
                config.empty = False
                if not p["is_active"]:
                    config.warnings.append(
                        {
                            "code": "R-W2",
                            "staff_code": p["staff_code"],
                            "where": where,
                            "message": (
                                f"비활성 직원 {p['name']}({p['staff_code']}, {where})"
                                " — 역할에서 뺐습니다."
                            ),
                        }
                    )
                    continue
                out.add(p["id"])
                config.people[p["id"]] = {
                    "id": p["id"],
                    "staff_code": p["staff_code"],
                    "name": p["name"],
                }
            return frozenset(out)

        config.leaders = ids(rows["leaders"], "haccp_leaders")
        for type_code, form in rows["forms"].items():
            config.forms[type_code] = FormRole(
                owners=ids(form["owners"], f"forms.{type_code}.owners"),
                slots=SLOT_CONFIGS[form["slots"]],
                labels={**DEFAULT_LABELS, **form["labels"]},
                writers=ids(form["writers"], f"forms.{type_code}.writers"),
            )
        s.note(f"경고 {len(config.warnings)}건")
    with step("ROLE-CFG-05", "ROLE", "양식별 칸 후보 검사"):
        for type_code, form in config.forms.items():
            for role in form.slots:
                if not _holders(config, form, role):
                    config.warnings.append(
                        {
                            "code": "R-W5",
                            "type_code": type_code,
                            "message": (
                                f"{type_code}: {DEFAULT_LABELS[role]} 칸을 처리할 사람이"
                                " 없습니다 — 상신할 수 없습니다."
                            ),
                        }
                    )
    return config


def _holders(config, form, role):
    return form.owners if role == "owner" else config.leaders


def _is_owner(config, staff_id, type_code):
    form = config.forms.get(type_code)
    return staff_id is not None and form is not None and staff_id in form.owners


def _is_leader(config, staff_id):
    return staff_id is not None and staff_id in config.leaders


def _is_writer(config, staff_id, type_code):
    form = config.forms.get(type_code)
    return staff_id is not None and form is not None and staff_id in form.writers


def _submit_role(config, staff_id, type_code):
    """ROLE-R01이 통과하는 역할 이름(trace 기록용) — 없으면 None.

    여럿이면 팀장 > 담당자 > 작성 권한자.
    """
    if _is_leader(config, staff_id):
        return "leader"
    if _is_owner(config, staff_id, type_code):
        return "owner"
    if _is_writer(config, staff_id, type_code):
        return "writer"
    return None


# ---------------------------------------------------------------- 조회


def leaders():
    return load().leaders


def owners(type_code):
    form = load().forms.get(type_code)
    return form.owners if form else frozenset()


def is_leader(staff_id):
    return _is_leader(load(), staff_id)


def is_owner(staff_id, type_code):
    return _is_owner(load(), staff_id, type_code)


def writers(type_code):
    form = load().forms.get(type_code)
    return form.writers if form else frozenset()


def is_writer(staff_id, type_code):
    return _is_writer(load(), staff_id, type_code)


def can_submit(staff_id, type_code):
    """ROLE-R01(r11 D-198): 담당자·작성 권한자·HACCP팀장."""
    return _submit_role(load(), staff_id, type_code) is not None


def require_submitter(staff_id, type_code):
    """ROLE-R01: 담당자·작성 권한자·팀장. 반환: 통과한 역할 이름."""
    config = load()
    role = _submit_role(config, staff_id, type_code)
    if role is None:
        raise RoleRequired(RoleRequired.SUBMIT, RoleRequired.SUBMIT_MESSAGE)
    return role


def forms_of(staff_id):
    return sorted(t for t, form in load().forms.items() if staff_id in form.owners)


def require_owner_or_leader(staff_id, type_code):
    """ROLE-R04(정정 시작): 담당자 또는 팀장.

    상신(R01)은 작성 권한자도 되므로 require_submitter(r11 D-198).
    """
    config = load()
    if not (_is_owner(config, staff_id, type_code) or _is_leader(config, staff_id)):
        raise RoleRequired()


WRITE_REQUIRED = ("owner", "writer", "leader", "inspector")  # ROLE-R07(r13 D-201)
WRITE_MESSAGE = "이 양식의 담당자·작성 권한자·HACCP팀장이나 지정된 점검자만 작성할 수 있습니다."
INSPECTOR_MESSAGE = "점검자는 이 양식의 담당자나 HACCP팀장만 지정할 수 있습니다."


def write_role(staff_id, type_code, inspector_id=None):
    """ROLE-R07(r13): 작성이 통과하는 역할 이름(trace 기록용) — 없으면 None.

    문서 권한이 비어도 예외 없음(ADM-R38 Q-5 a). 여럿이면 팀장 > 담당자 > 작성 권한자 > 점검자.
    inspector_id = 그 문서 ``info.inspector``(새 문서는 None).
    """
    if staff_id is None:
        return None
    config = load()
    role = _submit_role(config, staff_id, type_code)
    if role is not None:
        return role
    if inspector_id is not None and inspector_id == staff_id:
        return "inspector"
    return None


def can_write(staff_id, type_code, inspector_id=None):
    """ROLE-R07 여부(문서 상세 permissions.write·묶음 can_write)."""
    return write_role(staff_id, type_code, inspector_id) is not None


def can_assign_inspector(staff_id, type_code):
    """ROLE-R08 여부(화면 권한 값)."""
    config = load()
    if staff_id is None:
        return False
    return _is_owner(config, staff_id, type_code) or _is_leader(config, staff_id)


def require_inspector_setter(staff_id, type_code):
    """ROLE-R08(r13): 점검자 지정·바꾸기 — 담당자 또는 팀장."""
    config = load()
    if not (_is_owner(config, staff_id, type_code) or _is_leader(config, staff_id)):
        raise RoleRequired(message=INSPECTOR_MESSAGE)


def approval_line(type_code, config=None):
    """ROLE-F01: 양식의 결재선. 반환 {ok, slots:[{slot_no, role, label, candidate_ids}], reason}.

    reason ∈ no_config · no_candidates · no_approval(P15)
    (ok면 None). 후보는 id 순(지금 활성 직원).
    """
    if config is None:
        config = load()
    form = config.forms.get(type_code)
    if form is None:
        return {"ok": False, "slots": [], "reason": "no_config"}
    if not form.slots:
        return {"ok": False, "slots": [], "reason": "no_approval"}  # P15 slots none
    slots = []
    for number, role in enumerate(form.slots, start=1):
        candidates = sorted(_holders(config, form, role))
        if not candidates:
            return {"ok": False, "slots": [], "reason": "no_candidates"}
        slots.append(
            {
                "slot_no": number,
                "role": role,
                "label": form.labels[role],
                "candidate_ids": candidates,
            }
        )
    return {"ok": True, "slots": slots, "reason": None}


def require_approval_line(type_code):
    line = approval_line(type_code)
    if not line["ok"]:
        raise NoApprovalLine(line["reason"], type_code)
    return line["slots"]


def setup(config, active_forms):
    """R38 빈 권한 경고: {empty: 사람 0명, leaders: 활성 팀장 수, blocked_forms: 상신 불가 양식}.

    blocked_forms = 결재 칸이 있는 활성 양식 중 칸 후보 0명(no_candidates)·행 없음(no_config).
    오류(403·409)와 따로 — 문서 권한 화면 위 경고·시스템 검사(R38)용.
    """
    blocked = []
    for type_code, _name in active_forms:
        line = approval_line(type_code, config)
        if line["reason"] in ("no_candidates", "no_config"):
            blocked.append(type_code)
    return {"empty": config.empty, "leaders": len(config.leaders), "blocked_forms": blocked}


def summary(active_forms, staff_id=None):
    """ROLE-A01 응답. active_forms = [(type_code, name)] — 활성 양식 순서(호출자가 DOC에서 읽음)."""
    config = load()
    people = config.people

    def person(sid):
        return people.get(sid, {"id": sid, "staff_code": None, "name": None})

    forms = []
    for type_code, name in active_forms:
        form = config.forms.get(type_code)
        line = approval_line(type_code, config)
        forms.append(
            {
                "type_code": type_code,
                "name": name,
                "slots": [
                    {"slot_no": n, "role": role, "label": form.labels[role]}
                    for n, role in enumerate(form.slots, start=1)
                ]
                if form
                else [],
                "owners": [person(sid) for sid in sorted(form.owners)] if form else [],
                "writers": [person(sid) for sid in sorted(form.writers)] if form else [],
                "submittable": line["ok"],
                "block_reason": line["reason"],
            }
        )
    warnings = list(config.warnings)
    for type_code, _name in active_forms:
        if type_code not in config.forms:
            warnings.append(
                {
                    "code": "R-W4",
                    "type_code": type_code,
                    "message": f"{type_code}: 문서 권한에 없습니다 — 상신할 수 없습니다.",
                }
            )
    # P16: 비활성 양식의 문서 권한 행은 보존이 정상이라 R-W3(활성 양식 아님)은 없앰
    result = {
        "leaders": [person(sid) for sid in sorted(config.leaders)],
        "forms": forms,
        "warnings": warnings,
        "version": config.version,
        "setup": setup(config, active_forms),
        "reload": "immediate",  # P16: 저장 즉시 다음 요청부터(R36)
    }
    if staff_id is not None:
        result["me"] = {
            "staff_id": staff_id,
            "is_leader": _is_leader(config, staff_id),
            "owner_of": sorted(t for t, f in config.forms.items() if staff_id in f.owners),
            "writer_of": sorted(t for t, f in config.forms.items() if staff_id in f.writers),
        }
    return result
