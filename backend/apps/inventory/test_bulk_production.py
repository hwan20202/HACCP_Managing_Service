"""Whole-BOM usage drafts and atomic saves, only on Django's isolated test DB."""

from .errors import InventoryError
from .models import Bom, BomLine, BomLineAlternative, Item, ProductionMaterialUsage, StockMovement
from .production import add_usage, add_usages, propose_bulk_allocation, start_batch
from .quantity import to_e6
from .test_production import ProductionTestCase


class BulkProductionTests(ProductionTestCase):
    def setUp(self):
        self.second = Item.objects.create(
            item_type_id="RAW", item_code="BULK2", short_code="B2", name="두 번째", base_unit="g"
        )
        self.bom = Bom.objects.create(
            item=self.semi, version=1, base_quantity_e6=to_e6(1), effective_from=self.today
        )
        self.first_line = BomLine.objects.create(
            bom=self.bom, line_no=1, component_item=self.raw, quantity_e6=to_e6(1)
        )
        self.second_line = BomLine.objects.create(
            bom=self.bom, line_no=2, component_item=self.second, quantity_e6=to_e6(500)
        )
        BomLineAlternative.objects.create(bom_line=self.second_line, item=self.raw)
        self.a = self.receive(self.raw, "10", "bulk-a")
        self.b = self.receive(self.second, "5000", "bulk-b")
        self.batch_ = self.batch(self.semi, bom_id=self.bom.pk)
        start_batch(batch_id=self.batch_.pk, staff_id=self.staff.pk)

    def draft(self, lines=None):
        return propose_bulk_allocation(batch_id=self.batch_.pk, lines=lines)["lines"]

    def save(self, rows, key="whole-bom"):
        return add_usages(
            batch_id=self.batch_.pk,
            staff_id=self.staff.pk,
            idempotency_key=key,
            expected_lines=[
                {k: r[k] for k in ("bom_line_id", "actual", "standard", "quantity")} for r in rows
            ],
            entries=[
                {"lot_id": e["lot_id"], "quantity": e["quantity"], "bom_line_id": r["bom_line_id"]}
                for r in rows
                for e in r["results"]
            ],
        )

    def test_remaining_draft_is_read_only_and_omits_fully_used_lines(self):
        add_usage(
            batch_id=self.batch_.pk,
            lot_id=self.a.pk,
            quantity="0.4",
            bom_line_id=self.first_line.pk,
            staff_id=self.staff.pk,
            idempotency_key="part",
        )
        before = StockMovement.objects.count()
        rows = self.draft()
        self.assertEqual(
            [(r["actual"], r["quantity"]) for r in rows], [("0.4", "0.6"), ("0", "500")]
        )
        self.assertEqual(StockMovement.objects.count(), before)
        self.save(rows)
        self.assertEqual(self.draft(), [])
        self.assertEqual(self.stock(self.a), to_e6(9))

    def test_multi_material_save_replay_and_stale_new_request(self):
        rows = self.draft()
        before = StockMovement.objects.count()
        self.save(rows)
        self.save(rows)
        self.assertEqual(StockMovement.objects.count(), before + 2)
        self.assertEqual(self.stock(self.a), to_e6(9))
        self.assertEqual(self.stock(self.b), to_e6(4500))
        with self.assertRaisesRegex(InventoryError, "변경"):
            self.save(rows, "new-key-stale-draft")
        self.assertEqual(StockMovement.objects.count(), before + 2)

    def test_failure_of_later_material_rolls_back_first_material(self):
        rows = self.draft()
        add_usage(
            batch_id=self.batch_.pk,
            lot_id=self.b.pk,
            quantity="4600",
            bom_line_id=self.second_line.pk,
            staff_id=self.staff.pk,
            idempotency_key="consume",
        )
        # Refresh the usage snapshot but retain the now-unavailable LOT allocation.
        rows[1]["actual"] = "4600"
        before = (StockMovement.objects.count(), ProductionMaterialUsage.objects.count())
        with self.assertRaises(InventoryError):
            self.save(rows)
        self.assertEqual(
            (StockMovement.objects.count(), ProductionMaterialUsage.objects.count()), before
        )
        self.assertEqual(self.stock(self.a), to_e6(10))

    def test_row_total_mismatch_has_no_writes(self):
        rows = self.draft()
        rows[1]["results"][0]["quantity"] = "499"
        before = StockMovement.objects.count()
        with self.assertRaisesRegex(InventoryError, "LOT 합계"):
            self.save(rows)
        self.assertEqual(StockMovement.objects.count(), before)

    def test_shared_alternative_reserves_stock_and_converts_units(self):
        rows = self.draft(
            [
                {"bom_line_id": self.first_line.pk, "quantity": "9.8"},
                {"bom_line_id": self.second_line.pk, "quantity": "500", "item_id": self.raw.pk},
            ]
        )
        self.assertEqual(rows[1]["shortfall"], "300")
        self.assertEqual(rows[1]["results"][0]["quantity"], "0.2")
        rows = self.draft(
            [
                {"bom_line_id": self.first_line.pk, "quantity": "1"},
                {"bom_line_id": self.second_line.pk, "quantity": "500", "item_id": self.raw.pk},
            ]
        )
        self.save(rows)
        self.assertEqual(self.stock(self.a), to_e6("8.5"))
        self.assertEqual(self.stock(self.b), to_e6(5000))

    def test_api_preview_save_and_invalid_rows(self):
        url = f"/api/v1/inventory/batches/{self.batch_.pk}/bulk-allocation/"
        response = self.client.post(url, {}, content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(len(response.json()["lines"]), 2)
        for lines in (
            [None],
            [1],
            [{"bom_line_id": "bad"}],
            [{"bom_line_id": self.first_line.pk, "quantity": "0"}],
        ):
            response = self.client.post(url, {"lines": lines}, content_type="application/json")
            self.assertEqual(response.status_code, 400, response.content)
        rows = self.draft()
        entries = [
            {
                "lot_id": r["results"][0]["lot_id"],
                "bom_line_id": r["bom_line_id"],
                "quantity": r["results"][0]["quantity"],
            }
            for r in rows
        ]
        expected = [
            {k: r[k] for k in ("bom_line_id", "actual", "standard", "quantity")} for r in rows
        ]
        response = self.client.post(
            f"/api/v1/inventory/batches/{self.batch_.pk}/usages/",
            {
                "entries": entries,
                "expected_lines": expected,
                "staff_id": self.staff.pk,
                "idempotency_key": "api-bulk",
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)

    def test_eighteen_ingredients_keep_three_existing_and_save_remaining_fifteen(self):
        Bom.objects.filter(item=self.semi).update(is_active=False)  # one active version per item
        bom = Bom.objects.create(
            item=self.semi, version=2, base_quantity_e6=to_e6(1), effective_from=self.today
        )
        lots = []
        for index in range(18):
            item = Item.objects.create(
                item_type_id="RAW",
                item_code=f"MANY{index}",
                short_code=f"M{index}",
                name=f"일괄 원료 {index}",
                base_unit="kg",
            )
            line = BomLine.objects.create(
                bom=bom, line_no=index + 1, component_item=item, quantity_e6=to_e6("0.01")
            )
            lots.append((self.receive(item, "1", f"many-{index}"), line))
        self.batch_ = self.batch(self.semi, bom_id=bom.pk)
        start_batch(batch_id=self.batch_.pk, staff_id=self.staff.pk)
        for lot, line in lots[:3]:
            add_usage(
                batch_id=self.batch_.pk,
                lot_id=lot.pk,
                quantity="0.01",
                bom_line_id=line.pk,
                staff_id=self.staff.pk,
                idempotency_key=f"prior-{lot.pk}",
            )
        before = list(
            ProductionMaterialUsage.objects.filter(batch=self.batch_).values_list("id", flat=True)
        )
        rows = self.draft()
        self.assertEqual(len(rows), 15)
        self.save(rows)
        self.assertEqual(ProductionMaterialUsage.objects.filter(batch=self.batch_).count(), 18)
        self.assertEqual(ProductionMaterialUsage.objects.filter(id__in=before).count(), 3)
        self.assertTrue(all(self.stock(lot) == to_e6("0.99") for lot, _ in lots))
