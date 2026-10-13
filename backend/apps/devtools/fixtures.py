"""개발 콘솔 프리셋의 사전 조건 만들기 (ISS-019, P6 S5).

프리셋이 시드 문서 상태에 기대면 앞선 확인이 그 문서를 바꿀 때 실행할 수 없다
(P5 S6, P6a S5 DOC-PS-25).
P6 프리셋은 실행 전에 이 개발 API로 **새 입고 LOT과 육안검사(D03)**를 원하는 상태까지 만든다.
모두 실제 공개 함수(REQ·DOC·WF)로 만들고, 판정 전달(EFF)도 그대로 거친다.
개발 설정 + devstock에서만.

POST /api/dev/fixtures/d03 {
  state: draft | completed | approved | submitted | correcting | correction_completed
         | correction_submitted,
  verdict: PASS | FAIL           (검사 값, 기본 PASS),
  edited: bool                   (correcting: 정정 시작 뒤 한 번 수정),
  change_to: PASS | FAIL         (correcting 계열: 정정 시작 뒤 판정을 이 값으로 고침),
  used: bool                     (승인 뒤 개발 lots를 CONSUMED로 — "사용된 LOT" 흉내)
}
→ 201 {document_id, lot_id, lot_number, version, status}
"""

from django.db import transaction
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from apps.core.http import ApiError, error_response, json_response, parse_json_body
from apps.devstock.models import DevLotReceipt, Lot
from apps.doc_requirements import services as req
from apps.document_workflow import services as wf
from apps.documents import services as doc

from .req_api import _insert_numbered

ACTOR = 3
SLOTS = [
    {"slot_no": 1, "label": "담당", "approver_id": 3},
    {"slot_no": 2, "label": "HACCP팀장", "approver_id": 1},
]
STATES = (
    "draft",
    "completed",
    "approved",
    "submitted",
    "correcting",
    "correction_completed",
    "correction_submitted",
)
CHECK = {"PASS": {"appearance": "양호", "packaging": "양호", "labeling": "양호"},
         "FAIL": {"appearance": "양호", "packaging": "불량", "labeling": "양호"}}  # fmt: skip


def _bad(message):
    return ApiError(message, [{"path": "body", "code": "invalid", "message": message}])


def _clean(body):
    state = body.get("state", "draft")
    verdict = body.get("verdict", "PASS")
    change_to = body.get("change_to")
    if state not in STATES:
        raise _bad(f"state는 {', '.join(STATES)} 중 하나입니다.")
    if verdict not in CHECK or (change_to is not None and change_to not in CHECK):
        raise _bad("verdict·change_to는 PASS 또는 FAIL입니다.")
    return state, verdict, change_to, bool(body.get("edited")), bool(body.get("used"))


def _version(document_id):
    return doc.get_document(document_id)["version"]


def _fill(document_id, verdict):
    detail = doc.get_document(document_id)
    info = next(s for s in detail["sections"] if s["section_def"] == "info")
    check = next(s for s in detail["sections"] if s["section_def"] == "inspection")
    doc.update_document(
        ACTOR,
        document_id,
        {
            "expected_version": detail["version"],
            "sections": {
                "update": [
                    {"section_id": info["section_id"], "values": {"inspector": 4}},
                    {
                        "section_id": check["section_id"],
                        "values": {**CHECK[verdict], "verdict": verdict},
                    },
                ]
            },
        },
    )
    if verdict == "FAIL" and not doc.get_document(document_id)["deviations"]:
        doc.create_deviation(
            4,
            document_id,
            {
                "description": "외포장 파손(콘솔 준비)",
                "action_result": "반품",
                "actor_id": 4,
                "checker_ids": [2],
            },
        )


def _submit(document_id):
    out = wf.submit(ACTOR, document_id, _version(document_id), [dict(s) for s in SLOTS])
    return {s["slot_no"]: s["approval_id"] for s in out["request"]["slots"]}


def _approve(document_id):
    ids = _submit(document_id)
    wf.decide(3, ids[1], "approved")
    wf.decide(1, ids[2], "approved")


def _new_lot(day):
    lot_id = _insert_numbered(
        "lots",
        "lot_number",
        f"RM-{day:%m%d}-",
        ["item_id", "lot_kind", "status", "expiration_date"],
        [1, "INCOMING", "QUARANTINE", None],
    )
    DevLotReceipt.objects.create(
        lot_id=lot_id,
        material_kind="원료",
        supplier_name="콘솔준비농협",
        received_date=day,
        quantity=100,
        unit="kg",
        touched_at=timezone.now(),
    )
    return lot_id


def build_d03(state, verdict="PASS", change_to=None, edited=False, used=False):
    day = timezone.localdate()
    with transaction.atomic():
        lot_id = _new_lot(day)
        out = req.require_for_lot(ACTOR, lot_id)
        document_id = next(d for d in out["documents"] if d["type_code"] == "D03")["document_id"]
    _fill(document_id, verdict)
    if state == "draft":
        return lot_id, document_id
    doc.complete_document(ACTOR, document_id, _version(document_id))
    if state == "completed":
        return lot_id, document_id
    if state == "submitted":
        _submit(document_id)
        return lot_id, document_id
    _approve(document_id)
    if used:
        Lot.objects.filter(pk=lot_id).update(status="CONSUMED")
    if state == "approved":
        return lot_id, document_id
    doc.start_correction(ACTOR, document_id, _version(document_id), "콘솔 준비: 판정 재확인")
    if change_to:
        _fill(document_id, change_to)
    elif edited:
        doc.update_document(
            ACTOR,
            document_id,
            {"expected_version": _version(document_id), "document": {"assignee_id": 2}},
        )
    if state == "correcting":
        return lot_id, document_id
    doc.complete_document(ACTOR, document_id, _version(document_id))
    if state == "correction_submitted":
        _submit(document_id)
    return lot_id, document_id


@csrf_exempt
@require_http_methods(["POST"])
def d03_fixture(request):
    try:
        body = parse_json_body(request)
        state, verdict, change_to, edited, used = _clean(body)
        lot_id, document_id = build_d03(state, verdict, change_to, edited, used)
    except ApiError as error:
        return error_response(error)
    detail = doc.get_document(document_id)
    lot = Lot.objects.get(pk=lot_id)
    return json_response(
        {
            "document_id": document_id,
            "lot_id": lot_id,
            "lot_number": lot.lot_number,
            "version": detail["version"],
            "status": detail["status"],
            "correction": detail["correction"],
        },
        status=201,
    )


__all__ = ["build_d03", "d03_fixture"]
