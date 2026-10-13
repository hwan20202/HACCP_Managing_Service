"""스프린트 3 개발 콘솔 프리셋의 사전 조건 (C3 S5 — FILE-PS-*·P8-PS-*, ISS-019 방식).

모두 실제 공개 함수(REQ·DOC·WF)로 만든다. 개발 설정에서만(devtools URL).

POST /api/dev/fixtures/file-doc {            파일 업로드(D01·D02, F-002 Q5)
  type_code: D01 | D02          (기본 D01),
  state: draft | completed | submitted       (기본 draft — completed·submitted는 파일 1개 이상),
  files: 0~5                    (이 문서에 올려 둘 견본 파일 수, 기본 0. 1번은 PDF, 2번부터 PNG),
  received_date: YYYY-MM-DD     (기본 오늘. 새 입고 LOT — 품목 유자, 매입처 콘솔준비농협)
}
→ 201 {document_id, lot_id, lot_number, version, status, files: [file_id…]}

POST /api/dev/fixtures/periodic {            P8 점검표(D10·D12·D11) — 주기 작성 요구(N1)로 만듦
  type_code: D10 | D12 | D11    (기본 D10),
  week_start: YYYY-MM-DD(월)    (기본: 이번 주 이전에서 그 양식 문서가 하나도 없는 가장 가까운 주),
  days: [{weekday: 1~7, state, x: bool}]  (기본 월~금 draft. D11은 weekday 무시 — 그 주 월요일 1건)
       state: draft | filled | completed | submitted | submitted_partial | approved | skipped
       x: filled 이상에서 첫 매일 항목을 X로 + 개선조치 1건
}
→ 201 {type_code, week_start, items: [{document_id, work_date, status, version}]}
record_key는 P9 형식(`{코드}|day:{날짜}`, D11 `|week:{월요일}`).
이미 있으면 그 문서를 그대로 돌려준다.
"""

import datetime

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from apps.core.http import ApiError, error_response, json_response, parse_json_body
from apps.doc_requirements import services as req
from apps.document_workflow import services as wf
from apps.documents import files as doc_files
from apps.documents import services as doc
from apps.documents.models import Document

from . import inventory_dev
from .fixtures import ACTOR, SLOTS, _bad, _new_lot, _version

PERIODIC_TYPES = ("D10", "D12", "D11")
PERIODIC_STATES = (
    "draft",
    "filled",
    "completed",
    "submitted",
    "submitted_partial",
    "approved",
    "skipped",
)
FILE_STATES = ("draft", "completed", "submitted")
# 견본 파일: 서명(DOC-VR-20)만 맞으면 된다
SAMPLE_PDF = (
    b"%PDF-1.4\n% console sample\n1 0 obj << /Type /Catalog >> endobj\ntrailer << >>\n%%EOF\n"
)
SAMPLE_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    b"\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00"
    b"\x00\x00IEND\xaeB`\x82"
)


def sample_upload(n, prefix="콘솔_성적서"):
    if n == 1:
        return SimpleUploadedFile(f"{prefix}_{n}.pdf", SAMPLE_PDF, "application/pdf")
    return SimpleUploadedFile(f"{prefix}_{n}.png", SAMPLE_PNG, "image/png")


def _day(raw, name):
    if raw is None:
        return None
    try:
        if not isinstance(raw, str) or len(raw) != 10:
            raise ValueError(raw)
        return datetime.date.fromisoformat(raw)
    except ValueError:
        raise _bad(f"{name}는 YYYY-MM-DD입니다.") from None


def _submit(document_id):
    out = wf.submit(ACTOR, document_id, _version(document_id), [dict(s) for s in SLOTS])
    return {s["slot_no"]: s["approval_id"] for s in out["request"]["slots"]}


# ---------------------------------------------------------------- 파일 업로드(D01·D02)


def build_file_doc(type_code="D01", state="draft", files=0, day=None):
    day = day or timezone.localdate()
    with transaction.atomic():
        lot_id = _new_lot(day)
        out = req.require_for_lot(ACTOR, lot_id)
    document_id = next(d for d in out["documents"] if d["type_code"] == type_code)["document_id"]
    if type_code == "D02":
        detail = doc.get_document(document_id)
        info = next(s for s in detail["sections"] if s["section_def"] == "info")
        doc.update_document(
            ACTOR,
            document_id,
            {
                "expected_version": detail["version"],
                "sections": {
                    "update": [
                        {"section_id": info["section_id"], "values": {"doc_kind": "수입면장"}}
                    ]
                },
            },
        )
    file_ids = []
    for n in range(1, files + 1):
        made = doc_files.attach_file(ACTOR, document_id, _version(document_id), sample_upload(n))
        file_ids.append(made["file"]["file_id"])
    if state in ("completed", "submitted"):
        doc.complete_document(ACTOR, document_id, _version(document_id))
    if state == "submitted":
        _submit(document_id)
    return lot_id, document_id, file_ids


@csrf_exempt
@require_http_methods(["POST"])
def file_doc_fixture(request):
    try:
        body = parse_json_body(request)
        type_code = body.get("type_code", "D01")
        state = body.get("state", "draft")
        files = body.get("files", 0)
        if type_code not in ("D01", "D02"):
            raise _bad("type_code는 D01 또는 D02입니다.")
        if state not in FILE_STATES:
            raise _bad(f"state는 {', '.join(FILE_STATES)} 중 하나입니다.")
        if isinstance(files, bool) or not isinstance(files, int) or not 0 <= files <= 5:
            raise _bad("files는 0~5입니다.")
        if state != "draft" and files < 1:
            raise _bad("작성완료·결재중은 파일이 1개 이상 필요합니다(files ≥ 1).")
        day = _day(body.get("received_date"), "received_date")
        lot_id, document_id, file_ids = build_file_doc(type_code, state, files, day)
    except ApiError as error:
        return error_response(error)
    detail = doc.get_document(document_id)
    return json_response(
        {
            "document_id": document_id,
            "lot_id": lot_id,
            "lot_number": inventory_dev.lot_number(lot_id),
            "version": detail["version"],
            "status": detail["status"],
            "files": file_ids,
        },
        status=201,
    )


