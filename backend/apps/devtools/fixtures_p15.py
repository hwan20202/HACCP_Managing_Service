"""P15 S5b 개발 콘솔 프리셋 사전 조건·연동 오류 스위치(p15-s5-ui.md, D-249 Q3 a).

개발 설정에서만(urls가 DEBUG + HACCP_DEV_CONSOLE일 때만 등록).
운영 코드는 이 모듈을 import하지 않는다.

POST /api/dev/fixtures/prodlog {
  scenario: started|used|partial|cancelled|nobom   (prodlog_dev.make — 새 배치·생산일지),
  template: "효력환"        (그 템플릿 행을 불러와 저장 — A02 + DOC PATCH, 선택),
  fill: true                (작업 전 점검·점검자 + 공정마다 필수 칸, 선택),
  complete: true            (작성완료, 선택 — fill 필요),
  output_after_kg: 40       (작성완료 뒤 수불 산출 등록 — "연동 값이 바뀌었습니다", 선택),
  drop_ccp: "CCP-2B"        (그 배치의 그 CCP 일지를 논리 삭제 — 품목 예외 흉내, 선택)
} → 201 {scenario, batch_id, batch_number, prod_log_id, documents, version}

GET·POST /api/dev/prodlog/link-fail {on: bool, batch_id} → {on, batch_id, seconds_left}
  켜면 그 배치 하나의 수불 0009 연동 읽기가 실패한다(REQ F13 → SourceUnavailable, 배치 상태+BOM 줄 →
  lines None). 다른 배치는 정상. 5분 뒤 스스로 꺼짐(r1 A3 a).
  배치 상태(v_doc_batch 기본 컬럼)는 그대로 읽힌다 — 0009 마이그레이션 전 상황.
  서버 프로세스 안에서만.

스냅샷(④)용: master_tables(process_id=…|process_template_id=…) — 공정·템플릿·단계·변경 이력.
"""

import time
import uuid
from decimal import Decimal

from django.db import connection, transaction
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from apps.core.http import ApiError, error_response, json_response, parse_json_body
from apps.doc_requirements import errors as req_errors
from apps.doc_requirements import services as req
from apps.documents import services as doc
from apps.production_log import logbook
from apps.production_log.models import (
    MasterChangeLog,
    Process,
    ProcessTemplate,
    ProcessTemplateStep,
)

from . import prodlog_dev
from .fixtures import ACTOR, _bad

KEYS = {"scenario", "template", "fill", "complete", "output_after_kg", "drop_ccp"}
RESULT = {
    "CCP-1P": {"verdict": "적합"},
    "CCP-3P": {"verdict": "적합"},
    "CCP-2B": {"temp": 70.1, "time_min": 118},
    "INNER": {"qty": 12000, "qty_unit": "환"},
    "OUTER": {"material": "PP", "expiry": "2028-10-26", "fg_qty": 100, "fg_unit": "box"},
}
GEN = {
    "JUDGE": {"verdict": "적합"},
    "TEMP_TIME": {"temp": 95, "time_min": 30},
    "QTY": {"qty": 1, "qty_unit": "EA"},
}


def _version(document_id):
    return doc.get_document(document_id)["version"]


def _patch(document_id, sections):
    with transaction.atomic():
        return doc.update_document(
            ACTOR, document_id, {"expected_version": _version(document_id), "sections": sections}
        )


def _clean(body):
    unknown = sorted(set(body) - KEYS)
    if unknown:
        raise _bad(f"모르는 키: {unknown}")
    if body.get("scenario") not in prodlog_dev.SCENARIOS:
        raise _bad(f"scenario는 {prodlog_dev.SCENARIOS} 중 하나입니다.")
    if body.get("complete") and not body.get("fill"):
        raise _bad("complete는 fill과 함께 씁니다.")
    return body


