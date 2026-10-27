"""P15 S5 개발 전용 생산일지 데이터 (개발 콘솔·개발 시드·화면 확인).

수불 공개 서비스(입고 `register_receipt`, 생산 `create_batch`·`start_batch`·`add_usage`·
`add_output`·`cancel_batch`)로 배치·투입·산출을 만든다 — 수불 코드는 고치지 않는다.
BOM은 수불 QA 시드처럼 모델로 직접 만든다(개발 품목, 대체 원료 1개).
생산 시작(`start_batch`)의 수불 훅이 작성 요구(REQ-F02)를 불러 CCP 일지 3개 + 생산일지가 생긴다
(생산일지 양식이 설치돼 있을 때 — 여기서 설치한다).
운영 코드는 이 모듈을 import하지 않는다(개발 설정에서만).
"""

import datetime
import uuid
from decimal import Decimal

from django.db import transaction

from apps.doc_requirements import services as req
from apps.documents import seed as doc_seed
from apps.inventory.models import Bom, BomLine, BomLineAlternative, Item, ProductionBatch
from apps.inventory.production import (
    add_output,
    add_usage,
    cancel_batch,
    create_batch,
    start_batch,
)
from apps.production_log.seed import seed_production_master

from . import inventory_dev

# (품목 코드, LOT 약어, 구분, 이름, 단위, 원산지, 재고 관리)
ITEMS = [
    ("1915001", "PNZ", "RAW", "녹용(뉴질랜드)", "kg", "뉴질랜드", True),
    ("1915002", "PRU", "RAW", "녹용(러시아)", "g", "러시아", True),
    ("1915003", "PHN", "RAW", "사양벌꿀", "kg", "국산", True),
    ("1915004", "PRB", "RAW", "홍국균", "kg", "국산", True),
    ("1915009", None, "RAW", "정제수", "kg", None, False),
]
PRODUCT = ("3915001", None, "SEMI", "녹용 효력환(개발)", "kg", None, True)
FOOD_TYPE, REPORT_NO = "기타가공품", "20260012345-001"
# BOM(기준 100 kg): 녹용 9 kg(대체 녹용(러시아) g)·정제수 90 kg(재고 비관리)·벌꿀·홍국균
BOM_LINES = [
    ("1915001", "9", "1915002"),
    ("1915009", "90", None),
    ("1915003", "0.9", None),
    ("1915004", "0.1", None),
]
SUPPLIER = "개발 생산일지 공급처"
INSPECTION = {"appearance": "양호", "packaging": "양호", "labeling": "양호", "verdict": "PASS"}
SCENARIOS = ("started", "used", "partial", "cancelled", "nobom")
# 품목 정보(유형·보고번호)·BOM 없는 반제품(PLG-PS-05)
BARE = ("3915002", None, "SEMI", "녹용 원액(개발·정보 없음)", "kg", None, True)


def _item(entry, extra=None):
    code, short, kind, name, unit, origin, stock = entry
    item, _ = Item.objects.get_or_create(
        item_code=code,
        defaults={
            "short_code": short,
            "item_type_id": kind,
            "name": name,
            "base_unit": unit,
            "origin_country": origin,
            "is_stock_managed": stock,
            **(extra or {}),
        },
    )
    return item


def ensure_master(staff_id):
    """품목 6개·BOM 1개·생산일지 양식·공정 기준정보(개발 시드). 반환 {product, bom, items}."""
    doc_seed.ensure_p4_templates()
    doc_seed.ensure_p15_templates()
    seed_production_master(staff_id)
    items = {e[0]: _item(e) for e in ITEMS}
    product = _item(PRODUCT, {"food_type": FOOD_TYPE, "manufacturing_report_number": REPORT_NO})
    bom = Bom.objects.filter(item=product, notes="DEV_PRODLOG").first()
    if bom is None:
        bom = Bom.objects.create(
            item=product,
            version=(Bom.objects.filter(item=product).count() + 1),
            base_quantity_e6=100_000_000,
            effective_from=datetime.date(2026, 1, 1),
            created_by_id=staff_id,
            notes="DEV_PRODLOG",
        )
        for no, (code, qty, alt) in enumerate(BOM_LINES, 1):
            line = BomLine.objects.create(
                bom=bom,
                line_no=no,
                component_item=items[code],
                quantity_e6=int(Decimal(qty) * 1_000_000),
            )
            if alt:
                BomLineAlternative.objects.create(bom_line=line, item=items[alt])
    return {"product": product, "bom": bom, "items": items}


