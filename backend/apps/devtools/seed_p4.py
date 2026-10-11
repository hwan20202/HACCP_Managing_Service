"""P4 개발·사용 테스트용 가상 데이터 (p4-s1-screens.md 7장).

- 수불 임시 데이터(apps.devstock): 품목 4, 입고 LOT 5, 생산 배치 2. 개발·테스트 설정에서만.
- 작성 요구 문서는 REQ가 아직 없으므로(P5) DOC의 N1·N2를 직접 불러 만든다. record_key 형식은
  req-s2-spec.md와 같다. 결재 상태는 WF 함수로 만든다(문서·회차 상태 짝 유지).
- 파일(D01·D02 첨부)은 스프린트 3(D-058)이라 만들지 않는다. D01·D02는 작성중으로 남는다.
"""

from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from apps.devstock.models import Item, Lot, ProductionBatch
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
        batches.append((batch, item, qty))
    return lots, batches


def _lot_values(lot, item, supplier, today):
    return {
        "lot_number": lot.lot_number,
        "item_name": item,
        "supplier_name": supplier,
        "received_date": today.isoformat(),
    }


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


def _complete(actor, document_id):
    version = doc.get_document(document_id)["version"]
    return doc.complete_document(actor, document_id, version)


def _submit(actor, document_id):
    version = doc.get_document(document_id)["version"]
    out = wf.submit(actor, document_id, version, [dict(s) for s in SLOTS])
    return {s["slot_no"]: s["approval_id"] for s in out["request"]["slots"]}


def seed_p4(today=None):
    """시드를 만든다. 같은 날짜로 다시 부르면 이미 있는 문서는 그대로 둔다(N1·N2 멱등)."""
    today = today or timezone.localdate()
    if isinstance(today, str):
        today = date.fromisoformat(today)
    ensure_staff()
    ensure_p4_templates()
    lots, batches = ensure_stock(today)
    made = {"documents": 0, "lot_rows": 0}
    actor = 3

    with transaction.atomic():
        # D01·D02: 입고 LOT마다 1건(작성중). D03: 그날 문서 1건에 LOT 3행.
        d03 = doc.get_or_create_document(
            actor, "D03", f"D03|date:{today.isoformat()}", today, [], assignee_id=2
        )
        d03_id = d03["document"]["document_id"]
        made["documents"] += int(d03["created"])
        for lot, item, supplier, kind, qty in lots[:3]:
            ref = [{"lot_id": lot.id, "label": lot.lot_number}]
            base = _lot_values(lot, item, supplier, today)
            for code in ("D01", "D02"):
                out = doc.get_or_create_document(
                    actor, code, f"{code}|lot:{lot.id}", today, ref, values={"info": base}
                )
                made["documents"] += int(out["created"])
            row = {
                **base,
                "material_kind": kind,
                "quantity": qty,
                "expiration_date": lot.expiration_date.isoformat(),
            }
            out = doc.add_ref_row(actor, d03_id, "lots", row, ref, "lot_id")
            made["lot_rows"] += int(out["created"])

        # CCP: 배치 1 × 1P·2B·3P, 배치 2 × 1P
        ccp = {}
        for batch, item, qty in batches[:1]:
            for code, process in (("CCP-1P", "1P"), ("CCP-2B", "2B"), ("CCP-3P", "3P")):
                out = doc.get_or_create_document(
                    actor,
                    code,
                    f"{code}|batch:{batch.id}",
                    today,
                    [{"production_batch_id": batch.id, "process_code": process,
                      "label": batch.batch_number}],
                    values={"info": {"item_name": item, "batch_qty_kg": qty}},
                    assignee_id=2,
                )  # fmt: skip
                ccp[code] = out
                made["documents"] += int(out["created"])
        batch, item, qty = batches[1]
        rejected = doc.get_or_create_document(
            actor,
            "CCP-1P",
            f"CCP-1P|batch:{batch.id}",
            today,
            [{"production_batch_id": batch.id, "process_code": "1P", "label": batch.batch_number}],
            values={"info": {"item_name": item, "batch_qty_kg": qty}},
            assignee_id=2,
        )
        made["documents"] += int(rejected["created"])

    if not d03["created"]:
        return made  # 이미 시드된 날짜: 상태 만들기는 건너뛴다

    # 상태: D03 승인, CCP-1P 작성완료, CCP-2B 결재중, CCP-3P 작성중(부적합+개선조치),
    # 배치 2 CCP-1P 반려
    detail = doc.get_document(d03_id)
    updates = [
        {
            "section_id": s["section_id"],
            "values": {"appearance": "양호", "packaging": "양호", "labeling": "양호",
                       "verdict": "PASS"},
        }
        for s in detail["sections"]
        if s["section_def"] == "lots"
    ]  # fmt: skip
    doc.update_document(
        actor, d03_id, {"expected_version": detail["version"], "sections": {"update": updates}}
    )
    _set_info(actor, d03_id, {"inspector": 4})
    _complete(actor, d03_id)
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
    return made
