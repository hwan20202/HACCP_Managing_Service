"""생산 기준정보(PLG) 서비스 — 공정 목록·공정 템플릿·변경 이력(p15-s2-spec.md PLG-F08·F09·F11).

규칙: PLG-R12(누구나·변경마다 이력 1행) · R13(이름 중복·비슷한 이름) · R14(기본 제공 잠금) ·
R15(삭제는 쓰인 적 없을 때만) · R16(템플릿 구성). 쓰기는 모두 트랜잭션 안에서 부른다(API가 연다).

계층: DOC 공개 함수(`count_rows_with`)·staff만 부른다.
수불(apps.inventory)·REQ sources는 import하지 않는다.
"""

import math
import re

from django.db import connection, transaction
from django.db.models import Count, F, Max
from django.utils import timezone

from apps.core.trace import step
from apps.documents import services as doc
from apps.staff import services as staff_services

from . import errors
from .models import (
    DUR_UNITS,
    MODES,
    MasterChangeLog,
    Process,
    ProcessTemplate,
    ProcessTemplateStep,
)

PROD_LOG = "PROD-LOG"
STEPS_SECTION = "steps"
NAME_MAX = 40
DESC_MAX = 300
DURATION_MAX = {"분": 100000, "시간": 10000, "일": 1000}  # B1(S4a 리뷰): 무한대·터무니없는 값 막기
TEMPLATE_STEPS_MAX = 30  # 생산일지 steps max_rows와 같음
BUILTIN_ORDER = ["CCP-1P", "CCP-2B", "CCP-3P", "INNER", "OUTER"]
CCP_KINDS = ("CCP-1P", "CCP-2B", "CCP-3P")
PROCESS_KEYS = {"name", "mode", "description", "std_duration"}
BUILTIN_KEYS = {"name", "description", "std_duration"}  # PLG-R14
# 템플릿 단계에서 덮어쓸 수 있는 값(기능별) — S1 PLG-SC-05 "덮어쓸 값"
OVERRIDE_KEYS = {
    "common": {"name", "desc", "duration"},
    "GEN": {"mode"},
    "INNER": {"spec", "qty_unit"},
    "OUTER": {"material"},
}
OVERRIDE_TEXT_MAX = {
    "name": NAME_MAX,
    "desc": DESC_MAX,
    "spec": 40,
    "qty_unit": 10,
    "material": 100,
}
_SIMILAR_STRIP = re.compile(r"[\s()\[\]{}（）]")


def _require_transaction():
    if not connection.in_atomic_block:
        raise errors.TransactionRequired()


def _detail(path, code, message):
    return {"path": path, "code": code, "message": message}


# ---------------------------------------------------------------- 이름 (PLG-R13)


def clean_name(value, path="name"):
    """공백 정리한 이름. 1~40자, 공백만 불가."""
    if not isinstance(value, str) or not " ".join(value.split()):
        raise errors.ValidationFailed(details=[_detail(path, "required", "이름을 입력하세요.")])
    name = " ".join(value.split())
    if len(name) > NAME_MAX:
        raise errors.ValidationFailed(
            details=[_detail(path, "too_long", f"이름은 {NAME_MAX}자 이하입니다.")]
        )
    return name


def name_key(name):
    """중복 판정 키(공백 정리·대소문자 무시) — DB `name_key` 부분 유니크와 같은 값."""
    return " ".join(name.split()).casefold()


def similar_key(name):
    """비슷한 이름 키(공백·괄호 제거) — 경고만(PLG-R13)."""
    return _SIMILAR_STRIP.sub("", name).casefold()


def _check_name(model, name, exclude_pk, confirm_similar):
    """같은 이름 409 NAME_TAKEN(기존 id), 비슷한 이름 409 SIMILAR_NAME(확인 없을 때). SQL 1."""
    key = name_key(name)
    rows = model.objects.filter(is_active=True).exclude(pk=exclude_pk).values_list("pk", "name")
    similar = []
    for pk, other in rows:
        if name_key(other) == key:
            raise errors.NameTaken(
                details=[{"path": "name", "code": "taken", "id": pk, "name": other}]
            )
        if similar_key(other) == similar_key(name):
            similar.append({"id": pk, "name": other})
    if similar and not confirm_similar:
        raise errors.SimilarName(
            details=[{"path": "name", "code": "similar", **item} for item in similar]
        )


