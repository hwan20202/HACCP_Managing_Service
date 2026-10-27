"""Inventory -> document app hooks (document_bridge) against the real document services.

Contract: docs/reference/document-inventory-interface.md.
The document app's functions run inside the inventory transaction:
their errors roll the inventory change back.
"""

import datetime
import json
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps.doc_requirements import services as req
from apps.documents.models import DocSection, Document, DocumentTemplate

from .fields import kst_now
from .models import AuditLog, Bom, BomLine, IncomingReceipt, Item, Lot, LotStatus, Staff, Supplier
from .production import add_output, complete_batch, create_batch, start_batch
from .receiving import ReceiptInput, ReceivingError, cancel_receipt, register_receipt
from .test_support import seed_document_forms

PASS = {"appearance": "양호", "packaging": "양호", "labeling": "양호", "verdict": "PASS"}


class DocumentBridgeTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_document_forms()
        call_command("seed_master", "--sample", stdout=StringIO())
        cls.raw = Item.objects.get(item_code="1000001")
        cls.supplier = Supplier.objects.get(supplier_code="V001")
        cls.staff = Staff.objects.get(staff_code="S001")
        cls.today = kst_now().date()
        cls.semi = Item.objects.create(
            item_type_id="SEMI",
            item_code="3000001",
            short_code="BGH",
            name="가상환(벌크)",
            base_unit="개",
            shelf_life_days=365,
        )

    def receive(self, key="k1", **overrides):
        values = {
            "item_id": self.raw.pk,
            "supplier_id": self.supplier.pk,
            "staff_id": self.staff.pk,
            "received_date": self.today,
            "quantity": "50",
            "idempotency_key": key,
            "expiration_date": datetime.date(2027, 9, 1),
        }
        values.update(overrides)
        return register_receipt(ReceiptInput(**values))

    def documents(self, lot_id):
        return {d["type_code"]: d for d in req.docs_for_lot(lot_id)["documents"]}


