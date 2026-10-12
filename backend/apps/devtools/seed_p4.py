"""P4 개발·사용 테스트용 가상 데이터 (p4-s1-screens.md 7장).

- 수불 임시 데이터(apps.devstock): 품목 4, 입고 LOT 5, 생산 배치 2. 개발·테스트 설정에서만.
- 작성 요구 문서는 P5부터 REQ F01·F02(require_for_lot·require_for_batch)로 만든다(REQ-S2-Q11).
  입고 기록·생산량은 devstock 개발용 보조 테이블(dev_lot_receipts·dev_batch_plans)에 넣고
  REQ는 뷰로 읽는다(D-069). 입고 LOT 5개 모두 D01·D02가 생긴다(P4 시드는 앞 3개만 — REQ 규칙대로).
  결재 상태는 WF 함수로 만든다(문서·회차 상태 짝 유지).
- 파일(D01·D02 첨부)은 스프린트 3(D-058)이라 만들지 않는다. D01·D02는 작성중으로 남는다.
- 개발 콘솔 P4 프리셋용: 전날 육안검사 draft(LOT 2행), 배치 2 CCP-3P draft(검출량 1, 개선조치 없음).
"""

from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from apps.devstock.models import DevBatchPlan, DevLotReceipt, Item, Lot, ProductionBatch
from apps.doc_requirements import services as req
from apps.document_workflow import services as wf
from apps.documents import services as doc
from apps.documents.seed import ensure_p4_templates, ensure_staff

SLOTS = [
    {"slot_no": 1, "label": "담당", "approver_id": 3},
    {"slot_no": 2, "label": "HACCP팀장", "approver_id": 1},
]
ITEMS = ["유자", "파우치", "유자차", "유자환"]
# (lot_number, 품목 이름, 매입처, 구분, 중량, 소비기한까지 일수)
LOTS = [
    ("RM-1011-01", "유자", "고흥농협", "원료", "500kg", 200),
    ("RM-1011-02", "파우치", "한빛포장", "부자재", "20box", 700),
    ("RM-1011-03", "유자", "남해유자", "원료", "300kg", 180),
    ("RM-1012-01", "유자", "고흥농협", "원료", "450kg", 210),
    ("RM-1012-02", "파우치", "한빛포장", "부자재", "15box", 690),
]
BATCHES = [("PB-1011-01", "유자차", 1200), ("PB-1011-02", "유자환", 800)]


def ensure_stock(today):
    items = {name: Item.objects.get_or_create(name=name)[0] for name in ITEMS}
    lots = []
    for number, item, supplier, kind, qty, days in LOTS:
        lot, _ = Lot.objects.get_or_create(
            lot_number=number,
            defaults={
                "item": items[item],
                "lot_kind": "INCOMING",
                "status": "QUARANTINE",
                "expiration_date": today + timedelta(days=days),
            },
        )
        received = today if number.startswith("RM-1011") else today - timedelta(days=1)
        amount, unit = int(qty.rstrip("kgbox")), qty.lstrip("0123456789")
        DevLotReceipt.objects.get_or_create(
            lot=lot,
            defaults={"material_kind": kind, "supplier_name": supplier, "received_date": received,
                      "quantity": amount, "unit": unit},
        )  # fmt: skip
        lots.append((lot, item, supplier, kind, qty))
    batches = []
    for number, item, qty in BATCHES:
        batch, _ = ProductionBatch.objects.get_or_create(
            batch_number=number,
            defaults={
                "item": items[item],
                "process_type": "MANUFACTURE",
                "status": "IN_PROGRESS",
                "manufactured_date": today,
            },
        )
        DevBatchPlan.objects.get_or_create(production_batch=batch, defaults={"quantity_kg": qty})
        batches.append((batch, item, qty))
    return lots, batches


def _count(made, results):
    for item in results:
        made["documents"] += int(item["result"] == "created")


def _assign(actor, results, assignee_id=2):
    """REQ는 담당자를 비워 둔다(REQ-S2-Q1). P4 시드와 같게 새로 만든 D03·CCP만 담당자 2."""
    for item in results:
        if item["type_code"] in ("D01", "D02"):
            continue  # P4 시드도 D01·D02는 담당자 없음
        if item["result"] == "created":
            document_id = item["document_id"]
            version = doc.get_document(document_id)["version"]
            patch = {"expected_version": version, "document": {"assignee_id": assignee_id}}
            doc.update_document(actor, document_id, patch)


