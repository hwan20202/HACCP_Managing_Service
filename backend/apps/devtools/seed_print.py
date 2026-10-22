"""P12 S5 개발 시드: 결재 칸이 찍힌 CCP 출력 확인용 (p12-ccp-policy.md, PRT-PS-01·02).

새 제조 배치 1개(노트 `dev-seed-print-YYYY-MM-DD`)를 만들고 작성 요구로 CCP-1P·2B·3P를 만든 뒤
WF 함수로 상태를 맞춘다(P14 역할 결재선 — 담당자 3, HACCP팀장 5):

- CCP-1P **승인**: 측정 4행(작업 중 1행 부적합) + 개선조치 1건 **확인됨**(확인자 5)
- CCP-2B **결재중**: 담당자 칸만 승인, 측정이 다음 날까지(작성일자 "~")
- CCP-3P(v2) **정정 중**: 승인 뒤 정정 시작, 값 하나 바꿈 + 정정 중 개선조치 1건(출력은 승인본 값)

D03 입고일 묶음(`seed_print_receiving`, p12-d03-policy.md 3장): 그날 입고 LOT 11개 —
D03 10건(승인 5·결재중·작성완료·작성중·반려·정정 중, 원료·부자재, 부적합 1건·개선조치 확인됨)
+ 문서 없는 LOT 1개.

D10 주 묶음(`seed_print_weekly`, p12-d10-policy.md): 지난주 월 정정 중(승인본 O) · 화 승인(부적합 1·
개선조치 확인됨, 용수검사일) · 수 결재중(작성자만) · 목 작성 안 함 · 금 없음 · 토 작성완료(주말 칸).

D12 주 묶음(`seed_print_weekly_d12`, p12-d12-policy.md): 지난주 월 승인(내포장) · 화 승인(외포장,
다른 승인자, 부적합 1·개선조치 확인됨) · 수 정정 중 · 목 결재중 · 금 작성중 · 토 작성 안 함
(출력 불가라 토 칸은 없음 — DP-12 W3 a).

D11 월 묶음(`seed_print_monthly`, p12-d11-policy.md): 지난달 1주 승인(특이사항) · 2주 승인(다른
승인자, 부적합 1, 특이사항) · 3주 정정 중 · 4주 작성 안 함 · (5주가 있으면) 결재중.
10줄이라 종이 2쪽(9줄 + 1줄).

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
        {"phase": "작업시작 전", "measured_at": _at(today, "08:50"), "gauss": 10500,
         "rod_cleaned": "O"},
        {"phase": "작업 중", "measured_at": _at(today, "09:50"), "gauss": 7800,
         "rod_cleaned": "O"},
        {"phase": "작업 중", "measured_at": _at(today, "10:50"), "gauss": 10400,
         "rod_cleaned": "O"},
        {"phase": "작업종료 후", "measured_at": _at(today, "17:00"), "gauss": 10200,
         "rod_cleaned": "O"},
    ])  # fmt: skip
    _set_info(OWNER, p1, {"inspector": INSPECTOR})
    deviation = doc.create_deviation(
        INSPECTOR,
        p1,
        {
            "description": "09:50 자력 7,800G(기준 8,000G 미달)",
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
        {"phase": "건조시작 전", "measured_at": _at(today, "23:00"), "temp_c": 70.1},
        {"phase": "작업 중", "measured_at": _at(today + timedelta(days=1), "00:00"),
         "temp_c": 70.4},
        {"phase": "건조종료 전", "measured_at": _at(today + timedelta(days=1), "01:00"),
         "temp_c": 69.8},
    ])  # fmt: skip
    _set_info(OWNER, p2, {"inspector": INSPECTOR})
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
    _set_info(OWNER, p3, {"inspector": INSPECTOR})
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


# ---------------------------------------------------------------- D03 입고일 묶음

GOOD = {"appearance": "양호", "packaging": "양호", "labeling": "양호", "verdict": "PASS"}
BAD = {"appearance": "양호", "packaging": "불량", "labeling": "양호", "verdict": "FAIL"}
# (품목, 매입처, 수량, 상태, 검사 값) — 입고 순서 = LOT 번호 순 = 종이 줄 순서
# D-234 r1: 성적서 유무는 시스템 계산(같은 LOT D01 파일 유무) — 시드에서 넣지 않는다
RECEIVING = [
    ("유자", "고흥농협", 500, "approved", {**GOOD}),
    ("파우치", "한빛포장", 40, "approved", {**GOOD}),
    ("유자", "남해유자영농", 320, "approved", {**BAD}),
    ("유자", "고흥농협", 450, "submitted_partial", {**GOOD}),
    ("파우치", "한빛포장", 25, "completed", {**GOOD}),
    ("유자", "거금도유자", 280, "draft", {**GOOD}),
    ("유자", "고흥농협", 300, "rejected", {**GOOD}),
    ("유자", "남해유자영농", 260, "correcting", {**GOOD}),
    ("유자", "농업회사법인 고흥유자영농조합 주식회사", 1200, "approved", {**GOOD}),
    ("파우치", "한빛포장", 60, "approved", {**GOOD}),
]


def _inspect(document_id, values):
    detail = doc.get_document(document_id)
    sections = {s["section_def"]: s for s in detail["sections"]}
    doc.update_document(
        OWNER,
        document_id,
        {
            "expected_version": detail["version"],
            "sections": {
                "update": [
                    {"section_id": sections["inspection"]["section_id"], "values": values},
                    {
                        "section_id": sections["info"]["section_id"],
                        "values": {"inspector": INSPECTOR},
                    },
                ]
            },
        },
    )


def _d03_to(document_id, state, values):
    _inspect(document_id, values)
    if values["verdict"] == "FAIL":
        deviation = doc.create_deviation(
            INSPECTOR,
            document_id,
            {
                "description": "외포장 박스 모서리 파손, 내포장 이상 없음",
                "action_result": "파손 박스 반품, 나머지 사용 — 매입처에 포장 개선 요청",
                "actor_id": INSPECTOR,
                "checker_ids": [LEADER],
            },
        )
        DeviationAction.objects.filter(pk=deviation["deviation_id"]).update(
            checked_by_id=LEADER, checked_at=timezone.now()
        )
    if state == "draft":
        return
    _complete(OWNER, document_id)
    if state == "completed":
        return
    version = doc.get_document(document_id)["version"]
    request = wf.submit(OWNER, document_id, version)["request"]
    slots = {s["role"]: s["approval_id"] for s in request["slots"]}
    if state == "rejected":
        wf.decide(LEADER, slots["leader"], "rejected", "소비기한 표기 확인 필요(시드)")
        return
    wf.decide(OWNER, slots["owner"], "approved")
    if state == "submitted_partial":
        return
    wf.decide(LEADER, slots["leader"], "approved")
    if state == "correcting":  # 승인본 = 적합, 지금 값 = 부적합(출력은 승인본)
        version = doc.get_document(document_id)["version"]
        doc.start_correction(OWNER, document_id, version, "외포장 판정 재확인(시드: 정정 중)")
        _inspect(document_id, BAD)
        doc.create_deviation(
            INSPECTOR,
            document_id,
            {"description": "정정 중 추가: 외포장 젖음 발견", "actor_id": INSPECTOR},
        )


def seed_print_receiving(day=None):
    """입고일 day(기본 오늘)에 D03 10건 + 문서 없는 LOT 1개. 반환 {created, date, documents}."""
    day = day or timezone.localdate()
    if isinstance(day, str):
        day = date.fromisoformat(day)
    ensure_staff()
    ensure_p4_templates()
    items = inventory_dev.ensure_master()
    key = f"dev-seed-print-rcv-{day.isoformat()}"
    documents = []
    for n, (item, supplier, qty, state, values) in enumerate(RECEIVING, start=1):
        raw = item == "유자"
        with transaction.atomic():
            _, out = inventory_dev.receive_lot(
                item_id=items[item],
                supplier_name=supplier,
                received_date=day,
                quantity=qty,
                staff_id=OWNER,
                expiration_date=day + timedelta(days=365) if raw else None,
                expiration_status=None if raw else "NONE",
                idempotency_key=f"{key}-{n}",
            )
        if out is None:  # 이미 만든 날(같은 요청 키)
            return {"created": False, "date": day.isoformat(), "documents": []}
        document_id = next(d["document_id"] for d in out["documents"] if d["type_code"] == "D03")
        _d03_to(document_id, state, values)
        documents.append(document_id)
    inventory_dev.receive_lot(  # 문서 없는 LOT → 종이에 줄 없음(DP-10 Q2 a)
        item_id=items["유자"],
        supplier_name="고흥농협",
        received_date=day,
        quantity=100,
        staff_id=OWNER,
        expiration_date=day + timedelta(days=365),
        idempotency_key=f"{key}-nodoc",
        documents=False,
    )
    return {"created": True, "date": day.isoformat(), "documents": documents}


# ---------------------------------------------------------------- D10 주 묶음


def _d10(day, actor=OWNER):
    with transaction.atomic():
        return doc.get_or_create_document(actor, "D10", f"D10|day:{day.isoformat()}", day, [])


def _d10_fill(document_id, value="O", inspector=INSPECTOR, checks=None):
    detail = doc.get_document(document_id)
    rows = {s["section_def"]: s for s in detail["sections"]}
    from apps.documents.seed_forms import D10 as D10_FORM

    schema = next(x for x in D10_FORM["sections"] if x["key"] == "checks")
    current = rows["checks"]["values"]
    values = {
        f["key"]: value
        for f in schema["fields"]
        if f["type"] == "select" and current.get(f["key"]) != "NA"
    }
    values.update(checks or {})
    doc.update_document(
        OWNER,
        document_id,
        {
            "expected_version": detail["version"],
            "sections": {
                "update": [
                    {"section_id": rows["info"]["section_id"], "values": {"inspector": inspector}},
                    {"section_id": rows["checks"]["section_id"], "values": values},
                ]
            },
        },
    )


def seed_print_weekly(day=None):
    """day(기본 오늘)의 지난주 D10 — 반환 {created, week_start, documents: {요일: id}}."""
    day = day or timezone.localdate()
    if isinstance(day, str):
        day = date.fromisoformat(day)
    monday = day - timedelta(days=day.weekday() + 7)
    ensure_staff()
    ensure_p4_templates()
    from apps.documents.seed import ensure_p8_templates

    ensure_p8_templates()
    first = _d10(monday)
    if not first["created"]:
        return {"created": False, "week_start": monday.isoformat(), "documents": {}}
    ids = {"월": first["document"]["document_id"]}
    for n, name in ((1, "화"), (2, "수"), (3, "목"), (5, "토")):
        ids[name] = _d10(monday + timedelta(days=n))["document"]["document_id"]

    # 월: 승인 → 정정 중(지금 값 X, 출력은 승인본 O)
    _d10_fill(ids["월"], inspector=INSPECTOR)
    _complete(OWNER, ids["월"])
    _submit_and_decide(ids["월"])
    version = doc.get_document(ids["월"])["version"]
    doc.start_correction(OWNER, ids["월"], version, "월요일 점검 재확인(시드: 정정 중)")
    _d10_fill(ids["월"], "X")
    # 화: 부적합 1 + 개선조치 확인됨 + 용수검사일, 승인(작성자 2 · 팀장 1 — 가장 최근 승인자)
    _d10_fill(
        ids["화"],
        inspector=2,
        checks={"d_clean_contact": "X", "y_water_test_date": monday.isoformat()},
    )
    deviation = doc.create_deviation(
        OWNER,  # 화 점검자는 2 — 작성 권한(P14 R07)은 역할자·점검자만, 조치자는 4 그대로
        ids["화"],
        {
            "description": "배수로 찌꺼기 남음(작업장 바닥·배수로 청소 불량)",
            "action_result": "배수로 재청소·소독 후 확인",
            "actor_id": INSPECTOR,
            "checker_ids": [LEADER],
        },
    )
    DeviationAction.objects.filter(pk=deviation["deviation_id"]).update(
        checked_by_id=LEADER, checked_at=timezone.now()
    )
    _complete(OWNER, ids["화"])
    version = doc.get_document(ids["화"])["version"]
    request = wf.submit(OWNER, ids["화"], version)["request"]
    slots = {s["role"]: s["approval_id"] for s in request["slots"]}
    wf.decide(2, slots["owner"], "approved")
    wf.decide(1, slots["leader"], "approved")
    # 수: 결재중(작성자만) — 점검자 5(가장 늦은 출력 가능 요일은 토)
    _d10_fill(ids["수"], inspector=5)
    _complete(OWNER, ids["수"])
    _submit_and_decide(ids["수"], leader=False)
    # 목: 작성 안 함
    version = doc.get_document(ids["목"])["version"]
    doc.skip_documents(
        OWNER, [{"document_id": ids["목"], "expected_version": version}], "설비 점검 휴무"
    )
    # 토: 작성완료(주말 칸), 점검자 = 이 주 마지막
    _d10_fill(ids["토"], inspector=3)
    _complete(OWNER, ids["토"])
    return {"created": True, "week_start": monday.isoformat(), "documents": ids}


# ---------------------------------------------------------------- D12 주 묶음


def _d12(day):
    with transaction.atomic():
        return doc.get_or_create_document(OWNER, "D12", f"D12|day:{day.isoformat()}", day, [])


def _d12_fill(document_id, process, value="O", checks=None):
    from apps.documents.seed_forms import D12 as D12_FORM

    detail = doc.get_document(document_id)
    rows = {s["section_def"]: s for s in detail["sections"]}
    schema = next(x for x in D12_FORM["sections"] if x["key"] == "checks")
    values = {f["key"]: value for f in schema["fields"] if f["type"] == "select"}
    values.update(checks or {})
    info = {"inspector": INSPECTOR, "process_name": process}
    doc.update_document(
        OWNER,
        document_id,
        {
            "expected_version": detail["version"],
            "sections": {
                "update": [
                    {"section_id": rows["info"]["section_id"], "values": info},
                    {"section_id": rows["checks"]["section_id"], "values": values},
                ]
            },
        },
    )


def _decide(document_id, owner=OWNER, leader=LEADER):
    version = doc.get_document(document_id)["version"]
    request = wf.submit(OWNER, document_id, version)["request"]
    slots = {s["role"]: s["approval_id"] for s in request["slots"]}
    wf.decide(owner, slots["owner"], "approved")
    if leader:
        wf.decide(leader, slots["leader"], "approved")


def seed_print_weekly_d12(day=None):
    """day(기본 오늘)의 지난주 D12 — 반환 {created, week_start, documents: {요일: id}}."""
    day = day or timezone.localdate()
    if isinstance(day, str):
        day = date.fromisoformat(day)
    monday = day - timedelta(days=day.weekday() + 7)
    ensure_staff()
    ensure_p4_templates()
    from apps.documents.seed import ensure_p8_templates

    ensure_p8_templates()
    first = _d12(monday)
    if not first["created"]:
        return {"created": False, "week_start": monday.isoformat(), "documents": {}}
    ids = {"월": first["document"]["document_id"]}
    for n, name in ((1, "화"), (2, "수"), (3, "목"), (4, "금"), (5, "토")):
        ids[name] = _d12(monday + timedelta(days=n))["document"]["document_id"]
    _d12_fill(ids["월"], "내포장")
    _complete(OWNER, ids["월"])
    _decide(ids["월"])
    _d12_fill(ids["화"], "외포장", checks={"pack_film": "X"})
    deviation = doc.create_deviation(
        INSPECTOR,
        ids["화"],
        {
            "description": "내포장재(비닐) 조각 발견",
            "action_result": "해당 구간 제품 재선별, 포장기 칼날 교체",
            "actor_id": INSPECTOR,
            "checker_ids": [LEADER],
        },
    )
    DeviationAction.objects.filter(pk=deviation["deviation_id"]).update(
        checked_by_id=LEADER, checked_at=timezone.now()
    )
    _complete(OWNER, ids["화"])
    _decide(ids["화"], owner=2, leader=1)
    _d12_fill(ids["수"], "내포장")  # 승인 → 정정 중(지금 값 X, 출력은 승인본 O)
    _complete(OWNER, ids["수"])
    _decide(ids["수"])
    version = doc.get_document(ids["수"])["version"]
    doc.start_correction(OWNER, ids["수"], version, "점검 재확인(시드: 정정 중)")
    _d12_fill(ids["수"], "내포장", checks={"worker_hair": "X"})
    _d12_fill(ids["목"], "농축")
    _complete(OWNER, ids["목"])
    _decide(ids["목"], leader=None)
    _d12_fill(ids["금"], "내포장")  # 작성중
    version = doc.get_document(ids["토"])["version"]
    doc.skip_documents(
        OWNER, [{"document_id": ids["토"], "expected_version": version}], "주말 휴무"
    )
    return {"created": True, "week_start": monday.isoformat(), "documents": ids}


# ---------------------------------------------------------------- D11 월 묶음


def _d11(monday):
    with transaction.atomic():
        return doc.get_or_create_document(
            OWNER, "D11", f"D11|week:{monday.isoformat()}", monday, []
        )


def _d11_fill(document_id, monday, value="O", remark=None, checks=None):
    from apps.documents.seed_forms import D11 as D11_FORM

    detail = doc.get_document(document_id)
    rows = {s["section_def"]: s for s in detail["sections"]}
    schema = next(x for x in D11_FORM["sections"] if x["key"] == "checks")
    values = {f["key"]: value for f in schema["fields"] if f["type"] == "select"}
    values.update(checks or {})
    info = {"inspector": INSPECTOR, "checked_on": (monday + timedelta(days=2)).isoformat()}
    if remark:
        info["remark"] = remark
    doc.update_document(
        OWNER,
        document_id,
        {
            "expected_version": detail["version"],
            "sections": {
                "update": [
                    {"section_id": rows["info"]["section_id"], "values": info},
                    {"section_id": rows["checks"]["section_id"], "values": values},
                ]
            },
        },
    )


def seed_print_monthly(day=None):
    """day(기본 오늘)의 지난달 D11 — 반환 {created, month, documents: {주: id}}."""
    from apps.document_workflow.printing import _mondays

    day = day or timezone.localdate()
    if isinstance(day, str):
        day = date.fromisoformat(day)
    last = day.replace(day=1) - timedelta(days=1)
    mondays = _mondays(last.year, last.month)
    ensure_staff()
    ensure_p4_templates()
    from apps.documents.seed import ensure_p8_templates

    ensure_p8_templates()
    first = _d11(mondays[0])
    month = f"{last.year}-{last.month:02d}"
    if not first["created"]:
        return {"created": False, "month": month, "documents": {}}
    ids = {1: first["document"]["document_id"]}
    for n, monday in enumerate(mondays[1:], start=2):
        ids[n] = _d11(monday)["document"]["document_id"]
    _d11_fill(ids[1], mondays[0], remark="포충등 2번 램프 밝기 저하 — 다음 주 교체 예정")
    _complete(OWNER, ids[1])
    _decide(ids[1])
    _d11_fill(ids[2], mondays[1], checks={"fly_trap_lamp": "X"}, remark="포충등 2번 램프 교체 완료")
    doc.create_deviation(
        INSPECTOR, ids[2], {"description": "포충등 2번 점등 안 됨", "actor_id": INSPECTOR}
    )
    _complete(OWNER, ids[2])
    _decide(ids[2], owner=2, leader=1)
    _d11_fill(ids[3], mondays[2])  # 승인 → 정정 중(지금 값 X, 출력은 승인본 O)
    _complete(OWNER, ids[3])
    _decide(ids[3])
    version = doc.get_document(ids[3])["version"]
    doc.start_correction(OWNER, ids[3], version, "점검일 재확인(시드: 정정 중)")
    _d11_fill(ids[3], mondays[2], checks={"food_trace": "X"})
    version = doc.get_document(ids[4])["version"]
    doc.skip_documents(
        OWNER, [{"document_id": ids[4], "expected_version": version}], "외부 방역 주간"
    )
    if 5 in ids:
        _d11_fill(ids[5], mondays[4])
        _complete(OWNER, ids[5])
        _decide(ids[5], leader=None)
    return {"created": True, "month": month, "documents": ids}
