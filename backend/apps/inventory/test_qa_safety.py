"""QA regression tests; only Django's isolated test database is used."""

from unittest.mock import patch

from .errors import InventoryError
from .models import (
    Bom,
    BomLine,
    BomLineAlternative,
    ProductionBatch,
    ProductionMaterialUsage,
    StockMovement,
)
from .production import add_usages, batch_summary, complete_batch, material_readiness, start_batch
from .quantity import to_e6
from .test_production import ProductionTestCase


class QaSafetyTests(ProductionTestCase):
    def setUp(self):
        self.bom = Bom.objects.create(
            item=self.semi, version=1, base_quantity_e6=to_e6(1), effective_from=self.today
        )
        self.line = BomLine.objects.create(
            bom=self.bom, line_no=1, component_item=self.raw, quantity_e6=to_e6(1)
        )
        self.a = self.receive(self.raw, "1", "a")
        self.b = self.receive(self.raw, "1", "b")
        self.batch_ = self.batch(self.semi, planned_quantity="2")

    def use(self, batch, lot, quantity, key, **extra):
        from .production import add_usage

        return add_usage(
            batch_id=batch.pk,
            lot_id=lot.pk,
            quantity=quantity,
            staff_id=self.staff.pk,
            idempotency_key=key,
            **extra,
        )

    def output(self, batch, quantity, key, **extra):
        from .production import add_output

        return add_output(
            batch_id=batch.pk,
            quantity=quantity,
            staff_id=self.staff.pk,
            idempotency_key=key,
            **extra,
        )

    def start(self):
        return start_batch(batch_id=self.batch_.pk, staff_id=self.staff.pk)

    def bulk(self, entries, key="bulk"):
        return add_usages(
            batch_id=self.batch_.pk, staff_id=self.staff.pk, entries=entries, idempotency_key=key
        )

    def test_outside_bom_without_line_is_rejected_without_any_writes(self):
        self.start()
        foreign = self.receive(self.pouch, "3", "foreign")
        before = (
            StockMovement.objects.count(),
            ProductionMaterialUsage.objects.count(),
            self.stock(foreign),
        )
        for line in (None, self.line.pk):
            with self.assertRaises(InventoryError):
                self.use(self.batch_, foreign, "1", "bad", bom_line_id=line)
        self.assertEqual(
            before,
            (
                StockMovement.objects.count(),
                ProductionMaterialUsage.objects.count(),
                self.stock(foreign),
            ),
        )

    def test_auto_link_and_alternative_conversion(self):
        from .models import Item

        Bom.objects.filter(item=self.semi).update(is_active=False)  # one active version per item
        self.bom = Bom.objects.create(
            item=self.semi, version=2, base_quantity_e6=to_e6(1), effective_from=self.today
        )
        self.line = BomLine.objects.create(
            bom=self.bom, line_no=1, component_item=self.raw, quantity_e6=to_e6(1)
        )
        alt = Item.objects.create(
            item_type_id="RAW", item_code="ALT", short_code="ALT", name="대체 원료", base_unit="g"
        )
        BomLineAlternative.objects.create(bom_line=self.line, item=alt)
        self.batch_ = self.batch(self.semi, planned_quantity="2", bom_id=self.bom.pk)
        lot = self.receive(alt, "1000", "alt")
        self.start()
        usage = self.use(self.batch_, lot, "1000", "alt-use")
        self.assertEqual(usage.bom_line_id, self.line.pk)
        self.assertEqual(
            batch_summary(self.batch_.pk)["bom_check"]["lines"][0]["actual_e6"], to_e6(1)
        )

    def test_bulk_rollback_replay_conflict_and_depletion(self):
        self.start()
        before = StockMovement.objects.count()
        with self.assertRaises(InventoryError):
            self.bulk(
                [{"lot_id": self.a.pk, "quantity": "1"}, {"lot_id": self.b.pk, "quantity": "2"}]
            )
        self.assertEqual(StockMovement.objects.count(), before)
        self.assertEqual(self.stock(self.a), to_e6(1))
        rows = [{"lot_id": self.a.pk, "quantity": "1"}, {"lot_id": self.b.pk, "quantity": "1"}]
        self.bulk(rows)
        self.bulk(rows)
        self.assertEqual(StockMovement.objects.count(), before + 2)
        self.assertEqual(self.stock(self.a), 0)
        with self.assertRaises(InventoryError):
            self.bulk(rows, "another-request")
        with self.assertRaises(InventoryError):
            self.bulk(rows[:1])
        self.assertEqual(StockMovement.objects.count(), before + 2)
        self.assert_consistent()

    def test_shortage_preserves_plan_and_does_not_call_ccp(self):
        ProductionBatch.objects.filter(pk=self.batch_.pk).update(planned_quantity_e6=to_e6(100))
        for _ in range(2):
            with patch("apps.inventory.document_bridge.batch_started") as hook:
                with self.assertRaises(InventoryError):
                    self.start()
                hook.assert_not_called()
        self.batch_.refresh_from_db()
        self.assertEqual(self.batch_.status, "PLANNED")
        self.assertIsNone(self.batch_.started_at)

    def test_ccp_failure_rolls_back_start_and_retry_creates_only_once(self):
        from apps.documents.models import Document

        before = Document.objects.count()
        with patch(
            "apps.inventory.document_bridge.batch_started", side_effect=RuntimeError("CCP failure")
        ):
            with self.assertRaises(RuntimeError):
                self.start()
        self.batch_.refresh_from_db()
        self.assertEqual(self.batch_.status, "PLANNED")
        self.assertEqual(Document.objects.count(), before)
        self.start()
        self.start()
        self.assertEqual(Document.objects.count(), before + 3)

    def test_planned_usage_and_output_rejected(self):
        with self.assertRaises(InventoryError):
            self.use(self.batch_, self.a, "1", "use")
        with self.assertRaises(InventoryError):
            self.output(self.batch_, "1", "out")

    def test_complete_requires_each_stock_component(self):
        self.start()
        self.output(self.batch_, "2", "output")
        with self.assertRaisesRegex(InventoryError, "필수 원료"):
            complete_batch(batch_id=self.batch_.pk, staff_id=self.staff.pk)
        self.use(self.batch_, self.a, "1", "use")
        # No invented yield tolerance: positive input meets the missing-material check.
        complete_batch(batch_id=self.batch_.pk, staff_id=self.staff.pk)

    def test_shared_alternative_is_not_counted_twice(self):
        Bom.objects.filter(item=self.semi).update(is_active=False)  # one active version per item
        self.bom = Bom.objects.create(
            item=self.semi, version=2, base_quantity_e6=to_e6(1), effective_from=self.today
        )
        BomLine.objects.create(
            bom=self.bom, line_no=1, component_item=self.raw, quantity_e6=to_e6(1)
        )
        BomLine.objects.create(
            bom=self.bom, line_no=2, component_item=self.pouch, quantity_e6=to_e6(1)
        )
        # Same-unit alternative lets both lines compete for the same 2 units.
        self.pouch.base_unit = self.raw.base_unit
        self.pouch.save(update_fields=["base_unit"])
        second = self.bom.lines.get(line_no=2)
        BomLineAlternative.objects.create(bom_line=second, item=self.raw)
        self.batch_ = self.batch(self.semi, planned_quantity="2", bom_id=self.bom.pk)
        check = material_readiness(self.batch_)
        self.assertFalse(check["ready"])
        self.assertEqual(sum(float(r["shortfall"]) for r in check["lines"]), 2)

    def test_api_bulk_and_foreign_item_validation(self):
        self.start()
        foreign = self.receive(self.pouch, "1", "foreign")
        url = f"/api/v1/inventory/batches/{self.batch_.pk}/usages/"
        response = self.client.post(
            url,
            {
                "lot_id": foreign.pk,
                "quantity": "1",
                "staff_id": self.staff.pk,
                "idempotency_key": "bad",
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        response = self.client.post(
            url,
            {
                "entries": [
                    {"lot_id": self.a.pk, "quantity": "1"},
                    {"lot_id": self.b.pk, "quantity": "1"},
                ],
                "staff_id": self.staff.pk,
                "idempotency_key": "ok",
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