def _flag(value, path):
    if value is None:
        return False
    if not isinstance(value, bool):
        raise errors.ValidationFailed(details=[_detail(path, "invalid", "true/false여야 합니다.")])
    return value


# ---------------------------------------------------------------- 공통 값 검사


def _duration(value, path):
    """표준 소요기간 {value, unit} 또는 None → (value, unit)."""
    if value is None:
        return None, None
    if not isinstance(value, dict) or set(value) != {"value", "unit"}:
        raise errors.ValidationFailed(
            details=[_detail(path, "invalid", "소요기간은 {value, unit} 또는 null입니다.")]
        )
    number, unit = value["value"], value["unit"]
    if unit not in DUR_UNITS:
        raise errors.ValidationFailed(
            details=[_detail(f"{path}.unit", "invalid", "분·시간·일 중 하나입니다.")]
        )
    if (
        isinstance(number, bool)
        or not isinstance(number, (int, float))
        or not math.isfinite(number)
        or not 0 < number <= DURATION_MAX[unit]
    ):
        raise errors.ValidationFailed(
            details=[
                _detail(
                    f"{path}.value",
                    "invalid",
                    f"0보다 크고 {DURATION_MAX[unit]}{unit} 이하인 수입니다.",
                )
            ]
        )
    return number, unit


def _text(value, path, max_len, required=False):
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise errors.ValidationFailed(details=[_detail(path, "required", "값을 입력하세요.")])
        return None
    if not isinstance(value, str):
        raise errors.ValidationFailed(details=[_detail(path, "invalid", "문자열이어야 합니다.")])
    text = value.strip()
    if len(text) > max_len:
        raise errors.ValidationFailed(
            details=[_detail(path, "too_long", f"{max_len}자 이하입니다.")]
        )
    return text


def _mode(value, path="mode"):
    if value not in MODES:
        raise errors.ValidationFailed(
            details=[_detail(path, "invalid", "적합/부적합·온도·시간·수량 중 하나입니다.")]
        )
    return value


def _check_version(expected_version):
    if (
        isinstance(expected_version, bool)
        or not isinstance(expected_version, int)
        or (expected_version < 1)
    ):
        raise errors.ValidationFailed(
            details=[_detail("expected_version", "invalid", "1 이상의 정수")]
        )


def _log(actor_id, target, target_id, action, before, after, document_id=None):
    MasterChangeLog.objects.create(
        target=target,
        target_id=target_id,
        action=action,
        before_json=before,
        after_json=after,
        actor_id=actor_id,
        document_id=document_id,
        at=timezone.now(),
    )


# ---------------------------------------------------------------- 공정 (PLG-F08)


def _process_state(p):
    """이력·응답용 공정 값."""
    return {
        "name": p.name,
        "kind": p.kind,
        "mode": p.mode,
        "description": p.description,
        "std_duration": None
        if p.std_duration_value is None
        else {"value": p.std_duration_value, "unit": p.std_duration_unit},
        "is_active": p.is_active,
    }


def _process_dict(p, template_count=0, last_used_at=None):
    return {
        "process_id": p.process_id,
        **_process_state(p),
        "is_builtin": p.is_builtin,
        "version": p.version,
        "template_count": template_count,
        "last_used_at": last_used_at.isoformat() if last_used_at else None,
        "updated_at": p.updated_at.isoformat(),
        "updated_by": p.updated_by_id,
    }


def _process_usage(process_ids=None):
    """{process_id: (쓰는 템플릿 수, 그 템플릿들의 최근 사용)} — SQL 1."""
    rows = ProcessTemplateStep.objects.all()
    if process_ids is not None:
        rows = rows.filter(process_id__in=process_ids)
    return {
        r["process_id"]: (r["n"], r["last"])
        for r in rows.values("process_id").annotate(
            n=Count("template_id", distinct=True), last=Max("template__last_used_at")
        )
    }


def _builtin_rank(p):
    return (0, BUILTIN_ORDER.index(p.kind), "") if p.is_builtin else (1, 0, p.name_key)