class ReceiptHookTests(DocumentBridgeTestCase):
    def test_receipt_creates_lot_documents(self):
        receipt = self.receive()
        self.assertEqual(
            [(d["type_code"], d["result"]) for d in receipt.documents["documents"]],
            [("D01", "created"), ("D02", "created"), ("D03", "created")],
        )
        docs = self.documents(receipt.lot_id)
        self.assertEqual(sorted(docs), ["D01", "D02", "D03"])
        self.assertEqual({d["status"] for d in docs.values()}, {"draft"})
        self.assertEqual(receipt.lot.status, LotStatus.QUARANTINE)
        # same request key: same receipt, no new documents
        again = self.receive()
        self.assertEqual((again.pk, again.documents), (receipt.pk, None))
        self.assertEqual(Document.objects.count(), 3)

    def test_inspection_fills_d03_and_sets_the_judgment(self):
        receipt = self.receive(inspection=PASS)
        d03 = next(d for d in receipt.documents["documents"] if d["type_code"] == "D03")
        self.assertTrue(d03["inspection_applied"])
        lot = Lot.objects.get(pk=receipt.lot_id)
        self.assertEqual(lot.status, LotStatus.AVAILABLE)
        audit = AuditLog.objects.filter(table_name="lots", record_id=str(lot.pk)).latest("pk")
        after = (
            audit.after_json if isinstance(audit.after_json, dict) else json.loads(audit.after_json)
        )
        self.assertEqual((after["judgment"], after["document_id"]), ("PASS", d03["document_id"]))

    def test_pass_judgment_without_inspection_fills_d03_all_pass(self):
        receipt = self.receive(judgment="PASS")
        d03 = next(d for d in receipt.documents["documents"] if d["type_code"] == "D03")
        self.assertTrue(d03["inspection_applied"])
        row = DocSection.objects.get(document_id=d03["document_id"], section_def="inspection")
        self.assertEqual(row.values_json, PASS)
        self.assertEqual(Lot.objects.get(pk=receipt.lot_id).status, LotStatus.AVAILABLE)

    def test_receipt_staff_becomes_d03_inspector(self):
        """D-233 Q1 b: 판정과 상관없이 새 D03 점검자 = 입고 담당자."""
        for key, judgment in (("ins-pass", "PASS"), ("ins-none", None)):
            with self.subTest(judgment=judgment):
                receipt = self.receive(key, judgment=judgment)
                d03 = next(d for d in receipt.documents["documents"] if d["type_code"] == "D03")
                info = DocSection.objects.get(document_id=d03["document_id"], section_def="info")
                self.assertEqual(info.values_json.get("inspector"), self.staff.pk)

    def test_fail_judgment_without_inspection_leaves_d03_empty(self):
        receipt = self.receive(judgment="FAIL")
        d03 = next(d for d in receipt.documents["documents"] if d["type_code"] == "D03")
        self.assertFalse(d03["inspection_applied"])

    def test_judgment_and_inspection_must_agree(self):
        with self.assertRaisesMessage(ReceivingError, "다릅니다"):
            self.receive(judgment="FAIL", inspection=PASS)
        self.assertEqual(Lot.objects.count(), 0)

    def test_document_error_rolls_the_receipt_back(self):
        from apps.core.http import ApiError

        with self.assertRaises(ApiError) as raised:
            self.receive(inspection={**PASS, "unknown": "x"})
        self.assertEqual(raised.exception.code, "VALIDATION_ERROR")
        DocumentTemplate.objects.filter(type_code="D01").update(is_active=False)
        with self.assertRaises(ApiError):
            self.receive("k2")
        self.assertEqual(
            (Lot.objects.count(), IncomingReceipt.objects.count(), Document.objects.count()),
            (0, 0, 0),
        )

    def test_api_maps_document_errors(self):
        res = self.client.post(
            "/api/v1/inventory/receipts/",
            json.dumps(
                {
                    "item_id": self.raw.pk,
                    "supplier_id": self.supplier.pk,
                    "staff_id": self.staff.pk,
                    "received_date": self.today.isoformat(),
                    "quantity": "5",
                    "idempotency_key": "api-1",
                    "expiration_status": "NONE",
                    "inspection": {**PASS, "unknown": "x"},
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 400, res.content)
        self.assertEqual(res.json()["error"]["code"], "VALIDATION_ERROR")
        self.assertEqual(Lot.objects.count(), 0)


class CancelHookTests(DocumentBridgeTestCase):
    def cancel(self, receipt):
        return cancel_receipt(receipt_id=receipt.pk, staff_id=self.staff.pk, reason="오입력")

    def test_cancel_allowed_while_documents_are_drafts(self):
        receipt = self.receive()
        self.assertEqual(self.cancel(receipt).receipt_status, "CANCELLED")

    def test_cancel_refused_once_a_document_is_in_approval(self):
        for n, status in enumerate(("submitted", "approved", "correcting"), start=1):
            receipt = self.receive(f"k{n}")
            d03 = self.documents(receipt.lot_id)["D03"]["document_id"]
            Document.objects.filter(pk=d03).update(status=status)
            with self.assertRaisesMessage(ReceivingError, f"D03({status})"):
                self.cancel(receipt)
            receipt.refresh_from_db()
            self.assertEqual(receipt.receipt_status, "COMPLETED")

    def test_rejected_document_does_not_block(self):
        receipt = self.receive()
        d03 = self.documents(receipt.lot_id)["D03"]["document_id"]
        Document.objects.filter(pk=d03).update(status="rejected")
        self.assertEqual(self.cancel(receipt).receipt_status, "CANCELLED")


class BatchHookTests(DocumentBridgeTestCase):
    def batch(self):
        water = Item.objects.create(
            item_type_id="RAW",
            item_code="WATER",
            name="공정용수",
            base_unit="kg",
            is_stock_managed=False,
        )
        bom = Bom.objects.create(
            item=self.semi, version=1, base_quantity_e6=1000000, effective_from=self.today
        )
        BomLine.objects.create(bom=bom, line_no=1, component_item=water, quantity_e6=1000000)
        return create_batch(
            item_id=self.semi.pk,
            staff_id=self.staff.pk,
            manufactured_date=self.today,
            planned_quantity="10",
        )

    def ccp(self, batch):
        return [d["process_code"] for d in req.docs_for_batch(batch.pk)["documents"]]

    def test_start_creates_ccp_records(self):
        batch = self.batch()
        self.assertEqual(self.ccp(batch), [])
        start_batch(batch_id=batch.pk, staff_id=self.staff.pk)
        self.assertEqual(self.ccp(batch), ["1P", "2B", "3P"])

    def test_start_then_complete_does_not_duplicate_ccp(self):
        batch = self.batch()
        start_batch(batch_id=batch.pk, staff_id=self.staff.pk)
        start_batch(batch_id=batch.pk, staff_id=self.staff.pk)
        add_output(batch_id=batch.pk, quantity="10", staff_id=self.staff.pk, idempotency_key="o1")
        complete_batch(batch_id=batch.pk, staff_id=self.staff.pk)
        self.assertEqual(self.ccp(batch), ["1P", "2B", "3P"])
