"""Journal view contracts: plan scaling, unused ingredients and corrected actuals."""

import datetime
import json

from django.db import connection

from .master_import import import_items
from .models import (
    Bom,
    BomLine,
    BomLineAlternative,
    Item,
    ProductionBatch,
    ProductionMaterialUsage,
    StockMovement,
)
from .movements import correct_movement
from .quantity import to_e6
from .test_production import ProductionTestCase


class DocumentProductionSourceTests(ProductionTestCase):
    def setUp(self):
        self.bom = Bom.objects.create(
            item=self.semi, version=1, base_quantity_e6=to_e6(3), effective_from=self.today
        )
        self.water = Item.objects.create(
            item_type_id="RAW",
            item_code="1000098",
            name="정제수",
            base_unit="kg",
            is_stock_managed=False,
        )
        # Intentionally insert in reverse order to require explicit line_no sorting.
        self.water_line = BomLine.objects.create(
            bom=self.bom, line_no=2, component_item=self.water, quantity_e6=to_e6(2)
        )
        self.raw_line = BomLine.objects.create(
            bom=self.bom, line_no=1, component_item=self.raw, quantity_e6=to_e6(1)
        )
        self.alternative = Item.objects.create(
            item_type_id="RAW",
            item_code="1000099",
            name="대체원료",
            base_unit="g",
            origin_country="미국",
            short_code="ALT",
        )
        BomLineAlternative.objects.create(bom_line=self.raw_line, item=self.alternative)
        self.batch_record = self.batch(self.semi, bom_id=self.bom.pk, planned_quantity="10")

    def rows(self, view, suffix="", params=None):
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT * FROM {view} WHERE production_batch_id = %s {suffix}",
                [self.batch_record.pk, *(params or [])],
            )
            keys = [column[0] for column in cursor.description]
            return [dict(zip(keys, row, strict=True)) for row in cursor.fetchall()]

    def test_unconsumed_lines_order_origin_and_ceiling(self):
        self.raw.origin_country = "대한민국"
        self.raw.save()
        rows = self.rows("v_doc_batch_bom_line", "ORDER BY line_no")
        self.assertEqual([r["bom_line_id"] for r in rows], [self.raw_line.pk, self.water_line.pk])
        self.assertEqual([r["standard_quantity_e6"] for r in rows], [3_333_334, 6_666_667])
        self.assertEqual(rows[0]["origin_country"], "대한민국")
        self.assertEqual(rows[0]["base_unit"], "kg")
        self.assertEqual(rows[1]["is_stock_managed"], 0)
        self.assertEqual(self.rows("v_doc_batch_usage"), [])

    def test_null_plan_keeps_lines_with_null_standard(self):
        ProductionBatch.objects.filter(pk=self.batch_record.pk).update(planned_quantity_e6=None)
        rows = self.rows("v_doc_batch_bom_line")
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["standard_quantity_e6"] is None for row in rows))

    def test_output_does_not_change_plan_basis(self):
        self.receive(self.raw, "20", "output-supply")
        self.output(self.batch_record, "2", "first")
        self.output(self.batch_record, "1", "second")
        rows = self.rows("v_doc_batch_bom_line", "ORDER BY line_no")
        self.assertEqual(rows[0]["standard_quantity_e6"], 3_333_334)
        batch = self.rows("v_doc_batch")[0]
        self.assertEqual(batch["output_quantity_e6"], to_e6(3))
        self.assertEqual(batch["output_lot_count"], 1)
        self.assertTrue(batch["output_lot_number"])

    def test_large_products_remain_exact_integers(self):
        # Multiplication exceeds int64; REAL arithmetic would lose the final e6 digit.
        plan, component, base = 9_000_000_001, 9_000_000_007, 3_000_001
        Bom.objects.filter(item=self.semi).update(is_active=False)  # one active version per item
        other_bom = Bom.objects.create(
            item=self.semi, version=2, base_quantity_e6=base, effective_from=self.today
        )
        BomLine.objects.create(
            bom=other_bom, line_no=1, component_item=self.raw, quantity_e6=component
        )
        ProductionBatch.objects.filter(pk=self.batch_record.pk).update(
            bom=other_bom, planned_quantity_e6=plan
        )
        value = self.rows("v_doc_batch_bom_line")[0]["standard_quantity_e6"]
        self.assertIsInstance(value, int)
        self.assertEqual(value, (component * plan + base - 1) // base)

    def test_no_bom_returns_no_lines(self):
        ProductionBatch.objects.filter(pk=self.batch_record.pk).update(bom=None)
        self.assertEqual(self.rows("v_doc_batch_bom_line"), [])

    def test_usage_corrections_and_earliest_active_date(self):
        first_day = self.today - datetime.timedelta(days=2)
        second_day = self.today - datetime.timedelta(days=1)
        lot = self.receive(self.raw, "20", "receipt", day=first_day)
        first = self.use(self.batch_record, lot, "3", "u1", occurred_at=first_day)
        second = self.use(self.batch_record, lot, "2", "u2", occurred_at=second_day)
        correct_movement(
            movement_id=first.stock_movement_id,
            quantity="3",
            staff_id=self.staff.pk,
            reason="투입 취소",
            idempotency_key="c1",
        )
        correct_movement(
            movement_id=second.stock_movement_id,
            quantity="0.5",
            staff_id=self.staff.pk,
            reason="수량 정정",
            idempotency_key="c2",
        )
        rows = self.rows("v_doc_batch_usage", "ORDER BY input_date, usage_id")
        self.assertEqual([r["net_quantity_e6"] for r in rows], [0, to_e6("1.5")])
        self.assertEqual([r["input_date"] for r in rows], [str(first_day), str(second_day)])
        self.assertEqual({r["bom_line_id"] for r in rows}, {self.raw_line.pk})
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT MIN(input_date) FROM v_doc_batch_usage "
                "WHERE production_batch_id = %s AND net_quantity_e6 > 0",
                [self.batch_record.pk],
            )
            self.assertEqual(cursor.fetchone()[0], str(second_day))

    def test_alternative_preserves_actual_unit_and_original_item(self):
        alternative = self.alternative
        lot = self.receive(alternative, "5000", "alt")
        self.use(self.batch_record, lot, "500", "u1", bom_line_id=self.raw_line.pk)
        row = self.rows("v_doc_batch_usage")[0]
        self.assertEqual(row["bom_line_id"], self.raw_line.pk)
        self.assertEqual(row["bom_item_code"], self.raw.item_code)
        self.assertEqual(row["item_code"], alternative.item_code)
        self.assertEqual((row["base_unit"], row["bom_base_unit"]), ("g", "kg"))
        self.assertEqual(row["origin_country"], "미국")
        self.assertEqual(row["net_quantity_e6"], to_e6(500))

    def test_legacy_unlinked_primary_usage_matches_by_item(self):
        lot = self.receive(self.raw, "10", "receipt")
        # Direct INSERT models historical records; production rows are append-only.
        movement = StockMovement.objects.create(
            lot=lot,
            movement_type_id="PRODUCTION_USE",
            quantity_e6=to_e6(1),
            staff=self.staff,
            occurred_at=lot.created_at,
            idempotency_key="legacy",
        )
        ProductionMaterialUsage.objects.create(
            batch=self.batch_record, lot=lot, quantity_e6=to_e6(1), stock_movement=movement
        )
        row = self.rows("v_doc_batch_usage")[0]
        self.assertEqual(row["bom_line_id"], self.raw_line.pk)
        self.assertEqual(row["bom_item_id"], self.raw.pk)

    def test_report_number_api_and_batch_view(self):
        url = f"/api/v1/inventory/items/{self.semi.pk}/"
        response = self.client.patch(
            url,
            json.dumps({"food_type": "기타가공품", "manufacturing_report_number": "001234"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["manufacturing_report_number"], "001234")
        row = self.rows("v_doc_batch")[0]
        self.assertEqual(
            (row["food_type"], row["manufacturing_report_number"]), ("기타가공품", "001234")
        )
        self.assertEqual(row["output_quantity_e6"], 0)
        self.assertIsNone(row["output_lot_number"])
        self.client.patch(url, json.dumps({"name": "이름 변경"}), content_type="application/json")
        self.assertEqual(self.rows("v_doc_batch")[0]["manufacturing_report_number"], "001234")
        self.client.patch(
            url, json.dumps({"manufacturing_report_number": " "}), content_type="application/json"
        )
        self.assertIsNone(self.rows("v_doc_batch")[0]["manufacturing_report_number"])

    def test_import_report_number_and_old_file_preservation(self):
        row = {
            "item_code": self.semi.item_code,
            "item_type": "SEMI",
            "name": self.semi.name,
            "base_unit": self.semi.base_unit,
        }
        import_items([{**row, "manufacturing_report_number": " 001234 "}])
        import_items([row])  # Older CSVs must not erase a registered report number.
        self.semi.refresh_from_db()
        self.assertEqual(self.semi.manufacturing_report_number, "001234")
        import_items([{**row, "manufacturing_report_number": ""}])
        self.semi.refresh_from_db()
        self.assertIsNone(self.semi.manufacturing_report_number)
