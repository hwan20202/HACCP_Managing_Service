"""S4b 생산일지 테스트 준비물.

수불 행은 SQL로 직접 넣는다(PLG 테스트는 apps.inventory를 import하지 않음 — 경계 TC-27).
트리거 규칙을 지킨다: 배치 BOM = 배치 품목, 투입 = 같은 LOT·수량의 PRODUCTION_USE 이동,
재고 비관리 품목은 LOT 없음.
"""

from django.db import connection, transaction
from django.test import TestCase

from apps.admin_settings.testing import ensure_ccp_defaults
from apps.doc_requirements import services as req
from apps.documents import seed as doc_seed
from apps.documents import services as doc
from apps.production_log import services
from apps.staff import services as staff_services

TODAY = "2026-10-26"


def lines_unavailable():
    """0009 BOM 줄 뷰를 못 읽는 상황: 배치 상태는 읽히고 `lines`만 None(REQ-PLS-02 r2)."""
    from unittest import mock

    original = req.production_batch_state

    def state(batch_id, with_lines=False):
        out = original(batch_id)
        return {**out, "lines": None} if with_lines else out

    return mock.patch.object(req, "production_batch_state", side_effect=state)


def sql(statement, params=()):
    with connection.cursor() as cursor:
        cursor.execute(statement, list(params))
        return cursor.lastrowid


class Inventory:
    """배치 1개: 품목 100(kg), BOM 4줄(녹용 9%·정제수 90%·벌꿀 0.9%·홍국균 EA)."""

    def __init__(self, item_id=100, batch_id=400, item_code="P15T100"):
        self.item_id, self.batch_id = item_id, batch_id
        self.mv = batch_id * 100
        # 수불 기준 데이터(마이그레이션 데이터) — TransactionTestCase가 표를 비운 뒤에도 쓰도록
        sql(
            "INSERT OR IGNORE INTO item_types (code,name,code_prefix,sort_order)"
            " VALUES ('RAW','원료','1',1),('SEMI','반제품','3',3)"
        )
        sql(
            "INSERT OR IGNORE INTO stock_movement_types (code,name,direction)"
            " VALUES ('RECEIPT','입고',1),('PRODUCTION_USE','생산 투입',-1)"
        )
        sql(
            "INSERT INTO items (id,item_type,item_code,name,base_unit,origin_country,"
            "is_stock_managed) VALUES (101,'RAW','P15T001','사양벌꿀','kg','국산',1),"
            "(102,'RAW','P15T098','정제수','kg',NULL,0),(103,'RAW','P15T002','녹용','kg','뉴질랜드',1),"
            "(104,'RAW','P15T099','녹용(러시아)','g','러시아',1),(105,'RAW','P15T003','홍국균','EA',NULL,1)"
        )
        sql(
            "INSERT INTO items (id,item_type,item_code,name,base_unit,food_type,"
            "manufacturing_report_number) VALUES"
            " (%s,'SEMI',%s,'한동 효력환','kg','기타가공품','2024-123')",
            [item_id, item_code],
        )
        self.bom = sql(
            "INSERT INTO boms (item_id,version,base_quantity_e6,effective_from)"
            " VALUES (%s,%s,1000000,%s)",
            [item_id, batch_id, "2026-10-01"],
        )
        self.lines = {}
        for no, item, qty in ((1, 103, 90000), (2, 102, 900000), (3, 101, 9000), (4, 105, 1000000)):
            self.lines[item] = sql(
                "INSERT INTO bom_lines (bom_id,line_no,component_item_id,quantity_e6)"
                " VALUES (%s,%s,%s,%s)",
                [self.bom, no, item, qty],
            )
        sql(
            "INSERT INTO production_batches (id,batch_number,process_type,item_id,bom_id,status,"
            "planned_quantity_e6,manufactured_date,staff_id) VALUES (%s,%s,'MANUFACTURE',%s,%s,"
            "'IN_PROGRESS',100000000,%s,1)",
            [batch_id, f"PB-{batch_id}", item_id, self.bom, TODAY],
        )

    def use(self, item, qty_e6, day=TODAY, line=None):
        lot = sql(
            "INSERT INTO lots (lot_number,item_id,lot_kind,status)"
            " VALUES (%s,%s,'INCOMING','AVAILABLE')",
            [f"L{self.mv}", item],
        )
        sql(
            "INSERT INTO stock_movements (id,lot_id,movement_type_code,quantity_e6,staff_id,"
            "occurred_at,idempotency_key) VALUES (%s,%s,'RECEIPT',%s,1,%s,%s)",
            [self.mv, lot, qty_e6 * 10, f"{day} 08:00:00", f"r{self.mv}"],
        )
        sql(
            "INSERT INTO stock_movements (id,lot_id,movement_type_code,quantity_e6,staff_id,"
            "occurred_at,idempotency_key) VALUES (%s,%s,'PRODUCTION_USE',%s,1,%s,%s)",
            [self.mv + 1, lot, qty_e6, f"{day} 09:00:00", f"u{self.mv}"],
        )
        sql(
            "INSERT INTO production_material_usages (batch_id,lot_id,quantity_e6,stock_movement_id,"
            "bom_line_id) VALUES (%s,%s,%s,%s,%s)",
            [self.batch_id, lot, qty_e6, self.mv + 1, line],
        )
        self.mv += 2

    def cancel(self):
        sql(
            "UPDATE production_batches SET status='CANCELLED', cancelled_at=%s,"
            " cancel_reason='테스트' WHERE id=%s",
            [f"{TODAY} 12:00:00", self.batch_id],
        )