def _at(day, hm):
    return f"{day.isoformat()}T{hm}"


def _ccp_rows(code, day):
    """작성완료할 수 있는 측정 행(첫 행 = 시작, 마지막 행 = 종료)."""
    if code == "CCP-1P":
        return "rounds", [
            {"phase": "작업시작 전", "measured_at": _at(day, "08:50"), "gauss": 10500,
             "rod_cleaned": "O"},
            {"phase": "작업 중", "measured_at": _at(day, "09:50"), "gauss": 10300,
             "rod_cleaned": "O"},
            {"phase": "작업종료 후", "measured_at": _at(day, "17:00"), "gauss": 10200,
             "rod_cleaned": "O"},
        ]  # fmt: skip
    if code == "CCP-2B":
        return "rounds", [
            {"phase": "건조시작 전", "measured_at": _at(day, "09:00"), "temp_c": 70.1,
             "dry_minutes": 120},  # 설정 건조시간(시작 전 행도 판정 대상 — 확인 필요)
            {"phase": "건조종료 전", "measured_at": _at(day + timedelta(days=1), "11:00"),
             "temp_c": 69.8, "dry_minutes": 120},
        ]  # fmt: skip
    ok = dict.fromkeys(("fe_l", "fe_c", "fe_r", "sus_l", "sus_c", "sus_r"), "○")
    ok.update(product_only="X", product_fe="○", product_sus="○")
    return "checks", [
        {"phase": "시작", "passed_at": _at(day, "08:40"), **ok},
        {"phase": "중간", "passed_at": _at(day, "10:40"), **ok, "fe_c": "X"},  # 부적합 1행
        {"phase": "종료", "passed_at": _at(day, "17:10"), **ok},
    ]


def _add_rows(actor, document_id, section, rows):
    version = doc.get_document(document_id)["version"]
    return doc.update_document(
        actor,
        document_id,
        {
            "expected_version": version,
            "sections": {"add": [{"section_def": section, "values": v} for v in rows]},
        },
    )


def _set_info(actor, document_id, values):
    detail = doc.get_document(document_id)
    info = next(s for s in detail["sections"] if s["section_def"] == "info")
    return doc.update_document(
        actor,
        document_id,
        {
            "expected_version": detail["version"],
            "sections": {"update": [{"section_id": info["section_id"], "values": values}]},
        },
    )


def _inspect(actor, document_id, verdict):
    """D03 v2 검사 섹션(1행)을 채운다."""
    detail = doc.get_document(document_id)
    row = next(s for s in detail["sections"] if s["section_def"] == "inspection")
    values = {"appearance": "양호", "packaging": "양호", "labeling": "양호", "verdict": verdict}
    return doc.update_document(
        actor,
        document_id,
        {
            "expected_version": detail["version"],
            "sections": {"update": [{"section_id": row["section_id"], "values": values}]},
        },
    )


def _complete(actor, document_id):
    version = doc.get_document(document_id)["version"]
    return doc.complete_document(actor, document_id, version)


def _submit(actor, document_id):
    version = doc.get_document(document_id)["version"]
    out = wf.submit(actor, document_id, version, [dict(s) for s in SLOTS])
    return {s["slot_no"]: s["approval_id"] for s in out["request"]["slots"]}


