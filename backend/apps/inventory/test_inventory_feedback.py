"""Regression tests for batch receipts, optional EA, and protected item removal."""

from .models import IncomingReceipt, Inventory, Item, Lot, StockMovement
from .test_api import ApiTestCase


class InventoryFeedbackTests(ApiTestCase):
    def import_payload(self):
        return {
            "staff_id": self.staff.pk,
            "idempotency_key": "TEST-IMPORT",
            "dry_run": True,
            "rows": [
                {
                    "item_code": self.raw.item_code,
                    "supplier_code": self.supplier.supplier_code,
                    "received_date": self.today,
                    "quantity": "500",
                    "unit": "g",
                    "expiration_status": "KNOWN",
                    "expiration_date": "2028-10-20",
                    "ea_count": "25",
                }
            ],
        }

    def test_import_preview_commit_retry(self):
        payload = self.import_payload()
        baseline = IncomingReceipt.objects.count()
        result = self.post("/receipts/import/", payload)
        self.assertEqual(result.status_code, 200, result.content)
        self.assertEqual(IncomingReceipt.objects.count(), baseline)
        payload["dry_run"] = False
        result = self.post("/receipts/import/", payload)
        self.assertEqual(result.status_code, 200, result.content)
        self.assertEqual(result.json()["results"][0]["quantity"], "0.5")
        self.assertEqual(result.json()["results"][0]["ea_count"], 25)
        again = self.post("/receipts/import/", payload)
        self.assertEqual(again.status_code, 200, again.content)
        self.assertEqual(IncomingReceipt.objects.count(), baseline + 1)

    def test_import_bad_second_row_rolls_back_everything(self):
        payload = self.import_payload()
        payload["dry_run"] = False
        payload["rows"].append({**payload["rows"][0], "item_code": "MISSING"})
        baseline = (
            IncomingReceipt.objects.count(),
            Lot.objects.count(),
            StockMovement.objects.count(),
        )
        result = self.post("/receipts/import/", payload)
        self.assertEqual(result.status_code, 400, result.content)
        self.assertEqual(
            (IncomingReceipt.objects.count(), Lot.objects.count(), StockMovement.objects.count()),
            baseline,
        )

    def test_unused_item_with_receipt_removed_and_trigger_stays_enabled(self):
        receipt = self.receive()
        payload = {"staff_id": self.staff.pk, "item_ids": [self.raw.pk], "dry_run": True}
        preview = self.post("/items/delete/", payload)
        self.assertEqual(preview.status_code, 200, preview.content)
        self.assertEqual(len(preview.json()["removable"]), 1, preview.content)
        self.assertTrue(Item.objects.filter(pk=self.raw.pk).exists())
        payload.update(dry_run=False, confirmation="DELETE_UNUSED_ITEMS")
        result = self.post("/items/delete/", payload)
        self.assertEqual(result.status_code, 200, result.content)
        self.assertFalse(Item.objects.filter(pk=self.raw.pk).exists())
        self.assertFalse(Lot.objects.filter(pk=receipt["lot_id"]).exists())
        self.assertFalse(Inventory.objects.filter(lot_id=receipt["lot_id"]).exists())

    def test_bom_component_is_protected_from_removal(self):
        from .models import Bom, BomLine

        semi = Item.objects.create(
            item_code="TEST-SEMI", name="테스트", item_type_id="SEMI", base_unit="kg"
        )
        bom = Bom.objects.create(
            item=semi, version=1, base_quantity_e6=1000000, effective_from=self.today
        )
        BomLine.objects.create(bom=bom, line_no=1, component_item=self.raw, quantity_e6=1000000)
        result = self.post("/items/delete/", {"staff_id": self.staff.pk, "item_ids": [self.raw.pk]})
        self.assertEqual(result.status_code, 200, result.content)
        self.assertEqual(len(result.json()["blocked"]), 1)
        self.assertTrue(Item.objects.filter(pk=self.raw.pk).exists())

    def test_optional_ea_rejects_fraction_and_keeps_unknown_null(self):
        payload = self.import_payload()
        payload["rows"][0]["ea_count"] = "1.5"
        result = self.post("/receipts/import/", payload)
        self.assertEqual(result.status_code, 400, result.content)
        receipt = self.receive()
        self.assertIsNone(receipt["ea_count"])