class ProdLogTestCase(TestCase):
    """양식 P4(CCP)·P15(PROD-LOG) 설치, 직원 1~5, 배치 400 + 생산 시작(REQ-F02)."""

    install_prod_log = True

    @classmethod
    def setUpTestData(cls):
        staff_services.ensure_dev_staff(range(1, 6))
        doc_seed.ensure_p4_templates()
        ensure_ccp_defaults()  # P16: 생산 시작 CCP 공정 = 관리 설정 기본 CCP
        if cls.install_prod_log:
            doc_seed.ensure_p15_templates()
        cls.inv = Inventory()
        with transaction.atomic():
            cls.started = req.require_for_batch(1, cls.inv.batch_id)
        cls.log_id = next(
            (d["document_id"] for d in cls.started["documents"] if d["type_code"] == "PROD-LOG"),
            None,
        )

    def ccp_id(self, kind):
        return next(d["document_id"] for d in self.started["documents"] if d["type_code"] == kind)

    def detail(self, document_id=None):
        return doc.get_document(document_id or self.log_id)

    def section_id(self, section_def, document_id=None):
        return next(
            r["section_id"]
            for r in self.detail(document_id)["sections"]
            if r["section_def"] == section_def
        )

    def patch(self, sections, actor=1, document_id=None):
        d = self.detail(document_id)
        return doc.update_document(
            actor, d["document_id"], {"expected_version": d["version"], "sections": sections}
        )

    def add_steps(self, *rows, actor=1):
        return self.patch({"add": [{"section_def": "steps", "values": v} for v in rows]}, actor)

    def fill_info(self, actor=1):
        return self.patch(
            {
                "update": [
                    {
                        "section_id": self.section_id("info"),
                        "values": {
                            "pre_label": "적합",
                            "pre_clean": "적합",
                            "pre_lot": "적합",
                            "inspector": 1,
                        },
                    }
                ]
            },
            actor,
        )

    def complete(self, actor=1):
        d = self.detail()
        return doc.complete_document(actor, self.log_id, d["version"])

    def reopen(self, actor=1):
        d = self.detail()
        return doc.reopen_document(actor, self.log_id, d["version"])

    def builtin(self, kind):
        from apps.production_log.models import Process

        return Process.objects.get(kind=kind).pk

    def gen(self, name="분쇄", mode="JUDGE", **extra):
        with transaction.atomic():
            return services.create_process(1, {"name": name, "mode": mode, **extra})["process_id"]

    def assertDocError(self, code, fn, *args, **kwargs):
        from apps.core.http import ApiError

        try:
            fn(*args, **kwargs)
        except ApiError as error:
            self.assertEqual(error.code, code, error.details)
            return error
        self.fail(f"{code} 예외가 나야 합니다")


def full_step(kind, process_id, **extra):
    """작성완료 필수 칸이 다 찬 공정 행."""
    base = {"kind": kind, "process_id": process_id, "name": kind, "work_date": TODAY, "worker": 1}
    base.update(
        {
            "CCP-1P": {"verdict": "적합"},
            "CCP-3P": {"verdict": "적합"},
            "CCP-2B": {"temp": 70.1, "time_min": 118},
            "INNER": {"qty": 100},
            "OUTER": {"material": "PE", "expiry": "2028-10-25", "fg_qty": 100},
            "GEN": {"mode": "JUDGE", "verdict": "적합"},
        }[kind]
    )
    base.update(extra)
    return base