def seed_p4(today=None):
    """시드를 만든다. 같은 날짜로 다시 부르면 이미 있는 문서는 그대로 둔다(N1 멱등)."""
    today = today or timezone.localdate()
    if isinstance(today, str):
        today = date.fromisoformat(today)
    ensure_staff()
    ensure_p4_templates()
    lots, batches = ensure_stock(today)
    made = {"documents": 0}
    actor = 3

    with transaction.atomic():
        # 입고 LOT마다 F01: D01·D02·D03(LOT마다 1건, P6a). 오늘 3개, 전날 2개(DOC-PS-16·17·27).
        # 시드는 수불 자리라 호출 전에 자기 쓰기(touched_at)를 먼저 한다(REQ-S2-Q13).
        lot_out = []
        for lot, *_ in lots:
            DevLotReceipt.objects.filter(lot=lot).update(touched_at=timezone.now())
            out = req.require_for_lot(actor, lot.id)
            _count(made, out["documents"])
            _assign(actor, out["documents"])
            lot_out.append(out)
        today_d03 = [
            next(d for d in out["documents"] if d["type_code"] == "D03") for out in lot_out[:3]
        ]
        d03 = {"created": today_d03[0]["result"] == "created"}
        d03_id = today_d03[0]["document_id"]

        # 생산 배치마다 F02: 제조 배치라 CCP-1P·2B·3P. 배치 2는 1P 반려(S6), 3P 부적합(DOC-PS-18),
        # 2B 측정 행 없음(S6-25)
        batch_out = []
        for batch, *_ in batches:
            DevBatchPlan.objects.filter(production_batch=batch).update(touched_at=timezone.now())
            out = req.require_for_batch(actor, batch.id)
            _count(made, out["documents"])
            _assign(actor, out["documents"])
            batch_out.append({d["type_code"]: d for d in out["documents"]})
        ccp = {
            code: {"document": {"document_id": d["document_id"]},
                   "created": d["result"] == "created"}
            for code, d in batch_out[0].items()
        }  # fmt: skip
        rejected = {"document": {"document_id": batch_out[1]["CCP-1P"]["document_id"]}}
        batch3p = {"document": {"document_id": batch_out[1]["CCP-3P"]["document_id"]}}

    if not d03["created"] or not ccp["CCP-1P"]["created"]:
        # 이미 시드된 날짜, 또는 다른 날짜로 다시 실행해 배치 문서가 이미 있는 경우:
        # 상태 만들기는 건너뛴다
        return made

    # 상태: 오늘 LOT 1 D03 승인, LOT 2 D03 작성완료, LOT 3 D03 작성중(P6a — LOT마다 문서),
    # CCP-1P 작성완료, CCP-2B 결재중, CCP-3P 작성중(부적합+개선조치), 배치 2 CCP-1P 반려
    for item in today_d03[:2]:
        _inspect(actor, item["document_id"], "PASS")
        _set_info(actor, item["document_id"], {"inspector": 4})
        _complete(actor, item["document_id"])
    ids = _submit(actor, d03_id)
    wf.decide(3, ids[1], "approved")
    wf.decide(1, ids[2], "approved")

    for code, out in ccp.items():
        document_id = out["document"]["document_id"]
        section, rows = _ccp_rows(code, today)
        _add_rows(actor, document_id, section, rows)
        if code == "CCP-3P":
            _add_rows(actor, document_id, "summary", [{"item_name": "유자차", "passed_qty": 1180,
                                                       "detected_qty": 0}])  # fmt: skip
        _set_info(actor, document_id, {"inspector": 4})
    doc.create_deviation(
        4,
        ccp["CCP-3P"]["document"]["document_id"],
        {
            "description": "10:40 Fe 중앙 시편 미검출",
            "action_result": "감도 재조정 후 재점검, 적합",
            "actor_id": 4,
            "checker_ids": [2, 5],
        },
    )
    _complete(actor, ccp["CCP-1P"]["document"]["document_id"])
    _complete(actor, ccp["CCP-2B"]["document"]["document_id"])
    _submit(actor, ccp["CCP-2B"]["document"]["document_id"])

    rejected_id = rejected["document"]["document_id"]
    section, rows = _ccp_rows("CCP-1P", today)
    _add_rows(actor, rejected_id, section, rows)
    _set_info(actor, rejected_id, {"inspector": 4})
    _complete(actor, rejected_id)
    ids = _submit(actor, rejected_id)
    wf.decide(3, ids[1], "rejected", "작업 중 측정 시각 확인 필요")

    b3p = batch3p["document"]["document_id"]
    section, rows = _ccp_rows("CCP-3P", today)
    _add_rows(actor, b3p, section, [rows[0], rows[2]])
    _add_rows(
        actor, b3p, "summary", [{"item_name": "유자환", "passed_qty": 790, "detected_qty": 1}]
    )
    return made
