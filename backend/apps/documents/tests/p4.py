"""P4 테스트 준비물: 작성 요구 양식 6종 + 수불 임시 데이터.

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
    stub("production_batches", id=12, batch_number="PB-1011-01", process_type="MANUFACTURE",
         item_id=2, status="IN_PROGRESS")  # fmt: skip
    return templates


def stub(table, **values):
    """수불 테이블에 행 하나. 주어지지 않은 NOT NULL 컬럼(기본값 없음)은 형식별 빈 값으로 채운다.

    수불 실제 테이블로 바꿔도(devstock 교체, P4-S3-Q7) 컬럼 구성에 묶이지 않게 한다(V3 리허설).
    """
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
        cursor.execute(f'INSERT INTO "{table}" ({columns}) VALUES ({marks})', list(values.values()))


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
