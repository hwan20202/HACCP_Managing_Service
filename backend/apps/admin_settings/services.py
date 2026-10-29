"""관리 설정(ADM) 서비스 — 묶음 ① 품목별 CCP(F10·F11)·공통 이력(F20). p16-s2-spec 2.1·3.2·5장.

- 쓰기는 API가 연 한 트랜잭션 안: 본문 검사 → 대상 읽기 → 조건부 UPDATE(version) → 이력.
- 권한 검사 없음(D-257 Q2 b) — 현재 사용자(X-Staff-Id)는 이력의 "누가"로만 씀.
- 수불 품목은 `Item` 모델을 읽기만 한다. 배치 수는 계약 뷰 `v_doc_batch`.
"""

from django.db import connection
from django.db.models import Q
from django.utils import timezone

from apps.core.trace import step
from apps.inventory.models import Item
from apps.staff import services as staff_services

from . import errors
from .errors import detail
from .models import MODES, PROCESSES, REASON_MAX, AdminChangeLog, CcpDefault, ItemCcp

PRODUCIBLE_TYPE = "SEMI"  # ADM-R03: 수불 PRODUCIBLE_ITEM_TYPES와 같음(반제품만)
ITEM_PROCESS_TYPE = "MANUFACTURE"  # 반제품 = 제조 배치
HISTORY_MAX = 200
HISTORY_TARGETS = {"item_ccp": ("item_ccp",)}  # 묶음 ②에서 staff·roles 추가


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
    """대상 이름 — 품목 CCP는 "품목명(코드)". 지워진 품목이면 None."""
    item_ids = {r.target_id for r in rows if r.target == "item_ccp"}
    found = Item.objects.filter(pk__in=item_ids).values_list("pk", "name", "item_code")
    return {("item_ccp", pk): f"{name}({code})" for pk, name, code in found}


def history(target, target_id=None, limit=HISTORY_MAX):
    """F20(A11): 최신순, 사람 이름·대상 이름(label) 붙임. SQL 3."""
    with step("ADM-HIS-01", "ADM", "변경 이력"):
        if target not in HISTORY_TARGETS:
            raise errors.ValidationFailed(
                details=[detail("target", "invalid", "item_ccp")]  # 묶음 ②: staff·roles
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
