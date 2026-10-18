"""Run with HACCP_TEST_FILE_DB=1 and config.settings.test_filedb."""

import os
import threading
import unittest
import uuid
from io import StringIO

from django.core.management import call_command
from django.db import close_old_connections, connection, transaction
from django.test import TransactionTestCase

from .errors import InventoryError
from .fields import kst_now
from .models import Bom, BomLine, Inventory, Item, ProductionMaterialUsage, Staff, Supplier
from .production import add_usages, create_batch, start_batch
from .receiving import ReceiptInput, register_receipt
from .test_support import seed_document_forms


@unittest.skipUnless(os.environ.get("HACCP_TEST_FILE_DB"), "Requires isolated file SQLite")
class BulkConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.assertNotIn("memory", str(connection.settings_dict["NAME"]))
        seed_document_forms()
        call_command("seed_master", "--sample", stdout=StringIO())
        self.staff = Staff.objects.get(staff_code="S001")
        supplier = Supplier.objects.get(supplier_code="V001")
        raw = Item.objects.get(item_code="1000001")
        token = uuid.uuid4().hex[:8]
        semi = Item.objects.create(
            item_type_id="SEMI", item_code="3" + token, name="동시 투입 검증", base_unit="kg"
        )
        today = kst_now().date()
        bom = Bom.objects.create(
            item=semi, version=1, base_quantity_e6=1000000, effective_from=today
        )
        BomLine.objects.create(bom=bom, line_no=1, component_item=raw, quantity_e6=1000000)
        self.lots = [
            register_receipt(
                ReceiptInput(
                    item_id=raw.pk,
                    supplier_id=supplier.pk,
                    staff_id=self.staff.pk,
                    received_date=today,
                    quantity="1",
                    judgment="PASS",
                    expiration_status="NONE",
                    idempotency_key=f"receipt-{token}-{n}",
                )
            ).lot
            for n in range(2)
        ]
        self.batch = create_batch(item_id=semi.pk, staff_id=self.staff.pk, planned_quantity="2")
        start_batch(batch_id=self.batch.pk, staff_id=self.staff.pk)

    def race(self, same_key, reviewed=False):
        locked, release = threading.Event(), threading.Event()
        results = []
        line_id = self.batch.bom.lines.get().pk

        def worker(first):
            close_old_connections()
            try:
                with transaction.atomic():
                    if first:
                        locked.set()
                        if not release.wait(10):
                            raise RuntimeError("test release timeout")
                    add_usages(
                        batch_id=self.batch.pk,
                        staff_id=self.staff.pk,
                        entries=[
                            {
                                "lot_id": lot.pk,
                                "quantity": "1",
                                **({"bom_line_id": line_id} if reviewed else {}),
                            }
                            for lot in self.lots
                        ],
                        idempotency_key=f"{self.batch.pk}-" + ("same" if same_key else str(first)),
                        **(
                            {
                                "expected_lines": [
                                    {
                                        "bom_line_id": line_id,
                                        "actual": "0",
                                        "standard": "2",
                                        "quantity": "2",
                                    }
                                ]
                            }
                            if reviewed
                            else {}
                        ),
                    )
                results.append("ok")
            except InventoryError as error:
                results.append("stale" if reviewed and "변경" in str(error) else "shortage")
            except Exception as error:
                results.append(repr(error))
            finally:
                connection.close()

        first = threading.Thread(target=worker, args=(True,))
        second = threading.Thread(target=worker, args=(False,))
        first.start()
        self.assertTrue(locked.wait(10))
        second.start()
        second.join(0.3)
        try:
            self.assertTrue(second.is_alive(), "second writer must wait for IMMEDIATE lock")
        finally:
            release.set()
            first.join(15)
            second.join(15)
        self.assertFalse(first.is_alive() or second.is_alive())
        self.assertCountEqual(
            results, ["ok", "ok"] if same_key else ["ok", "stale" if reviewed else "shortage"]
        )
        self.assertEqual(ProductionMaterialUsage.objects.filter(batch=self.batch).count(), 2)
        self.assertEqual(
            list(Inventory.objects.filter(lot__in=self.lots).values_list("quantity_e6", flat=True)),
            [0, 0],
        )

    def test_two_requests_cannot_consume_the_same_stock(self):
        self.race(False)

    def test_concurrent_double_click_is_one_bulk_request(self):
        self.race(True)

    def test_reviewed_draft_rejects_second_request_with_a_different_key(self):
        self.race(False, reviewed=True)
