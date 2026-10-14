"""개발 콘솔 프리셋의 사전 조건 만들기 (ISS-019, P6 S5).

프리셋이 시드 문서 상태에 기대면 앞선 확인이 그 문서를 바꿀 때 실행할 수 없다
(P5 S6, P6a S5 DOC-PS-25).
P6 프리셋은 실행 전에 이 개발 API로 **새 입고 LOT과 육안검사(D03)**를 원하는 상태까지 만든다.
모두 실제 공개 함수(REQ·DOC·WF)로 만들고, 판정 전달(EFF)도 그대로 거친다.
입고 LOT은 수불 입고 서비스로 만든다(C2 — LOT 번호는 수불 규칙, 품목 "유자"). 개발 설정에서만.

POST /api/dev/fixtures/d03 {
  state: draft | completed | approved | submitted | submitted_partial | rejected | correcting
         | correction_completed | correction_submitted,
         (submitted_partial: 담당 staff 3 승인 뒤 staff 1 대기, rejected: staff 1 반려 — P7)
  verdict: PASS | FAIL           (검사 값, 기본 PASS),
  edited: bool                   (correcting: 정정 시작 뒤 한 번 수정),
  change_to: PASS | FAIL         (correcting 계열: 정정 시작 뒤 판정을 이 값으로 고침),
  used: bool                     (승인 뒤 수불 재고조정(감소) 1건 — "사용된 LOT", P1),
  received_date: YYYY-MM-DD      (P7, 기본 오늘. 미래 불가. LOT 번호는 수불 규칙 AYJ{yyMMdd}…),
  count: 1~10                    (P7, 기본 1),
  inspector: staff id | null     (P7, 기본 4. null이면 점검자 비움 — 작성중(draft)만)
  lot_only: bool                 (P7 S5, 기본 false. 문서 없는 입고 LOT(수불 훅 연결 전 LOT 흉내) —
                                  묶음 상세의 "문서 없음" 줄 확인용. 다른 옵션은 received_date만 씀)
}
→ 201 {document_id, lot_id, lot_number, version, status}
   lot_only면 {lot_id, lot_number, document_id: null}
   count > 1이면 {items: [{document_id, lot_id, lot_number, version, status}, …]}
"""

import datetime

from django.db import transaction
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from apps.core.http import ApiError, error_response, json_response, parse_json_body
from apps.doc_requirements import services as req
from apps.document_workflow import services as wf
from apps.documents import services as doc

from . import inventory_dev

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
    "submitted_partial",
    "rejected",
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


def _clean_p7(body, state):
    """P7 옵션: received_date·count·inspector(p7-s2-spec 3.5)."""
    raw = body.get("received_date")
    day = timezone.localdate()
    if raw is not None:
        try:
            if not isinstance(raw, str) or len(raw) != 10:
                raise ValueError(raw)
            day = datetime.date.fromisoformat(raw)
        except ValueError:
            raise _bad("received_date는 YYYY-MM-DD입니다.") from None
    count = body.get("count", 1)
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 10:
        raise _bad("count는 1~10입니다.")
    inspector = body.get("inspector", 4)
    if inspector is not None and (isinstance(inspector, bool) or not isinstance(inspector, int)):
        raise _bad("inspector는 staff id 또는 null입니다.")
    if inspector is None and state != "draft":
        raise _bad("점검자가 없으면 작성완료할 수 없습니다 — inspector: null은 draft에서만.")
    return day, count, inspector


def _version(document_id):
    return doc.get_document(document_id)["version"]


def _fill(document_id, verdict, inspector=4):
    detail = doc.get_document(document_id)
    info = next(s for s in detail["sections"] if s["section_def"] == "info")
    check = next(s for s in detail["sections"] if s["section_def"] == "inspection")
    updates = [
        {"section_id": check["section_id"], "values": {**CHECK[verdict], "verdict": verdict}}
    ]
    if inspector is not None:
        updates.append({"section_id": info["section_id"], "values": {"inspector": inspector}})
    doc.update_document(
        ACTOR,
        document_id,
        {"expected_version": detail["version"], "sections": {"update": updates}},
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


def _new_lot(day, documents=True):
    """입고 LOT(수불 입고 훅이 D01·D02·D03을 만듦). documents=False면 문서 없는 예전 LOT 흉내."""
    items = inventory_dev.ensure_master()
    return inventory_dev.receive(
        item_id=items["유자"],
        supplier_name="콘솔준비농협",
        received_date=day,
        quantity=100,
        staff_id=ACTOR,
        documents=documents,
    )


def build_d03(
    state, verdict="PASS", change_to=None, edited=False, used=False, day=None, inspector=4
):
    day = day or timezone.localdate()
    with transaction.atomic():
        lot_id = _new_lot(day)
        out = req.require_for_lot(ACTOR, lot_id)
        document_id = next(d for d in out["documents"] if d["type_code"] == "D03")["document_id"]
    _fill(document_id, verdict, inspector)
    if state == "draft":
        return lot_id, document_id
    doc.complete_document(ACTOR, document_id, _version(document_id))
    if state == "completed":
        return lot_id, document_id
    if state == "submitted":
        _submit(document_id)
        return lot_id, document_id
    if state == "submitted_partial":  # P7: 담당(staff 3) 승인, HACCP팀장(staff 1) 대기
        wf.decide(3, _submit(document_id)[1], "approved")
        return lot_id, document_id
    if state == "rejected":  # P7: HACCP팀장(staff 1) 반려
        wf.decide(1, _submit(document_id)[2], "rejected", "콘솔 준비: 반려")
        return lot_id, document_id
    _approve(document_id)
    if used:
        inventory_dev.use_lot(lot_id, ACTOR)
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
        lot_only = body.get("lot_only", False)
        if not isinstance(lot_only, bool):
            raise _bad("lot_only는 true 또는 false입니다.")
        if lot_only:
            day, _count, _inspector = _clean_p7(body, "draft")
            with transaction.atomic():
                lot_id = _new_lot(day, documents=False)
            lot_number = inventory_dev.lot_number(lot_id)
            return json_response(
                {"lot_id": lot_id, "lot_number": lot_number, "document_id": None}, status=201
            )
        state, verdict, change_to, edited, used = _clean(body)
        day, count, inspector = _clean_p7(body, state)
        made = [
            build_d03(state, verdict, change_to, edited, used, day, inspector) for _ in range(count)
        ]
    except ApiError as error:
        return error_response(error)
    items = []
    for lot_id, document_id in made:
        detail = doc.get_document(document_id)
        items.append(
            {
                "document_id": document_id,
                "lot_id": lot_id,
                "lot_number": inventory_dev.lot_number(lot_id),
                "version": detail["version"],
                "status": detail["status"],
                "correction": detail["correction"],
            }
        )
    if count == 1:
        return json_response(items[0], status=201)
    return json_response(
        {"items": [{k: v for k, v in i.items() if k != "correction"} for i in items]}, status=201
    )


__all__ = ["build_d03", "d03_fixture"]