@csrf_exempt
@require_http_methods(["POST"])
def prodlog_fixture(request):
    try:
        body = _clean(parse_json_body(request))
        made = prodlog_dev.make(body["scenario"], ACTOR)
        log = made["prod_log_id"]
        if body.get("drop_ccp"):
            target = next(
                (d for d in made["documents"] if d["type_code"] == body["drop_ccp"]), None
            )
            if target is None:
                raise _bad(f"이 배치에 {body['drop_ccp']} 일지가 없습니다.")
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE document SET deleted_at = CURRENT_TIMESTAMP, deleted_by = %s"
                    " WHERE document_id = %s",
                    [ACTOR, target["document_id"]],
                )
        if body.get("template"):
            found = ProcessTemplate.objects.filter(name=body["template"], is_active=True).first()
            if found is None:
                raise _bad(f"사용 중인 템플릿 '{body['template']}'이 없습니다.")
            with transaction.atomic():
                rows = logbook.template_rows(ACTOR, log, found.pk, "replace")
            _patch(log, {"add": [{"section_def": "steps", "values": v} for v in rows["rows"]]})
        if body.get("fill"):
            d = doc.get_document(log)
            info = next(s for s in d["sections"] if s["section_def"] == "info")
            steps = [s for s in d["sections"] if s["section_def"] == "steps"]
            updates = [
                {
                    "section_id": info["section_id"],
                    "values": {
                        "pre_label": "적합",
                        "pre_clean": "적합",
                        "pre_lot": "적합",
                        "inspector": ACTOR,
                    },
                }
            ]
            for s in steps:
                v = s["values"]
                extra = (
                    GEN.get(v.get("mode"), {})
                    if v.get("kind") == "GEN"
                    else RESULT.get(v.get("kind"), {})
                )
                extra = {**extra, "worker": ACTOR}
                if v.get("dur_on") and v.get("dur_value") is None:
                    extra.update(dur_value=1, dur_unit="시간")
                updates.append({"section_id": s["section_id"], "values": extra})
            _patch(log, {"update": updates})
        if body.get("complete"):
            with transaction.atomic():
                doc.complete_document(ACTOR, log, _version(log))
        if body.get("output_after_kg"):
            from apps.inventory.production import add_output

            add_output(
                batch_id=made["batch_id"],
                quantity=Decimal(str(body["output_after_kg"])),
                staff_id=ACTOR,
                idempotency_key=f"dev-p15-out-{uuid.uuid4().hex}",
            )
        return json_response({**made, "version": _version(log)}, status=201)
    except ApiError as error:
        return error_response(error)


# ---------------------------------------------------------------- 연동 오류 스위치 (PLG-PS-06)
# r1 A3 a: 지정한 배치 하나에만 걸리고, TTL(기본 5분)이 지나면 스스로 꺼진다.
# 다른 요청·배치는 정상 연동.

TTL_SECONDS = 300
_ORIGINAL = {}
_TARGET = {}  # {"batch_id": int, "until": monotonic}


def _active():
    if _TARGET and time.monotonic() >= _TARGET["until"]:
        set_link_fail(False)
    return bool(_TARGET)


def link_fail_state():
    if not _active():
        return {"on": False}
    left = max(0, round(_TARGET["until"] - time.monotonic()))
    return {"on": True, "batch_id": _TARGET["batch_id"], "seconds_left": left}


def set_link_fail(on, batch_id=None, ttl=TTL_SECONDS):
    if on:
        if not _ORIGINAL:
            _ORIGINAL["source"] = req.production_log_source
            _ORIGINAL["state"] = req.production_batch_state
            source, state = _ORIGINAL["source"], _ORIGINAL["state"]

            def failing_source(bid):
                if _active() and bid == _TARGET["batch_id"]:
                    raise req_errors.SourceUnavailable()
                return source(bid)

            def state_without_lines(bid, with_lines=False):
                if not (_active() and bid == _TARGET["batch_id"]):
                    return state(bid, with_lines=with_lines)
                out = state(bid)
                return {**out, "lines": None} if with_lines else out

            req.production_log_source = failing_source
            req.production_batch_state = state_without_lines
        _TARGET.update(batch_id=batch_id, until=time.monotonic() + ttl)
    else:
        _TARGET.clear()
        if _ORIGINAL:
            req.production_log_source = _ORIGINAL.pop("source")
            req.production_batch_state = _ORIGINAL.pop("state")
    return link_fail_state()


@csrf_exempt
@require_http_methods(["GET", "POST"])
def link_fail(request):
    try:
        if request.method == "POST":
            body = parse_json_body(request)
            if not isinstance(body.get("on"), bool):
                raise _bad("on(true/false)이 필요합니다.")
            if body["on"]:
                bid = body.get("batch_id")
                if not isinstance(bid, int) or isinstance(bid, bool):
                    raise _bad("on: true에는 batch_id(정수)가 필요합니다 — 그 배치에만 연동 오류.")
                set_link_fail(True, bid)
            else:
                set_link_fail(False)
        return json_response(link_fail_state())
    except ApiError as error:
        return error_response(error)


# ---------------------------------------------------------------- ④ 스냅샷: 기준정보


def master_tables(process_id=None, template_id=None):
    """공정 하나(그 공정을 쓰는 템플릿 단계·이력) 또는 템플릿 하나(단계·이력)."""

    def rows(qs):
        return [
            {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in r.items()}
            for r in qs.values()
        ]

    if process_id is not None:
        return {
            "process": rows(Process.objects.filter(pk=process_id)),
            "process_template_step": rows(
                ProcessTemplateStep.objects.filter(process_id=process_id).order_by("pk")
            ),
            "master_change_log": rows(
                MasterChangeLog.objects.filter(target="process", target_id=process_id).order_by(
                    "pk"
                )
            ),
        }
    return {
        "process_template": rows(ProcessTemplate.objects.filter(pk=template_id)),
        "process_template_step": rows(
            ProcessTemplateStep.objects.filter(template_id=template_id).order_by("seq")
        ),
        "master_change_log": rows(
            MasterChangeLog.objects.filter(target="template", target_id=template_id).order_by("pk")
        ),
    }