def list_processes(query="", kind="all", status="active"):
    """PRC-LST: 이름 검색·기능(all|builtin|general)·상태(active|inactive|all). SQL 2."""
    with step("PRC-LST-01", "PLG", "공정 목록·쓰는 템플릿 수"):
        if kind not in ("all", "builtin", "general") or status not in ("active", "inactive", "all"):
            raise errors.ValidationFailed(
                details=[_detail("filter", "invalid", "조회 조건을 확인하세요.")]
            )
        rows = Process.objects.all()
        if query and query.strip():
            rows = rows.filter(name_key__contains=name_key(query))
        if kind != "all":
            rows = rows.filter(is_builtin=(kind == "builtin"))
        if status != "all":
            rows = rows.filter(is_active=(status == "active"))
        items = sorted(rows, key=_builtin_rank)
        usage = _process_usage()
        return {"items": [_process_dict(p, *usage.get(p.process_id, (0, None))) for p in items]}


def get_process(process_id):
    p = Process.objects.filter(pk=process_id).first()
    if p is None:
        raise errors.ProcessNotFound()
    return _process_dict(p, *_process_usage([process_id]).get(process_id, (0, None)))


def create_process(actor_id, data, *, action="create", document_id=None):
    """PRC-NEW: 일반 공정만 추가(기본 제공은 시드). 이름 R13 · 입력 방식 필수 → 이력."""
    with step("PRC-NEW-01", "PLG", "입력 확인"):
        _require_transaction()
        unknown = sorted(set(data) - PROCESS_KEYS - {"confirm_similar"})
        if unknown:
            raise errors.ValidationFailed(
                details=[_detail(k, "unknown_key", "허용되지 않은 키입니다.") for k in unknown]
            )
        name = clean_name(data.get("name"))
        mode = _mode(data.get("mode"))
        description = _text(data.get("description"), "description", DESC_MAX)
        dur_value, dur_unit = _duration(data.get("std_duration"), "std_duration")
        confirm = _flag(data.get("confirm_similar"), "confirm_similar")
    with step("PRC-NEW-02", "PLG", "이름 중복·비슷한 이름(R13)"):
        _check_name(Process, name, None, confirm)
    with step("PRC-NEW-03", "PLG", "저장·이력"):
        now = timezone.now()
        p = Process.objects.create(
            name=name,
            name_key=name_key(name),
            kind="GEN",
            mode=mode,
            is_builtin=False,
            description=description,
            std_duration_value=dur_value,
            std_duration_unit=dur_unit,
            is_active=True,
            created_by_id=actor_id,
            created_at=now,
            updated_by_id=actor_id,
            updated_at=now,
        )
        _log(actor_id, "process", p.process_id, action, None, _process_state(p), document_id)
        return _process_dict(p)


def _locked_process(process_id, expected_version):
    _check_version(expected_version)
    p = Process.objects.filter(pk=process_id).first()
    if p is None:
        raise errors.ProcessNotFound()
    if p.version != expected_version:
        raise errors.VersionConflict()
    return p


def _save_process(p, actor_id, expected_version, **fields):
    """조건부 UPDATE(version) — 0행이면 409 VERSION_CONFLICT."""
    now = timezone.now()
    changed = Process.objects.filter(pk=p.pk, version=expected_version).update(
        **fields, updated_by_id=actor_id, updated_at=now, version=F("version") + 1
    )
    if changed != 1:
        raise errors.VersionConflict()
    p.refresh_from_db()
    return p


