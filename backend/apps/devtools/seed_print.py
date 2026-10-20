"""P12 S5 개발 시드: 결재 칸이 찍힌 CCP 출력 확인용 (p12-ccp-policy.md, PRT-PS-01·02).

새 제조 배치 1개(노트 `dev-seed-print-YYYY-MM-DD`)를 만들고 작성 요구로 CCP-1P·2B·3P를 만든 뒤
WF 함수로 상태를 맞춘다(P14 역할 결재선 — 담당자 3, HACCP팀장 5):

- CCP-1P **승인**: 측정 4행(작업 중 1행 부적합) + 개선조치 1건 **확인됨**(확인자 5)
- CCP-2B **결재중**: 담당자 칸만 승인, 측정이 다음 날까지(작성일자 "~")
- CCP-3P(v2) **정정 중**: 승인 뒤 정정 시작, 값 하나 바꿈 + 정정 중 개선조치 1건(출력은 승인본 값)

같은 날짜로 다시 실행하면 이미 만든 배치·문서를 그대로 둔다. 개발 설정에서만(명령이 확인).
개선조치 확인은 P11 확인 기능이 이 브랜치에 없어 개발 시드에서만 직접 기록한다.
"""

from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from apps.doc_requirements import services as req
from apps.document_workflow import services as wf
from apps.documents import services as doc
from apps.documents.models import DeviationAction
from apps.documents.seed import ensure_p4_templates, ensure_staff

from . import inventory_dev
from .seed_p4 import BATCHES, _add_rows, _at, _complete, _set_info

OWNER, LEADER, INSPECTOR = 3, 5, 4


def _submit_and_decide(document_id, *, leader=True):
    version = doc.get_document(document_id)["version"]
    request = wf.submit(OWNER, document_id, version)["request"]
    slots = {s["role"]: s["approval_id"] for s in request["slots"]}
    wf.decide(OWNER, slots["owner"], "approved")
    if leader:
        wf.decide(LEADER, slots["leader"], "approved")


def seed_print(today=None):
    """반환 {code: document_id}. 이미 만든 날이면 created=False."""
    today = today or timezone.localdate()
    if isinstance(today, str):
        today = date.fromisoformat(today)
    ensure_staff()
    ensure_p4_templates()
    items = inventory_dev.ensure_master()
    item_name, qty = BATCHES[0]
    batch_id = inventory_dev.make_batch(
        item_id=items[item_name],
        process_type="MANUFACTURE",
        manufactured_date=today,
        quantity_kg=qty,
        staff_id=OWNER,
        notes=f"dev-seed-print-{today.isoformat()}",
    )
    with transaction.atomic():
        inventory_dev.touch_batch(batch_id)
        out = req.require_for_batch(OWNER, batch_id)
    docs = {d["type_code"]: d for d in out["documents"]}
    result = {code: d["document_id"] for code, d in docs.items()}
    if any(d["result"] != "created" for d in docs.values()):
        return {"created": False, **result}

    # CCP-1P 승인 + 확인된 개선조치
    p1 = result["CCP-1P"]
    _add_rows(OWNER, p1, "rounds", [
        {"phase": "작업시작 전", "measured_at": _at(today, "08:50"), "gauss": 10500, "rod_cleaned": "O"},
        {"phase": "작업 중", "measured_at": _at(today, "09:50"), "gauss": 9800, "rod_cleaned": "O"},
        {"phase": "작업 중", "measured_at": _at(today, "10:50"), "gauss": 10400, "rod_cleaned": "O"},
        {"phase": "작업종료 후", "measured_at": _at(today, "17:00"), "gauss": 10200, "rod_cleaned": "O"},
    ])  # fmt: skip
    _set_info(INSPECTOR, p1, {"inspector": INSPECTOR})
    deviation = doc.create_deviation(
        INSPECTOR,
        p1,
        {
            "description": "09:50 자력 9,800G(기준 10,000G 미달)",
            "action_result": "자석봉 재청소 후 10,400G 확인, 그 사이 제품 재검사 적합",
            "actor_id": INSPECTOR,
            "checker_ids": [LEADER],
        },
    )
    DeviationAction.objects.filter(pk=deviation["deviation_id"]).update(
        checked_by_id=LEADER, checked_at=timezone.now()
    )
    _complete(OWNER, p1)
    _submit_and_decide(p1)

    # CCP-2B 결재중(담당자 칸만 승인), 측정이 다음 날까지
    p2 = result["CCP-2B"]
    _add_rows(OWNER, p2, "rounds", [
        {"phase": "건조시작 전", "measured_at": _at(today, "09:00"), "temp_c": 70.1, "dry_minutes": 120},
        {"phase": "작업 중", "measured_at": _at(today, "15:00"), "temp_c": 70.4, "dry_minutes": 121},
        {"phase": "건조종료 전", "measured_at": _at(today + timedelta(days=1), "11:00"), "temp_c": 69.8,
         "dry_minutes": 119},
    ])  # fmt: skip
    _set_info(INSPECTOR, p2, {"inspector": INSPECTOR})
    _complete(OWNER, p2)
    _submit_and_decide(p2, leader=False)

    # CCP-3P 승인 → 정정 중(값 하나 바꿈)
    p3 = result["CCP-3P"]
    ok = {"fe_only": "○", "sts_only": "○", "product_only": "X"}
    ok.update(product_fe="○", product_sus="○")
    _add_rows(OWNER, p3, "checks", [
        {"phase": "시작", "passed_at": _at(today, "08:40"), **ok},
        {"phase": "중간", "passed_at": _at(today, "10:40"), **ok},
        {"phase": "중간", "passed_at": _at(today, "12:40"), **ok},
        {"phase": "종료", "passed_at": _at(today, "17:10"), **ok},
    ])  # fmt: skip
    _add_rows(OWNER, p3, "summary", [
        {"item_name": item_name, "passed_qty": 1180, "detected_qty": 0, "note": "이상 없음"},
    ])  # fmt: skip
    _set_info(INSPECTOR, p3, {"inspector": INSPECTOR})
    _complete(OWNER, p3)
    _submit_and_decide(p3)
    doc.start_correction(
        OWNER, p3, doc.get_document(p3)["version"], "12:40 통과시간 오기(시드: 정정 중)"
    )
    row = next(
        s
        for s in doc.get_document(p3)["sections"]
        if s["section_def"] == "checks" and s["values"].get("passed_at", "").endswith("12:40")
    )
    doc.update_document(
        OWNER,
        p3,
        {
            "expected_version": doc.get_document(p3)["version"],
            "sections": {
                "update": [
                    {"section_id": row["section_id"], "values": {"passed_at": _at(today, "12:45")}}
                ]
            },
        },
    )
    doc.create_deviation(
        INSPECTOR,
        p3,
        {"description": "정정 중 추가한 개선조치(출력엔 현재 값)", "actor_id": INSPECTOR},
    )
    return {"created": True, **result}
