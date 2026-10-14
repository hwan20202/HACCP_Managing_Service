"""P4 테스트 준비물: 작성 요구 양식 6종 + 수불 데이터(실제 수불 테이블에 SQL, C2).

수불 데이터는 SQL로 직접 넣는다(문서 도메인은 수불 앱을 import하지 않는다, NFR-12).

LOT 88·89·90(입고), 생산 배치 12, 품목 1·2. 값은 모두 가상이다.
"""

from django.db import connection, transaction

from apps.documents import services
from apps.documents.models import Document, DocumentFile, File
from apps.documents.seed import _ensure, ensure_p4_templates, ensure_staff
from apps.documents.seed_forms import D03 as D03_V1

# N2(행 단위 작성 요구) 시험용 양식 — D03 v1 정의를 빌려 씀(P6a: D03은 LOT 문서)
ROWS = "TEST-LOT-ROWS"

DAY = "2026-10-11"


def setup_p4():
    ensure_staff(5)
    templates = ensure_p4_templates()
    templates[ROWS] = _ensure([(ROWS, 1, "행 단위 시험 양식", D03_V1, True)])[(ROWS, 1)]
    stub("items", id=1, name="유자")
    stub("items", id=2, name="유자차")
    for lot_id in (88, 89, 90):
        stub("lots", id=lot_id, lot_number=f"RM-1011-0{lot_id - 87}", item_id=1,
             lot_kind="INCOMING", status="QUARANTINE")  # fmt: skip
        # P6 EFF: D03 작성완료 판정은 수불 판정 함수에 전달 — 입고 기록 필요
        stub("receipt", lot_id=lot_id, supplier_name="고흥농협", received_date=DAY, quantity=500)
    stub("production_batches", id=12, batch_number="PB-1011-01", process_type="MANUFACTURE",
         item_id=2, status="IN_PROGRESS")  # fmt: skip
    return templates


def stub(table, **values):
    """수불 테이블에 행 하나(테스트 전용, SQL). C2부터 실제 수불 테이블(apps.inventory)이라
    수불 규칙(FK·CHECK·트리거)을 지킨다.

    - items: 지정 안 한 품목 코드(T000001…)·구분(RAW)·기준 단위(kg)를 채운다
    - production_batches: 책임자 staff 1, 취소면 취소 시각·사유를 채운다
    - "receipt"(가상 이름): 수불 입고 — 공급처(이름으로 찾거나 만듦), 입고 이동(RECEIPT)·입고 기록
      (incoming_receipts). 구분·단위·원산지는 품목 값이라 받지 않는다
    - "batch_plan"(가상 이름): 배치의 계획 수량(planned_quantity_e6 = quantity_kg × 10⁶,
      품목 단위 kg)
    그 밖의 NOT NULL 컬럼(기본값 없음)은 형식별 빈 값으로 채운다.
    """
    if table == "receipt":
        return _receipt(**values)
    if table == "batch_plan":
        return _sql(
            "UPDATE production_batches SET planned_quantity_e6 = %s WHERE id = %s",
            [int(round(values["quantity_kg"] * 1_000_000)), values["production_batch_id"]],
        )
    values = {**_DEFAULTS.get(table, lambda v: {})(values), **values}
    with connection.cursor() as cursor:
        cursor.execute(f'PRAGMA table_info("{table}")')
        for _, name, type_, notnull, default, pk in cursor.fetchall():
            if name in values or pk or not notnull or default is not None:
                continue
            kind = (type_ or "").lower()
            if "date" in kind:
                values[name] = "2026-01-01"
            elif any(k in kind for k in ("int", "real", "decimal", "numeric", "bool")):
                values[name] = 0
            else:
                values[name] = ""
        columns = ", ".join(f'"{k}"' for k in values)
        marks = ", ".join(["%s"] * len(values))
        # TransactionTestCase: 수불 테이블은 managed=False라 flush되지 않고 이동·배치는
        # 삭제 금지 트리거가 있다 → 같은 id 행이 이미 있으면 그대로 쓴다(M6)
        insert = f'INSERT OR IGNORE INTO "{table}" ({columns}) VALUES ({marks})'
        if table == "production_batches" and values.get("process_type") == "PACKAGING":
            _legacy_packaging(cursor, insert, list(values.values()))
        else:
            cursor.execute(insert, list(values.values()))