def update_process(actor_id, process_id, data, expected_version):
    """PRC-UPD: 기본 제공은 이름·설명·소요기간만(R14), 입력 방식 바꾸면 confirm_mode 필요."""
    with step("PRC-UPD-01", "PLG", "공정·버전 확인"):
        _require_transaction()
        p = _locked_process(process_id, expected_version)
        allowed = BUILTIN_KEYS if p.is_builtin else PROCESS_KEYS
        flags = {"confirm_similar", "confirm_mode"}
        unknown = sorted(set(data) - PROCESS_KEYS - flags)
        if unknown:
            raise errors.ValidationFailed(
                details=[_detail(k, "unknown_key", "허용되지 않은 키입니다.") for k in unknown]
            )
        locked = sorted(set(data) - allowed - flags)
        if locked:
            raise errors.BuiltinLocked(
                details=[
                    _detail(k, "builtin_locked", "기본 제공 공정은 바꿀 수 없습니다.")
                    for k in locked
                ]
            )
        if not set(data) - flags:
            raise errors.ValidationFailed(
                details=[_detail("", "no_changes", "바꿀 내용이 없습니다.")]
            )
    with step("PRC-UPD-02", "PLG", "값 확인·이름(R13)"):
        fields = {}
        if "name" in data:
            name = clean_name(data["name"])
            if name != p.name:
                if p.is_active:
                    _check_name(
                        Process, name, p.pk, _flag(data.get("confirm_similar"), "confirm_similar")
                    )
                fields.update(name=name, name_key=name_key(name))
        if "description" in data:
            fields["description"] = _text(data["description"], "description", DESC_MAX)
        if "std_duration" in data:
            fields["std_duration_value"], fields["std_duration_unit"] = _duration(
                data["std_duration"], "std_duration"
            )
        template_count = _process_usage([p.pk]).get(p.pk, (0, None))[0]
    with step("PRC-UPD-03", "PLG", "입력 방식 변경 확인"):
        if "mode" in data and _mode(data["mode"]) != p.mode:
            if not _flag(data.get("confirm_mode"), "confirm_mode"):
                raise errors.ConfirmRequired(
                    details=[{"path": "mode", "code": "confirm", "template_count": template_count}]
                )
            fields["mode"] = data["mode"]
    with step("PRC-UPD-04", "PLG", "저장·이력"):
        before = _process_state(p)
        fields = {k: v for k, v in fields.items() if getattr(p, k) != v}  # B3: 같은 값은 저장 안 함
        if fields:
            p = _save_process(p, actor_id, expected_version, **fields)
            _log(actor_id, "process", p.pk, "update", before, _process_state(p))
        return _process_dict(p, *_process_usage([p.pk]).get(p.pk, (0, None)))


def set_process_active(actor_id, process_id, active, expected_version):
    """PRC-ACT: 사용 중지·다시 사용. 기본 제공 409, 다시 쓸 때 같은 이름 있으면 409."""
    with step("PRC-ACT-01", "PLG", "상태 바꾸기·이력"):
        _require_transaction()
        if not isinstance(active, bool):
            raise errors.ValidationFailed(details=[_detail("active", "required", "true/false")])
        p = _locked_process(process_id, expected_version)
        if p.is_builtin:
            raise errors.BuiltinLocked()
        if p.is_active == active:
            return get_process(p.pk)
        if active:
            _check_name(Process, p.name, p.pk, True)
        before = _process_state(p)
        p = _save_process(p, actor_id, expected_version, is_active=active)
        _log(
            actor_id,
            "process",
            p.pk,
            "reactivate" if active else "deactivate",
            before,
            _process_state(p),
        )
        return get_process(p.pk)


def process_in_use(process_id):
    """PLG-R15: 템플릿 단계 또는 생산일지 행에 쓰였나. SQL 2."""
    if ProcessTemplateStep.objects.filter(process_id=process_id).exists():
        return True
    return doc.count_rows_with(PROD_LOG, STEPS_SECTION, "process_id", process_id) > 0


def delete_process(actor_id, process_id, expected_version):
    """PRC-DEL: 한 번도 안 쓴 일반 공정만 물리 삭제 + 이력."""
    with step("PRC-DEL-01", "PLG", "기본 제공·사용 이력(R15)"):
        _require_transaction()
        p = _locked_process(process_id, expected_version)
        if p.is_builtin:
            raise errors.BuiltinLocked()
        if process_in_use(p.pk):
            raise errors.InUse()
    with step("PRC-DEL-02", "PLG", "삭제·이력"):
        before = _process_state(p)
        if Process.objects.filter(pk=p.pk, version=expected_version).delete()[0] != 1:
            raise errors.VersionConflict()
        _log(actor_id, "process", process_id, "delete", before, None)
        return {"process_id": process_id, "deleted": True}


# ---------------------------------------------------------------- 템플릿 (PLG-F09)


