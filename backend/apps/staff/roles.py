"""역할(P14) — 설정 파일의 HACCP팀장·양식별 담당자·작성 권한자·결재 칸 구성. 테이블 없음.

- 작성 권한자(``writers``, DR-20 — 명세 ROLE-C08): 양식별, 작성(ROLE-R07, r13 DR-23)과
  상신·재상신(ROLE-R01). 결재 칸 후보가 아니다.
- 작성(R07) = 담당자·작성 권한자·팀장 + 그 문서 점검자(점검자 값은 DOC가 넘김 — 이 모듈은
  문서를 읽지 않는다). 점검자 지정(R08) = 담당자·팀장.

- 설정 파일은 ``HACCP_ROLES_FILE``(비우면 이 폴더의 roles.json — 가상 개발 직원만). 서버 시작 뒤
  처음 쓸 때 한 번 읽어 보관한다(파일을 바꾸면 재시작 — ROLE-C05). ``HACCP_ROLES_RELOAD``가 참이면
  호출마다 다시 읽는다(테스트용).
- 직원은 설정에 ``staff_code``로 적고 **쓸 때마다** 그 순간의 활성 ``staff.id``로 바꾼다(SQL 1개,
  ``scope()`` 안에서는 한 번). 없는 코드·비활성 직원은 역할에서 빠진 것으로 보고 경고만 남긴다
  (ROLE-C04). 직원 등록·비활성 변경은 재시작 없이 반영된다(S4 리뷰 A1).
- 이 모듈은 ``staff``와 설정 파일만 읽고 다른 단위(DOC·APR·WF·REQ)를 import하지 않는다(ROLE-NFR-01).
  흐름: dev-notes/roles/p14-s2-flows.md 3.1.
"""

import contextvars
import json
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from django.conf import settings

from apps.core.http import ApiError
from apps.core.trace import step

from .models import Staff

DEFAULT_FILE = Path(__file__).resolve().parent / "roles.json"
SLOT_CONFIGS = {"owner": ("owner",), "owner_leader": ("owner", "leader"), "leader": ("leader",)}
ROLE_NAMES = ("owner", "leader")
DEFAULT_LABELS = {"owner": "담당자", "leader": "HACCP팀장"}
LABEL_MAX = 20


class RoleConfigInvalid(ApiError):
    status = 409
    code = "ROLE_CONFIG_INVALID"
    message = "역할 설정 파일 오류로 이 작업을 할 수 없습니다."


class RoleRequired(ApiError):
    status = 403
    code = "ROLE_REQUIRED"
    message = "이 양식의 담당자나 HACCP팀장만 할 수 있습니다."
    SUBMIT = ("owner", "writer", "leader")  # ROLE-R01(r11 DR-20) — 정정 시작(R04)은 기본값
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
        "no_config": "이 양식의 결재 칸 구성이 역할 설정에 없습니다.",
        "no_candidates": "결재 칸을 처리할 사람이 없습니다(역할 보유자 0명).",
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
    writers: frozenset = frozenset()  # 작성 권한자(DR-20·23) — 작성·상신, 결재 후보 아님


@dataclass
class RoleConfig:
    """쓸 때 만든 역할(그 순간의 활성 직원 기준 — 리뷰 A1, ROLE-C04)."""

    leaders: frozenset = frozenset()
    forms: dict = field(default_factory=dict)  # type_code → FormRole
    warnings: list = field(default_factory=list)  # [{code, type_code?, staff_code?, message}]
    error: str | None = None  # 형식 오류(R-E1)면 내용
    people: dict = field(default_factory=dict)  # staff_id → {id, staff_code, name}


@dataclass(frozen=True)
class _File:
    """설정 파일 내용(보관본 — 재시작 때 반영, ROLE-C05). data는 형식 검사를 통과한 JSON."""

    data: dict | None = None
    error: str | None = None


_lock = threading.Lock()
_cache = None  # _File


def config_path():
    return Path(getattr(settings, "HACCP_ROLES_FILE", None) or DEFAULT_FILE)


def reset():
    """보관본을 지운다(테스트·관리 명령용). 다음 load()가 파일을 다시 읽는다."""
    global _cache
    with _lock:
        _cache = None


_scoped = contextvars.ContextVar("haccp_roles_scope", default=None)