# ---------------------------------------------------------------- P8 점검표(D10·D12·D11)


def free_week(type_code, today=None):
    """이번 주 이전에서 그 양식 문서가 하나도 없는 가장 가까운 주의 월요일(최대 2년 전까지)."""
    today = today or timezone.localdate()
    monday = today - datetime.timedelta(days=today.isoweekday() - 1)
    for back in range(1, 105):
        start = monday - datetime.timedelta(weeks=back)
        if not Document.objects.filter(
            template__type_code=type_code,
            work_date__gte=start,
            work_date__lte=start + datetime.timedelta(days=6),
        ).exists():
            return start
    raise _bad("빈 주를 찾지 못했습니다.")


def _periodic(type_code, day):
    unit = "week" if type_code == "D11" else "day"
    with transaction.atomic():
        return doc.get_or_create_document(
            ACTOR, type_code, f"{type_code}|{unit}:{day.isoformat()}", day.isoformat(), []
        )["document"]


def _fill_check(document_id, x=False, inspector=4):
    detail = doc.get_document(document_id)
    schema = doc.get_template(detail["template"]["template_id"])["schema"]
    rows = {s["section_def"]: s for s in detail["sections"]}
    info, checks = {"inspector": inspector}, {}
    code = detail["template"]["type_code"]
    if code == "D12":
        info["process_name"] = "내포장"
    if code == "D11":
        info["checked_on"] = detail["work_date"]
    section = next(s for s in schema["sections"] if s["key"] == "checks")
    results = [
        f
        for f in section["fields"]
        if f["type"] == "select" and rows["checks"]["values"].get(f["key"]) != "NA"
    ]
    for n, field in enumerate(results):
        checks[field["key"]] = "X" if x and n == 0 else "O"
    doc.update_document(
        ACTOR,
        document_id,
        {
            "expected_version": detail["version"],
            "sections": {
                "update": [
                    {"section_id": rows["info"]["section_id"], "values": info},
                    {"section_id": rows["checks"]["section_id"], "values": checks},
                ]
            },
        },
    )
    if x:
        doc.create_deviation(
            4,
            document_id,
            {"description": f"{results[0]['label'][:40]} — 불량(콘솔 준비)", "actor_id": 4},
        )


def build_periodic(type_code, day, state="draft", x=False):
    detail = _periodic(type_code, day)
    document_id = detail["document_id"]
    if detail["version"] != 1 or state == "draft":
        return document_id  # 이미 있던 문서는 그대로
    if state == "skipped":
        doc.skip_documents(
            ACTOR, [{"document_id": document_id, "expected_version": 1}], "휴무(콘솔 준비)"
        )
        return document_id
    _fill_check(document_id, x)
    if state == "filled":
        return document_id
    doc.complete_document(ACTOR, document_id, _version(document_id))
    if state == "completed":
        return document_id
    ids = _submit(document_id)
    if state == "submitted":
        return document_id
    wf.decide(3, ids[1], "approved")
    if state == "approved":
        wf.decide(1, ids[2], "approved")
    return document_id


@csrf_exempt
@require_http_methods(["POST"])
def periodic_fixture(request):
    try:
        body = parse_json_body(request)
        type_code = body.get("type_code", "D10")
        if type_code not in PERIODIC_TYPES:
            raise _bad("type_code는 D10·D12·D11 중 하나입니다.")
        start = _day(body.get("week_start"), "week_start")
        if start is not None and start.isoweekday() != 1:
            raise _bad("week_start는 월요일이어야 합니다.")
        start = start or free_week(type_code)
        days = body.get("days") or [{"weekday": n} for n in range(1, 6)]
        if not isinstance(days, list) or len(days) > 7:
            raise _bad("days는 7개 이하의 목록입니다.")
        plan = []
        for item in days:
            weekday = item.get("weekday", 1) if isinstance(item, dict) else None
            state = item.get("state", "draft") if isinstance(item, dict) else None
            if isinstance(weekday, bool) or not isinstance(weekday, int) or not 1 <= weekday <= 7:
                raise _bad("weekday는 1(월)~7(일)입니다.")
            if state not in PERIODIC_STATES:
                raise _bad(f"state는 {', '.join(PERIODIC_STATES)} 중 하나입니다.")
            day = start if type_code == "D11" else start + datetime.timedelta(days=weekday - 1)
            plan.append((day, state, bool(item.get("x"))))
        made = [build_periodic(type_code, day, state, x) for day, state, x in plan]
    except ApiError as error:
        return error_response(error)
    items = []
    for document_id in dict.fromkeys(made):
        detail = doc.get_document(document_id)
        items.append(
            {
                "document_id": document_id,
                "work_date": detail["work_date"],
                "status": detail["status"],
                "version": detail["version"],
            }
        )
    return json_response(
        {"type_code": type_code, "week_start": start.isoformat(), "items": items}, status=201
    )


__all__ = ["build_file_doc", "build_periodic", "file_doc_fixture", "periodic_fixture"]
