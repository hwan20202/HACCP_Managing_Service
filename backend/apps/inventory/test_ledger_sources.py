"""Navigation context must not change balances or lose original links on corrections."""

from .models import IncomingReceipt
from .movements import correct_movement
from .receiving import cancel_receipt
from .test_production import ProductionTestCase


class LedgerSourceTests(ProductionTestCase):
    def test_cancelled_receipt_status_is_context_only_and_keeps_balances(self):
        lot = self.receive(self.raw, "10", "cancelled-context")
        receipt = IncomingReceipt.objects.get(lot=lot)
        cancel_receipt(receipt_id=receipt.pk, staff_id=self.staff.pk, reason="입고 취소 확인")
        response = self.client.get(
            "/api/v1/inventory/ledger/", {"from": str(self.today), "to": str(self.today)}
        )
        self.assertEqual(response.status_code, 200)
        record = next(
            record
            for item in response.json()["results"]
            for record in item["lots"]
            if record["lot_id"] == lot.pk
        )
        self.assertEqual(record["closing"], "0")
        self.assertEqual([line["balance"] for line in record["lines"]], ["10", "0"])
        for line in record["lines"]:
            self.assertEqual(line["source"]["receipt_status"], "CANCELLED")
            self.assertEqual(line["source"]["receipt_id"], receipt.pk)

    def test_receipt_usage_output_and_correction_links_with_unchanged_balances(self):
        lot = self.receive(self.raw, "10", "links-stock")
        batch = self.batch(self.semi)
        usage = self.use(batch, lot, "1", "links-use")
        output = self.output(batch, "1", "links-output")
        correction = correct_movement(
            movement_id=usage.stock_movement_id,
            quantity="0.2",
            staff_id=self.staff.pk,
            idempotency_key="links-correction",
            reason="연결 확인",
        )
        response = self.client.get(
            "/api/v1/inventory/ledger/",
            {
                "from": str(self.today),
                "to": str(self.today),
            },
        )
        self.assertEqual(response.status_code, 200)
        rows = {
            line["movement_id"]: line
            for item in response.json()["results"]
            for record in item["lots"]
            for line in record["lines"]
        }
        receipt = IncomingReceipt.objects.get(lot=lot)
        self.assertEqual(rows[receipt.stock_movement_id]["source"]["receipt_id"], receipt.pk)
        self.assertEqual(rows[usage.stock_movement_id]["source"]["batch"]["id"], batch.pk)
        self.assertEqual(rows[output.stock_movement_id]["source"]["batch"]["id"], batch.pk)
        self.assertEqual(rows[correction.pk]["source"]["batch"]["id"], batch.pk)
        self.assertEqual(self.stock(lot), 9200000)
        self.assertEqual(rows[correction.pk]["balance"], "9.2")