@contextmanager
def scope():
    """한 작업(상신·목록·묶음 화면) 안에서는 역할을 한 번만 만든다(직원 조회 SQL 1개).

    역할은 쓸 때마다 그 순간의 활성 직원으로 만든다(리뷰 A1). 한 작업 안에서 여러 번 물어도
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


def _file():
    """설정 파일: 운영은 서버 시작 뒤 처음 한 번(보관본), HACCP_ROLES_RELOAD(테스트)면 매번."""
    global _cache
    if getattr(settings, "HACCP_ROLES_RELOAD", False):
        return _read_file()
    with _lock:
        if _cache is None:
            _cache = _read_file()
        return _cache


def load():
    """지금의 역할. 파일은 보관본, 직원 코드 → 활성 id·경고는 그때 DB로(scope 안에서는 한 번)."""
    held = _scoped.get()
    if held:
        return held[0]
    config = _resolve(_file())
    if held is not None:
        held.append(config)
    return config


# ---------------------------------------------------------------- 읽기·검사 (ROLE-CFG)


def _format_problems(data):
    """R-E1 형식 검사. 반환: 문제 목록(빈 목록 = 정상)."""
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
            problems.append(f"{where}.slots는 owner·owner_leader·leader 중 하나여야 합니다.")
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


def _read_file():
    path = config_path()
    with step("ROLE-CFG-01", "ROLE", "설정 파일 읽기") as s:
        s.note(str(path))
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as error:
            s.fail(f"읽기 실패: {error}")
            return _File(error=f"설정 파일을 읽지 못했습니다: {error}")
    with step("ROLE-CFG-02", "ROLE", "형식 검사") as s:
        problems = _format_problems(data)
        if problems:
            s.fail(f"오류 {len(problems)}건")
            return _File(error=" / ".join(problems))
    return _File(data=data)


def _resolve(file):
    """ROLE-CFG-03~05: 코드 → 지금 활성인 staff id(쓸 때마다 — 리뷰 A1), 경고, 칸 후보 검사."""
    if file.error:
        return RoleConfig(error=file.error)
    data = file.data
    codes = set(data["haccp_leaders"])
    for form in data["forms"].values():
        codes.update(form["owners"])
        codes.update(form.get("writers", []))
    with step("ROLE-CFG-03", "ROLE", "직원 코드 → id(지금 활성 여부)"):
        rows = {
            code: (sid, name, active)
            for sid, code, name, active in Staff.objects.filter(staff_code__in=codes).values_list(
                "id", "staff_code", "name", "is_active"
            )
        }
    config = RoleConfig()
    with step("ROLE-CFG-04", "ROLE", "없는 코드·비활성 빼기") as s:

        def ids(code_list, where):
            out = set()
            for code in code_list:
                row = rows.get(code)
                if row is None:
                    config.warnings.append(
                        {
                            "code": "R-W1",
                            "staff_code": code,
                            "where": where,
                            "message": f"없는 직원 코드 {code}({where}) — 무시했습니다.",
                        }
                    )
                elif not row[2]:
                    config.warnings.append(
                        {
                            "code": "R-W2",
                            "staff_code": code,
                            "where": where,
                            "message": (
                                f"비활성 직원 {row[1]}({code}, {where}) — 역할에서 뺐습니다."
                            ),
                        }
                    )
                else:
                    out.add(row[0])
                    config.people[row[0]] = {"id": row[0], "staff_code": code, "name": row[1]}
            return frozenset(out)

        config.leaders = ids(data["haccp_leaders"], "haccp_leaders")
        for type_code, form in data["forms"].items():
            labels = {**DEFAULT_LABELS, **{k: v.strip() for k, v in form.get("labels", {}).items()}}
            config.forms[type_code] = FormRole(
                owners=ids(form["owners"], f"forms.{type_code}.owners"),
                slots=SLOT_CONFIGS[form["slots"]],
                labels=labels,
                writers=ids(form.get("writers", []), f"forms.{type_code}.writers"),
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


def config_error():
    return load().error


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
    """ROLE-R01(r11 DR-20): 담당자·작성 권한자·HACCP팀장.

    설정 오류 여부는 보지 않는다(호출자가 먼저).
    """
    return _submit_role(load(), staff_id, type_code) is not None


def require_submitter(staff_id, type_code):
    """ROLE-R01: 설정 오류가 먼저(ROLE-C07), 그다음 담당자·작성 권한자·팀장.

    반환: 통과한 역할 이름.
    """
    config = load()
    if config.error:
        raise RoleConfigInvalid()
    role = _submit_role(config, staff_id, type_code)
    if role is None:
        raise RoleRequired(RoleRequired.SUBMIT, RoleRequired.SUBMIT_MESSAGE)
    return role


def forms_of(staff_id):
    return sorted(t for t, form in load().forms.items() if staff_id in form.owners)


def require_owner_or_leader(staff_id, type_code):
    """ROLE-R04(정정 시작): 설정 오류가 먼저(ROLE-C07), 그다음 담당자 또는 팀장.

    상신(R01)은 작성 권한자도 되므로 require_submitter(r11 DR-20).
    """
    config = load()
    if config.error:
        raise RoleConfigInvalid()
    if not (_is_owner(config, staff_id, type_code) or _is_leader(config, staff_id)):
        raise RoleRequired()


WRITE_REQUIRED = ("owner", "writer", "leader", "inspector")  # ROLE-R07(r13 DR-23)
WRITE_MESSAGE = "이 양식의 담당자·작성 권한자·HACCP팀장이나 지정된 점검자만 작성할 수 있습니다."
INSPECTOR_MESSAGE = "점검자는 이 양식의 담당자나 HACCP팀장만 지정할 수 있습니다."


def write_role(staff_id, type_code, inspector_id=None):
    """ROLE-R07(r13): 작성이 통과하는 역할 이름(trace 기록용) — 없으면 None.

    설정 형식 오류면 검사하지 않는다(ROLE-C07 — 현장 기록이 멈추지 않게): ``"config_invalid"``.
    여럿이면 팀장 > 담당자 > 작성 권한자 > 점검자. inspector_id = 그 문서 ``info.inspector``
    (새 문서는 None).
    """
    if staff_id is None:
        return None
    config = load()
    if config.error:
        return "config_invalid"
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
    """ROLE-R08 여부(화면 권한 값) — 설정 형식 오류면 False(서버는 409)."""
    config = load()
    if staff_id is None or config.error:
        return False
    return _is_owner(config, staff_id, type_code) or _is_leader(config, staff_id)


def require_inspector_setter(staff_id, type_code):
    """ROLE-R08(r13): 점검자 지정·바꾸기 — 설정 오류가 먼저(409), 그다음 담당자 또는 팀장."""
    config = load()
    if config.error:
        raise RoleConfigInvalid()
    if not (_is_owner(config, staff_id, type_code) or _is_leader(config, staff_id)):
        raise RoleRequired(message=INSPECTOR_MESSAGE)


def approval_line(type_code, config=None):
    """ROLE-F01: 양식의 결재선. 반환 {ok, slots:[{slot_no, role, label, candidate_ids}], reason}.

    reason ∈ config_invalid · no_config · no_candidates (ok면 None). 후보는 id 순(지금 활성 직원).
    """
    if config is None:
        config = load()
    if config.error:
        return {"ok": False, "slots": [], "reason": "config_invalid"}
    form = config.forms.get(type_code)
    if form is None:
        return {"ok": False, "slots": [], "reason": "no_config"}
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
    if line["reason"] == "config_invalid":
        raise RoleConfigInvalid()
    if not line["ok"]:
        raise NoApprovalLine(line["reason"], type_code)
    return line["slots"]


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
    known = {t for t, _ in active_forms}
    for type_code, _name in active_forms:
        if not config.error and type_code not in config.forms:
            warnings.append(
                {
                    "code": "R-W4",
                    "type_code": type_code,
                    "message": f"{type_code}: 역할 설정에 없습니다 — 상신할 수 없습니다.",
                }
            )
    for type_code in sorted(set(config.forms) - known):
        warnings.append(
            {
                "code": "R-W3",
                "type_code": type_code,
                "message": f"{type_code}: 활성 양식이 아닙니다 — 무시했습니다.",
            }
        )
    result = {
        "leaders": [person(sid) for sid in sorted(config.leaders)],
        "forms": forms,
        "warnings": warnings,
        "config_error": config.error,
        "reload": "restart",
    }
    if staff_id is not None:
        result["me"] = {
            "staff_id": staff_id,
            "is_leader": _is_leader(config, staff_id),
            "owner_of": sorted(t for t, f in config.forms.items() if staff_id in f.owners),
            "writer_of": sorted(t for t, f in config.forms.items() if staff_id in f.writers),
        }
    return result
