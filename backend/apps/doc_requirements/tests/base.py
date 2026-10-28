"""REQ 테스트 준비물(s2-spec 7장).

수불·생산 값은 실제 수불 테이블(apps.inventory)에 SQL로 넣고(stub, C2), REQ는 뷰(v_doc_*)로 읽는다.
LOT 88·89(입고, 입고일 DAY), 90(제품), 91(입고 기록 없음).
배치 12(제조)·13(포장)·14(취소)·15(제조, 품목 3).
"""

from django.db import connection, transaction

from apps.admin_settings.testing import ensure_ccp_defaults
from apps.documents import services as doc
from apps.documents.models import Document, DocumentRef, DocumentTemplate
from apps.documents.seed import ensure_p4_templates, ensure_staff
from apps.documents.tests.p4 import stub

DAY = "2026-10-11"


def setup_req():
    ensure_ccp_defaults()  # P16: TransactionTestCase가 비운 기본 CCP 다시 넣기
    ensure_staff(5)
    ensure_p4_templates()
    stub("items", id=1, name="유자")
    stub("items", id=2, name="유자차", item_type="FINISHED")
    stub("items", id=3, name="유자환", item_type="FINISHED")
    for lot_id, number in ((88, "RM-1011-01"), (89, "RM-1011-02"), (91, "RM-1011-03")):
        stub(
            "lots",
            id=lot_id,
            lot_number=number,
            item_id=1,
            lot_kind="INCOMING",
            status="QUARANTINE",
            expiration_date="2027-04-30",
        )
    stub("lots", id=90, lot_number="FG-1011-01", item_id=2, lot_kind="PRODUCED", status="AVAILABLE")
    receipt(88, "고흥농협", 500, "kg")
    receipt(89, "남해유자", 300, "kg")
    for batch_id, kind, status, item in (
        (12, "MANUFACTURE", "IN_PROGRESS", 2),
        (13, "PACKAGING", "IN_PROGRESS", 2),
        (14, "MANUFACTURE", "CANCELLED", 2),
        (15, "MANUFACTURE", "IN_PROGRESS", 3),
    ):
        stub(
            "production_batches",
            id=batch_id,
            batch_number=f"PB-1011-{batch_id - 10:02d}",
            process_type=kind,
            item_id=item,
            status=status,
            manufactured_date=DAY,
        )
        stub("batch_plan", production_batch_id=batch_id, quantity_kg=1200)


def receipt(lot_id, supplier, quantity, unit="kg", day=DAY):
    """수불 입고 기록(단위는 품목 기준 단위 — C2부터 받지 않음, 호출 모양만 유지)."""
    stub("receipt", lot_id=lot_id, supplier_name=supplier, received_date=day, quantity=quantity)


def touch_lot(lot_id):
    """호출자 자기 쓰기 흉내(수불 LOT 갱신 — updated_at 트리거)."""
    with connection.cursor() as cursor:
        cursor.execute("UPDATE lots SET status = status WHERE id = %s", [lot_id])


def touch_batch(batch_id):
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE production_batches SET updated_at = updated_at WHERE id = %s", [batch_id]
        )


def in_tx(func, *args):
    with transaction.atomic():
        return func(*args)


def by_type(result):
    return {d["type_code"]: d for d in result["documents"]}


def set_status(document_id, status):
    """테스트 전용: 문서 상태만 바꾼다(작성완료 = 잠김 조건 재현)."""
    from django.utils import timezone

    done = status != "draft"
    Document.objects.filter(pk=document_id).update(
        status=status,
        completed_at=timezone.now() if done else None,
        completed_by_id=3 if done else None,
    )


def deactivate(type_code):
    DocumentTemplate.objects.filter(type_code=type_code).update(is_active=0)


def detail(document_id):
    return doc.get_document(document_id)


def cleanup_refs():
    # document_ref는 managed=False라 TransactionTestCase flush 대상이 아니다(D-059 Q6)
    DocumentRef.objects.all().delete()
