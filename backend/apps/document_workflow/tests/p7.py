"""P7 테스트 준비물 (p7-s2-spec 7장). 이름의 tcNNN은 P7-TC ID.

육안검사(D03)는 실제 공개 함수로 원하는 상태까지 만든다: DOC N1(get_or_create_document, REQ와 같은
값) → 수정(점검자·검사) → 작성완료(EFF 판정 전달 — 개발 판정 함수) → WF 상신·승인·반려 → 정정.
수불 값(LOT·입고 기록)은 실제 수불 테이블에 SQL로 넣는다(stub, C2).
WF 테스트는 REQ를 import하지 않는다(REQ-TC-030).
결재선은 개발 API fixtures/d03과 같다: 1번 담당 staff 3, 2번 HACCP팀장 staff 1.
"""

import itertools

from django.db import connection, transaction

from apps.document_workflow import services as wf
from apps.documents import services as doc
from apps.documents.seed import ensure_p4_templates, ensure_staff
from apps.documents.tests.base import setup_reference_data
from apps.documents.tests.p4 import stub

DAY = "2026-10-13"
SLOTS = [
    {"slot_no": 1, "label": "담당", "approver_id": 3},
    {"slot_no": 2, "label": "HACCP팀장", "approver_id": 1},
]
CHECK = {
    "PASS": {"appearance": "양호", "packaging": "양호", "labeling": "양호", "verdict": "PASS"},
    "FAIL": {"appearance": "양호", "packaging": "불량", "labeling": "양호", "verdict": "FAIL"},
}
_lot_ids = itertools.count(300)
_lot_numbers = {}


def setup_p7():
    ensure_staff(5)
    ensure_p4_templates()
    templates = setup_reference_data()  # CCP_MONITORING(직접 만든 문서)
    stub("items", id=1, name="유자")
    return templates


def slots():
    return [dict(s) for s in SLOTS]


def sql(statement, params=()):
    with connection.cursor() as cursor:
        cursor.execute(statement, params)
        return cursor.fetchall()


def new_lot(day=DAY, supplier="고흥농협"):
    """입고 LOT 1개(같은 입고일이면 번호 이어서 RM-MMDD-nn)."""
    lot_id = next(_lot_ids)
    n = _lot_numbers[day] = _lot_numbers.get(day, 0) + 1
    number = f"RM-{day[5:7]}{day[8:10]}-{n:02d}"
    if sql("SELECT 1 FROM lots WHERE lot_number = %s", [number]):  # 다른 테스트 클래스 데이터
        return new_lot(day, supplier)
    stub("lots", id=lot_id, lot_number=number, item_id=1, lot_kind="INCOMING", status="QUARANTINE")
    stub("receipt", lot_id=lot_id, supplier_name=supplier, received_date=day, quantity=500)
    return lot_id, number


def version_of(document_id):
    return doc.get_document(document_id)["version"]


def fill(document_id, verdict="PASS", inspector=4, actor=3):
    detail = doc.get_document(document_id)
    sections = {s["section_def"]: s for s in detail["sections"]}
    updates = [{"section_id": sections["inspection"]["section_id"], "values": CHECK[verdict]}]
    if inspector is not None:
        updates.append(
            {"section_id": sections["info"]["section_id"], "values": {"inspector": inspector}}
        )
    doc.update_document(
        actor, document_id, {"expected_version": detail["version"], "sections": {"update": updates}}
    )
    if verdict == "FAIL" and not doc.get_document(document_id)["deviations"]:
        doc.create_deviation(4, document_id, {"description": "포장 파손", "action_result": "반품"})


def complete(document_id, actor=3):
    return doc.complete_document(actor, document_id, version_of(document_id))


def submit(document_id):
    request = wf.submit(3, document_id, version_of(document_id), slots())["request"]
    return {s["slot_no"]: s["approval_id"] for s in request["slots"]}


def d03(state="draft", verdict="PASS", day=DAY, inspector=4, supplier="고흥농협"):
    """새 LOT의 D03을 state까지. 반환 dict(document_id, lot_id, lot_number, slots)."""
    lot_id, number = new_lot(day, supplier)
    info = {
        "lot_number": number,
        "received_date": day,
        "supplier_name": supplier,
        "material_kind": "원료",
        "item_name": "유자",
        "quantity": "500kg",
    }
    with transaction.atomic():
        made = doc.get_or_create_document(
            3,
            "D03",
            f"D03|lot:{lot_id}",
            day,
            [{"lot_id": lot_id, "label": number}],
            {"info": info},
        )
    document_id = made["document"]["document_id"]
    out = {"document_id": document_id, "lot_id": lot_id, "lot_number": number, "slots": {}}
    if state == "empty":  # 점검자·검사 없음(작성중)
        return out
    fill(document_id, verdict, inspector)
    if state == "draft":
        return out
    complete(document_id)
    if state == "completed":
        return out
    if state == "rejected":
        ids = submit(document_id)
        wf.decide(1, ids[2], "rejected", "반려(시험)")
        return out
    ids = out["slots"] = submit(document_id)
    if state == "submitted":  # 1번(staff 3)·2번(staff 1) 모두 대기
        return out
    wf.decide(3, ids[1], "approved")
    if state == "submitted_partial":  # 2번(staff 1)만 대기
        return out
    wf.decide(1, ids[2], "approved")
    if state == "approved":
        return out
    doc.start_correction(3, document_id, version_of(document_id), "판정 재확인")
    if state == "correcting":
        return out
    complete(document_id)
    if state == "correction_completed":
        return out
    out["slots"] = submit(document_id)  # correction_submitted
    return out


def ccp(templates, state="completed"):
    """직접 만든 문서(CCP_MONITORING) — 일괄 대상 양식 밖."""
    from apps.documents.tests.base import ccp_payload

    document_id = doc.create_document(3, ccp_payload(templates["ccp"]))["document_id"]
    out = {"document_id": document_id, "slots": {}}
    if state == "draft":
        return out
    doc.complete_document(3, document_id, 1)
    if state == "submitted":
        out["slots"] = submit(document_id)
    return out


def status_of(document_id):
    return sql("SELECT status, version FROM document WHERE document_id = %s", [document_id])[0]


def slot_state(approval_id):
    return sql("SELECT state, comment FROM approval WHERE approval_id = %s", [approval_id])[0]