def _overrides(raw, process, path):
    """템플릿 단계 오류는 모두 PLG_TEMPLATE_INVALID(값 형식 오류 포함 — S4a 리뷰 B1 회귀)."""
    try:
        return _overrides_values(raw, process, path)
    except errors.ValidationFailed as error:
        raise errors.TemplateInvalid(details=error.details) from error


def _overrides_values(raw, process, path):
    """기능별 덮어쓸 값 검사(OVERRIDE_KEYS) → 정리된 dict."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise errors.TemplateInvalid(details=[_detail(path, "invalid", "객체여야 합니다.")])
    allowed = OVERRIDE_KEYS["common"] | OVERRIDE_KEYS.get(process.kind, set())
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise errors.TemplateInvalid(
            details=[
                _detail(f"{path}.{k}", "not_allowed", "이 기능에서는 덮어쓸 수 없습니다.")
                for k in unknown
            ]
        )
    out = {}
    for key, value in raw.items():
        where = f"{path}.{key}"
        if key == "duration":
            if value is None:
                out[key] = None  # 소요기간 기록 끔
            else:
                number, unit = _duration(value, where)
                out[key] = {"value": number, "unit": unit}
        elif key == "mode":
            out[key] = _mode(value, where)
        elif key == "name":
            out[key] = clean_name(value, where)
        else:
            text = _text(value, where, OVERRIDE_TEXT_MAX[key])
            if text is not None:
                out[key] = text
    return out


def _clean_steps(raw, existing_ids=()):
    """PLG-R16: 1~30개, 공정 목록 공정만(새로 넣는 공정은 사용 중), 같은 공정 두 번 불가. SQL 1."""
    if not isinstance(raw, list) or not raw:
        raise errors.TemplateInvalid(
            details=[_detail("steps", "required", "공정을 1개 이상 넣으세요.")]
        )
    if len(raw) > TEMPLATE_STEPS_MAX:
        raise errors.TemplateInvalid(
            details=[_detail("steps", "too_many", f"공정은 {TEMPLATE_STEPS_MAX}개까지입니다.")]
        )
    ids = []
    for i, item in enumerate(raw):
        pid = item.get("process_id") if isinstance(item, dict) else None
        if isinstance(pid, bool) or not isinstance(pid, int):
            raise errors.TemplateInvalid(
                details=[_detail(f"steps[{i}].process_id", "required", "공정 id가 필요합니다.")]
            )
        unknown = sorted(set(item) - {"process_id", "overrides"})
        if unknown:
            raise errors.TemplateInvalid(
                details=[
                    _detail(f"steps[{i}].{k}", "unknown_key", "허용되지 않은 키입니다.")
                    for k in unknown
                ]
            )
        ids.append(pid)
    processes = Process.objects.in_bulk(set(ids))
    problems = []
    seen = set()
    for i, pid in enumerate(ids):
        p = processes.get(pid)
        if p is None:
            problems.append(_detail(f"steps[{i}].process_id", "not_found", "없는 공정입니다."))
        elif not p.is_active and pid not in existing_ids:
            problems.append(
                _detail(f"steps[{i}].process_id", "inactive", "사용 중지된 공정입니다.")
            )
        if pid in seen:
            problems.append(
                _detail(f"steps[{i}].process_id", "duplicate", "같은 공정이 두 번 있습니다.")
            )
        seen.add(pid)
    if problems:
        raise errors.TemplateInvalid(details=problems)
    return [
        (pid, _overrides(raw[i].get("overrides"), processes[pid], f"steps[{i}].overrides"))
        for i, pid in enumerate(ids)
    ]


def _write_steps(template_id, steps):
    ProcessTemplateStep.objects.filter(template_id=template_id).delete()
    ProcessTemplateStep.objects.bulk_create(
        [
            ProcessTemplateStep(template_id=template_id, process_id=pid, seq=n, overrides_json=ov)
            for n, (pid, ov) in enumerate(steps, 1)
        ]
    )


def _template_state(t, steps=None):
    if steps is None:
        steps = [
            (s.process_id, s.overrides_json)
            for s in ProcessTemplateStep.objects.filter(template_id=t.pk).order_by("seq")
        ]
    return {
        "name": t.name,
        "is_active": t.is_active,
        "steps": [{"process_id": pid, "overrides": ov} for pid, ov in steps],
    }


def _resolve(process, overrides):
    """템플릿 공정 = 공정 기본값 + 덮어쓴 값(PLG-R17 — 불러올 때 이 값을 복사)."""
    duration = (
        None
        if process.std_duration_value is None
        else {"value": process.std_duration_value, "unit": process.std_duration_unit}
    )
    return {
        "name": overrides.get("name", process.name),
        "desc": overrides.get("desc", process.description),
        "mode": overrides.get("mode", process.mode),
        "duration": overrides["duration"] if "duration" in overrides else duration,
        "spec": overrides.get("spec"),
        "qty_unit": overrides.get("qty_unit"),
        "material": overrides.get("material"),
    }


def _template_summary(t, step_count, ccp, creator_names):
    return {
        "process_template_id": t.pk,
        "name": t.name,
        "is_active": t.is_active,
        "used_count": t.used_count,
        "last_used_at": t.last_used_at.isoformat() if t.last_used_at else None,
        "step_count": step_count,
        "ccp_kinds": ccp,
        "created_by": {"id": t.created_by_id, "name": creator_names.get(t.created_by_id)},
        "version": t.version,
        "updated_at": t.updated_at.isoformat(),
    }


def list_templates(query="", status="active"):
    """TPL-LST: 이름순, 공정 수·CCP 기능·만든 사람·최근 사용. SQL 3."""
    with step("TPL-LST-01", "PLG", "템플릿 목록"):
        if status not in ("active", "inactive", "all"):
            raise errors.ValidationFailed(
                details=[_detail("status", "invalid", "조회 조건을 확인하세요.")]
            )
        rows = ProcessTemplate.objects.all()
        if query and query.strip():
            rows = rows.filter(name_key__contains=name_key(query))
        if status != "all":
            rows = rows.filter(is_active=(status == "active"))
        templates = list(rows.order_by("name_key", "pk"))
        counts, ccp = {}, {}
        for tid, kind in (
            ProcessTemplateStep.objects.filter(template_id__in=[t.pk for t in templates])
            .order_by("seq")
            .values_list("template_id", "process__kind")
        ):
            counts[tid] = counts.get(tid, 0) + 1
            if kind in CCP_KINDS:
                ccp.setdefault(tid, []).append(kind)
        names = staff_services.names_of({t.created_by_id for t in templates})
        return {
            "items": [
                _template_summary(t, counts.get(t.pk, 0), ccp.get(t.pk, []), names)
                for t in templates
            ]
        }


def get_template(template_id):
    """TPL-GET: 단계(공정 정보·덮어쓴 값·적용 값). SQL 3."""
    with step("TPL-GET-01", "PLG", "템플릿·단계"):
        t = ProcessTemplate.objects.filter(pk=template_id).first()
        if t is None:
            raise errors.TemplateNotFound()
        steps = list(
            ProcessTemplateStep.objects.filter(template_id=t.pk)
            .select_related("process")
            .order_by("seq")
        )
        names = staff_services.names_of({t.created_by_id})
        out = _template_summary(
            t, len(steps), [s.process.kind for s in steps if s.process.kind in CCP_KINDS], names
        )
        out["steps"] = [
            {
                "seq": s.seq,
                "process_id": s.process_id,
                "process_name": s.process.name,
                "kind": s.process.kind,
                "process_is_active": s.process.is_active,
                "overrides": s.overrides_json,
                "resolved": _resolve(s.process, s.overrides_json),
            }
            for s in steps
        ]
        return out


def create_template(actor_id, data, action="create", document_id=None):
    """TPL-NEW: 이름 R13 · 단계 R16 → 이력."""
    with step("TPL-NEW-01", "PLG", "입력 확인·단계(R16)"):
        _require_transaction()
        unknown = sorted(set(data) - {"name", "steps", "confirm_similar"})
        if unknown:
            raise errors.ValidationFailed(
                details=[_detail(k, "unknown_key", "허용되지 않은 키입니다.") for k in unknown]
            )
        name = clean_name(data.get("name"))
        steps = _clean_steps(data.get("steps"))
    with step("TPL-NEW-02", "PLG", "이름 중복·비슷한 이름(R13)"):
        _check_name(
            ProcessTemplate, name, None, _flag(data.get("confirm_similar"), "confirm_similar")
        )
    with step("TPL-NEW-03", "PLG", "저장·이력"):
        now = timezone.now()
        t = ProcessTemplate.objects.create(
            name=name,
            name_key=name_key(name),
            is_active=True,
            created_by_id=actor_id,
            created_at=now,
            updated_by_id=actor_id,
            updated_at=now,
        )
        _write_steps(t.pk, steps)
        _log(actor_id, "template", t.pk, action, None, _template_state(t, steps), document_id)
        return get_template(t.pk)


def _locked_template(template_id, expected_version):
    _check_version(expected_version)
    t = ProcessTemplate.objects.filter(pk=template_id).first()
    if t is None:
        raise errors.TemplateNotFound()
    if t.version != expected_version:
        raise errors.VersionConflict()
    return t


def _save_template(t, actor_id, expected_version, **fields):
    changed = ProcessTemplate.objects.filter(pk=t.pk, version=expected_version).update(
        **fields, updated_by_id=actor_id, updated_at=timezone.now(), version=F("version") + 1
    )
    if changed != 1:
        raise errors.VersionConflict()
    t.refresh_from_db()
    return t


def update_template(actor_id, template_id, data, expected_version):
    """TPL-UPD: 이름·단계 바꾸기(단계는 통째로). 이미 들어 있던 공정은 중지됐어도 둘 수 있음."""
    with step("TPL-UPD-01", "PLG", "템플릿·버전 확인"):
        _require_transaction()
        t = _locked_template(template_id, expected_version)
        unknown = sorted(set(data) - {"name", "steps", "confirm_similar"})
        if unknown:
            raise errors.ValidationFailed(
                details=[_detail(k, "unknown_key", "허용되지 않은 키입니다.") for k in unknown]
            )
        if not {"name", "steps"} & set(data):
            raise errors.ValidationFailed(
                details=[_detail("", "no_changes", "바꿀 내용이 없습니다.")]
            )
        before = _template_state(t)
    with step("TPL-UPD-02", "PLG", "단계(R16)"):
        steps = None
        if "steps" in data:
            existing = {s["process_id"] for s in before["steps"]}
            steps = _clean_steps(data["steps"], existing)
    with step("TPL-UPD-03", "PLG", "이름(R13)"):
        fields = {}
        if "name" in data:
            name = clean_name(data["name"])
            if name != t.name:
                if t.is_active:
                    _check_name(
                        ProcessTemplate,
                        name,
                        t.pk,
                        _flag(data.get("confirm_similar"), "confirm_similar"),
                    )
                fields.update(name=name, name_key=name_key(name))
    with step("TPL-UPD-04", "PLG", "저장·이력") as s:
        same_steps = (
            steps is None
            or [{"process_id": pid, "overrides": ov} for pid, ov in steps] == before["steps"]
        )
        if not fields and same_steps:  # B3(S4a 리뷰): 바뀐 것 없으면 저장·버전·이력 없음
            s.skip("바뀐 것 없음")
            return get_template(t.pk)
        t = _save_template(t, actor_id, expected_version, **fields)
        if steps is not None:
            _write_steps(t.pk, steps)
        after = _template_state(t)
        if after != before:
            _log(actor_id, "template", t.pk, "update", before, after)
        return get_template(t.pk)


def _copy_name(name):
    """ "이름 (복사)" — 사용 중인 이름과 겹치면 "(복사 2)"…, 40자 넘으면 앞을 줄임."""
    taken = {
        name_key(n)
        for n in ProcessTemplate.objects.filter(is_active=True).values_list("name", flat=True)
    }
    for n in range(1, 100):
        suffix = " (복사)" if n == 1 else f" (복사 {n})"
        candidate = name[: NAME_MAX - len(suffix)].rstrip() + suffix
        if name_key(candidate) not in taken:
            return candidate
    raise errors.NameTaken()


def copy_template(actor_id, template_id):
    """TPL-CPY: 같은 단계로 새 템플릿(비슷한 이름 경고 없음 — 이름이 정해져 있음)."""
    with step("TPL-CPY-01", "PLG", "원본 읽기·이름"):
        _require_transaction()
        source = ProcessTemplate.objects.filter(pk=template_id).first()
        if source is None:
            raise errors.TemplateNotFound()
        state = _template_state(source)
        # B2(S4a 리뷰): 새로 만들기와 같은 규칙 — 중지된 공정이 있으면 400(빼거나 다시 사용 뒤 복제)
        _clean_steps(
            [{"process_id": s["process_id"], "overrides": s["overrides"]} for s in state["steps"]]
        )
        name = _copy_name(source.name)
    with step("TPL-CPY-02", "PLG", "저장·이력"):
        now = timezone.now()
        t = ProcessTemplate.objects.create(
            name=name,
            name_key=name_key(name),
            is_active=True,
            created_by_id=actor_id,
            created_at=now,
            updated_by_id=actor_id,
            updated_at=now,
        )
        steps = [(s["process_id"], s["overrides"]) for s in state["steps"]]
        _write_steps(t.pk, steps)
        _log(actor_id, "template", t.pk, "copy", {"from": template_id}, _template_state(t, steps))
        return get_template(t.pk)


def set_template_active(actor_id, template_id, active, expected_version):
    """TPL-ACT: 사용 중지·다시 사용(다시 쓸 때 같은 이름 있으면 409)."""
    with step("TPL-ACT-01", "PLG", "상태 바꾸기·이력"):
        _require_transaction()
        if not isinstance(active, bool):
            raise errors.ValidationFailed(details=[_detail("active", "required", "true/false")])
        t = _locked_template(template_id, expected_version)
        if t.is_active == active:
            return get_template(t.pk)
        if active:
            _check_name(ProcessTemplate, t.name, t.pk, True)
        before = _template_state(t)
        t = _save_template(t, actor_id, expected_version, is_active=active)
        _log(
            actor_id,
            "template",
            t.pk,
            "reactivate" if active else "deactivate",
            before,
            _template_state(t),
        )
        return get_template(t.pk)


def delete_template(actor_id, template_id, expected_version):
    """TPL-DEL: 한 번도 불러온 적 없는 템플릿만(R15). 단계 먼저 지움(DB FK엔 CASCADE 없음 — T21)."""
    with step("TPL-DEL-01", "PLG", "사용 이력(R15)"):
        _require_transaction()
        t = _locked_template(template_id, expected_version)
        if t.used_count > 0:
            raise errors.InUse()
    with step("TPL-DEL-02", "PLG", "삭제·이력"):
        before = _template_state(t)
        ProcessTemplateStep.objects.filter(template_id=t.pk).delete()
        if ProcessTemplate.objects.filter(pk=t.pk, version=expected_version).delete()[0] != 1:
            raise errors.VersionConflict()
        _log(actor_id, "template", template_id, "delete", before, None)
        return {"process_template_id": template_id, "deleted": True}


# ---------------------------------------------------------------- 이력 (PLG-F11)

HISTORY_MAX = 100


def history(target, target_id):
    """MST-HIS: 최근 순 100건(누가·언제·전/후·문서). SQL 2."""
    with step("MST-HIS-01", "PLG", "변경 이력"):
        if target not in ("process", "template"):
            raise errors.ValidationFailed(
                details=[_detail("target", "invalid", "process 또는 template")]
            )
        if isinstance(target_id, bool) or not isinstance(target_id, int) or target_id < 1:
            raise errors.ValidationFailed(details=[_detail("id", "invalid", "1 이상의 정수")])
        rows = list(
            MasterChangeLog.objects.filter(target=target, target_id=target_id).order_by(
                "-at", "-pk"
            )[:HISTORY_MAX]
        )
        names = staff_services.names_of({r.actor_id for r in rows})
        return {
            "items": [
                {
                    "log_id": r.pk,
                    "action": r.action,
                    "before": r.before_json,
                    "after": r.after_json,
                    "actor": {"id": r.actor_id, "name": names.get(r.actor_id)},
                    "document_id": r.document_id,
                    "at": r.at.isoformat(),
                }
                for r in rows
            ]
        }


def atomic(fn, *args, **kwargs):
    """API용: 한 트랜잭션에서 쓰기 서비스 실행."""
    with transaction.atomic():
        return fn(*args, **kwargs)