# 수불 0006(MVP 벌크 범위): 새 포장배치는 트리거가 막고, 0006 전에 만든 포장배치만 남는다.
# 포장배치 = CCP 문서 없음(rules.CCP_PROCESSES)을 시험하려고 그 "예전 행"을 흉내 낸다 — 테스트 전용.
LEGACY_PACKAGING_TRIGGER = "trg_batches_no_packaging"


def _legacy_packaging(cursor, insert, params):
    cursor.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'trigger' AND name = %s",
        [LEGACY_PACKAGING_TRIGGER],
    )
    row = cursor.fetchone()
    if row is None:  # 0006 전 스키마
        cursor.execute(insert, params)
        return
    cursor.execute(f'DROP TRIGGER "{LEGACY_PACKAGING_TRIGGER}"')
    try:
        cursor.execute(insert, params)
    finally:
        cursor.execute(row[0])


def _batch_defaults(values):
    extra = {"staff_id": 1}
    if values.get("status") == "CANCELLED":
        extra.update(cancelled_at="2026-10-11 18:00:00", cancel_reason="테스트 취소")
    return extra


_DEFAULTS = {
    "items": lambda v: {
        "item_code": f"T{v['id']:06d}",
        "short_code": f"X{v['id']:02d}",  # LOT 약어(수불 입고 LOT 번호 규칙)
        "item_type": "RAW",
        "base_unit": "kg",
    },
    "production_batches": _batch_defaults,
    # 수불 0007: 소비기한 유무(KNOWN 날짜 있음 / NONE 없음). 원료 입고 LOT은 UNKNOWN(미확인) 불가
    "lots": lambda v: {"expiration_status": "KNOWN" if v.get("expiration_date") else "NONE"},
}


def _sql(statement, params=()):
    with connection.cursor() as cursor:
        cursor.execute(statement, params)
        return cursor.lastrowid