def _receive(item, quantity, staff_id, day):
    return inventory_dev.receive(
        item_id=item.pk,
        supplier_name=SUPPLIER,
        received_date=day,
        quantity=quantity,
        staff_id=staff_id,
        expiration_date=day + datetime.timedelta(days=365),
        inspection=INSPECTION,
        idempotency_key=f"dev-prodlog-{uuid.uuid4().hex}",
    )


def _line(bom, item):
    return BomLine.objects.get(bom=bom, component_item=item).pk


def make(scenario, staff_id, day=None):
    """개발 생산일지 배치 1개. 반환 {batch_id, batch_number, documents, prod_log_id, scenario}.

    started   생산 시작 직후(투입 0)
    used      녹용 6 kg + 녹용(러시아) 3000 g(대체·g 환산)·벌꿀·홍국균 투입, 산출 98 kg
    partial   녹용 9 kg만(나머지 미투입)
    cancelled 생산 시작 뒤 취소(투입 없음)
    nobom     품목 정보(유형·보고번호)·BOM 없는 배치 — 수불 생산 시작은 BOM이 필요해 개발 전용 배치
              (inventory_dev.make_batch, 직접 INSERT) + 작성 요구(REQ-F02)
    """
    if scenario not in SCENARIOS:
        raise ValueError(f"scenario: {SCENARIOS}")
    day = day or datetime.date.today()
    if scenario == "nobom":
        with transaction.atomic():
            ensure_master(staff_id)
            bare = _item(BARE)
            batch_id = inventory_dev.make_batch(
                item_id=bare.pk,
                process_type="MANUFACTURE",
                manufactured_date=day,
                quantity_kg=50,
                staff_id=staff_id,
                notes=f"DEV_PRODLOG nobom {uuid.uuid4().hex[:6]}",
            )
            req.require_for_batch(staff_id, batch_id)
        return _result(scenario, batch_id)
    with transaction.atomic():
        master = ensure_master(staff_id)
        items, bom, product = master["items"], master["bom"], master["product"]
        # 생산 시작 조건(material_readiness): 계획량만큼 쓸 수 있는 재고
        for code, qty in (
            ("1915001", "20"),
            ("1915002", "5000"),
            ("1915003", "2"),
            ("1915004", "1"),
        ):
            _receive(items[code], qty, staff_id, day)
        batch = create_batch(
            item_id=product.pk,
            staff_id=staff_id,
            planned_quantity=Decimal("100"),
            bom_id=bom.pk,
            notes=f"DEV_PRODLOG {scenario} {uuid.uuid4().hex[:6]}",
        )
        start_batch(batch_id=batch.pk, staff_id=staff_id, manufactured_date=day)
    lots = {}
    if scenario in ("used", "partial"):
        from apps.inventory.models import Lot

        for code in ("1915001", "1915002", "1915003", "1915004"):
            lots[code] = (
                Lot.objects.filter(item=items[code], status="AVAILABLE").order_by("-id").first().pk
            )
        uses = [("1915001", "6" if scenario == "used" else "9", "1915001")]
        if scenario == "used":
            uses += [
                ("1915002", "3000", "1915001"),
                ("1915003", "0.9", "1915003"),
                ("1915004", "0.1", "1915004"),
            ]
        for code, qty, line_code in uses:
            add_usage(
                batch_id=batch.pk,
                lot_id=lots[code],
                quantity=Decimal(qty),
                staff_id=staff_id,
                idempotency_key=f"dev-prodlog-use-{uuid.uuid4().hex}",
                bom_line_id=_line(bom, items[line_code]),
            )
        if scenario == "used":
            add_output(
                batch_id=batch.pk,
                quantity=Decimal("98"),
                staff_id=staff_id,
                idempotency_key=f"dev-prodlog-out-{uuid.uuid4().hex}",
            )
    if scenario == "cancelled":
        cancel_batch(batch_id=batch.pk, staff_id=staff_id, reason="개발: 취소 배치")
    return _result(scenario, batch.pk)


def _result(scenario, batch_id):
    docs = req.docs_for_batch(batch_id)["documents"]
    prod_log = next((d["document_id"] for d in docs if d["type_code"] == "PROD-LOG"), None)
    batch = ProductionBatch.objects.get(pk=batch_id)
    return {
        "scenario": scenario,
        "batch_id": batch.pk,
        "batch_number": batch.batch_number,
        "documents": [{"type_code": d["type_code"], "document_id": d["document_id"]} for d in docs],
        "prod_log_id": prod_log,
    }