def _receipt(lot_id, supplier_name, received_date, quantity, unit="kg", **_ignored):
    """수불 입고 기록(SQL). 입고 이동을 먼저 넣고(재고 트리거) 입고 기록이 그 이동을 가리킨다."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT id FROM incoming_receipts WHERE lot_id = %s", [lot_id])
        existing = cursor.fetchone()
    if existing:  # TransactionTestCase에서 앞 테스트가 넣은 입고(M6)
        return existing[0]
    with connection.cursor() as cursor:
        cursor.execute("SELECT id FROM suppliers WHERE name = %s", [supplier_name])
        row = cursor.fetchone()
    supplier_id = (
        row[0]
        if row
        else _sql(
            "INSERT INTO suppliers (supplier_code, name) VALUES (%s, %s)",
            [f"TS-{supplier_name}", supplier_name],
        )
    )
    quantity_e6 = int(round(quantity * 1_000_000))
    movement_id = _sql(
        "INSERT INTO stock_movements (lot_id, movement_type_code, quantity_e6, staff_id,"
        " occurred_at, idempotency_key) VALUES (%s, 'RECEIPT', %s, 1, %s, %s)",
        [lot_id, quantity_e6, f"{received_date} 09:00:00", f"test-receipt-{lot_id}"],
    )
    return _sql(
        "INSERT INTO incoming_receipts (lot_id, supplier_id, received_date, quantity_e6, staff_id,"
        " stock_movement_id) VALUES (%s, %s, %s, %s, 1, %s)",
        [lot_id, supplier_id, received_date, quantity_e6, movement_id],
    )


def lot_ref(lot_id):
    return [{"lot_id": lot_id, "label": f"RM-1011-0{lot_id - 87}"}]


def batch_ref(process):
    return [{"production_batch_id": 12, "process_code": process, "label": "PB-1011-01"}]


def goc(code, record_key, refs, values=None, actor=3):
    with transaction.atomic():
        return services.get_or_create_document(actor, code, record_key, DAY, refs, values=values)


def new_d01(lot_id=88):
    return goc("D01", f"D01|lot:{lot_id}", lot_ref(lot_id), {"info": {"item_name": "유자"}})


D03_INFO = {
    "lot_number": "RM-1011-01",
    "received_date": DAY,
    "supplier_name": "고흥농협",
    "material_kind": "원료",
    "item_name": "유자",
    "quantity": "500kg",
}
PASS_INSPECTION = {"appearance": "양호", "packaging": "양호", "labeling": "양호", "verdict": "PASS"}


def new_d03(lot_id=88):
    """D03 v2 — LOT마다 문서 1건(P6a, D-084)."""
    info = {**D03_INFO, "lot_number": f"RM-1011-0{lot_id - 87}"}
    return goc("D03", f"D03|lot:{lot_id}", lot_ref(lot_id), {"info": info})


def inspect(document_id, values=None):
    row = rows_of(document_id, "inspection")[0]
    values = values or PASS_INSPECTION
    return patch(document_id, {"update": [{"section_id": row["section_id"], "values": values}]})


def new_rows_doc():
    """N2 시험용 행 단위 문서(하루 1건)."""
    return goc(ROWS, f"{ROWS}|date:{DAY}", [])


def add_lot_row(document_id, lot_id, values=None):
    row = {"lot_number": f"RM-1011-0{lot_id - 87}", "item_name": "유자", **(values or {})}
    with transaction.atomic():
        return services.add_ref_row(3, document_id, "lots", row, lot_ref(lot_id), "lot_id")


def new_ccp(code="CCP-1P", process="1P"):
    return goc(
        code,
        f"{code}|batch:12",
        batch_ref(process),
        {"info": {"item_name": "유자차", "batch_qty_kg": 1200}},
    )


def version_of(document_id):
    return Document.objects.values_list("version", flat=True).get(pk=document_id)


def patch(document_id, sections=None, document=None, actor=3):
    body = {"expected_version": version_of(document_id)}
    if sections:
        body["sections"] = sections
    if document:
        body["document"] = document
    return services.update_document(actor, document_id, body)


def rows_of(document_id, section_def):
    detail = services.get_document(document_id)
    return [s for s in detail["sections"] if s["section_def"] == section_def]


def set_info(document_id, values):
    info = rows_of(document_id, "info")[0]
    return patch(document_id, {"update": [{"section_id": info["section_id"], "values": values}]})


def at(hm, day=DAY):
    return f"{day}T{hm}"


def ccp1p_rows(*specs):
    """specs: (phase, HH:MM, gauss, rod)."""
    return [
        {"phase": p, "measured_at": at(t), "gauss": g, "rod_cleaned": r} for p, t, g, r in specs
    ]


GOOD_1P = (
    ("작업시작 전", "08:50", 10500, "O"),
    ("작업 중", "09:50", 10300, "O"),
    ("작업종료 후", "17:00", 10200, "O"),
)


def filled_ccp1p(specs=GOOD_1P):
    """점검자·측정 행을 채운 CCP-1P draft. 반환: document_id."""
    document_id = new_ccp()["document"]["document_id"]
    set_info(document_id, {"inspector": 4})
    patch(
        document_id,
        {"add": [{"section_def": "rounds", "values": v} for v in ccp1p_rows(*specs)]},
    )
    return document_id


def complete(document_id, actor=3):
    return services.complete_document(actor, document_id, version_of(document_id))


def attach_file(document_id, name="coa.pdf"):
    """파일 기능(스프린트 3, D-058) 전이라 file·document_file 행을 ORM으로 직접 넣는다."""
    from django.utils import timezone

    now = timezone.now()
    file = File.objects.create(
        storage_path=f"test/{document_id}/{name}",
        original_name=name,
        mime_type="application/pdf",
        size_bytes=1024,
        sha256="0" * 64,
        uploaded_by_id=3,
        uploaded_at=now,
    )
    DocumentFile.objects.create(document_id=document_id, file=file, linked_by_id=3, linked_at=now)
    return file
