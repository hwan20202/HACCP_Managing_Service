"""Production services (production.py) on the Django test database."""

import datetime
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.db import connection
from django.test import TestCase

from .errors import InventoryError, NotFound
from .fields import kst_now
from .lot_numbers import LotNumberError
from .models import (
    AuditLog,
    BatchStatus,
    Bom,
    BomLine,
    Inventory,
    Item,
    LotKind,
    LotStatus,
    Staff,
    Supplier,
)
from .movements import correct_movement
from .production import (
    add_output,
    add_usage,
    batch_summary,
    cancel_batch,
    complete_batch,
    create_batch,
    fefo_candidates,
    standard_requirements,
    start_batch,
)
from .quantity import to_e6
from .receiving import ReceiptInput, register_receipt
from .shelf_life import add_months


class ProductionTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_master", "--sample", stdout=StringIO())
        cls.raw = Item.objects.get(item_code="1000001")  # LOT 약어 AGA
        cls.pouch = Item.objects.get(item_code="2000001")  # CGP
        cls.finished = Item.objects.get(item_code="4000001")  # shelf_life_months 24
        cls.semi = Item.objects.create(
            item_type_id="SEMI",
            item_code="3000001",
            short_code="BGH",
            name="가상환(벌크)",
            base_unit="개",
            shelf_life_days=365,
        )
        cls.supplier = Supplier.objects.get(supplier_code="V001")
        cls.staff = Staff.objects.get(staff_code="S001")
        cls.today = kst_now().date()

    def receive(self, item, quantity, key, judgment="PASS", expiration=None, day=None):
        return register_receipt(
            ReceiptInput(
                item_id=item.pk,
                supplier_id=self.supplier.pk,
                staff_id=self.staff.pk,
                received_date=day or self.today,
                quantity=quantity,
                idempotency_key=key,
                expiration_date=expiration,
                judgment=judgment,
            )
        ).lot

    def batch(self, item, process="MANUFACTURE", **extra):
        return create_batch(item_id=item.pk, process_type=process, staff_id=self.staff.pk, **extra)

    def use(self, batch, lot, quantity, key, **extra):
        return add_usage(
            batch_id=batch.pk,
            lot_id=lot.pk,
            quantity=quantity,
            staff_id=self.staff.pk,
            idempotency_key=key,
            **extra,
        )

    def output(self, batch, quantity, key, **extra):
        return add_output(
            batch_id=batch.pk,
            quantity=quantity,
            staff_id=self.staff.pk,
            idempotency_key=key,
            **extra,
        )

    def stock(self, lot):
        return Inventory.objects.get(lot=lot).quantity_e6

    def assert_consistent(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM v_inventory_mismatch")
            self.assertEqual(cursor.fetchall(), [])


class BatchFlowTests(ProductionTestCase):
    def test_raw_to_semi_to_finished(self):
        raw_lot = self.receive(self.raw, "100", "r1")
        pouch_lot = self.receive(self.pouch, "1000", "r2")
        day = f"{self.today:%y%m%d}"

        mfg = self.batch(self.semi)
        self.assertEqual(mfg.batch_number, f"B-3000001-{day}A")
        self.assertEqual(mfg.status, BatchStatus.PLANNED)
        with patch("apps.inventory.document_bridge.batch_started") as hook:
            start_batch(batch_id=mfg.pk, staff_id=self.staff.pk)
        hook.assert_called_once_with(batch_id=mfg.pk, staff_id=self.staff.pk)
        self.use(mfg, raw_lot, "40", "u1")
        semi_lot = self.output(mfg, "10000", "o1").lot
        complete_batch(batch_id=mfg.pk, staff_id=self.staff.pk)
        self.assertEqual(semi_lot.lot_number, f"BGH{day}")
        self.assertEqual(semi_lot.lot_kind, LotKind.PRODUCED)
        self.assertEqual(semi_lot.status, LotStatus.AVAILABLE)
        self.assertEqual(semi_lot.expiration_date, self.today + datetime.timedelta(days=365))
        self.assertEqual(self.stock(raw_lot), to_e6(60))

        pack = self.batch(self.finished, process="PACKAGING", shift="A")
        self.assertEqual(pack.batch_number, f"B-4000001-{day}A")
        self.use(pack, semi_lot, "10000", "u2")
        self.use(pack, pouch_lot, "200", "u3")
        first = self.output(pack, "100", "o2").lot
        second = self.output(pack, "100", "o3").lot
        self.assertEqual((first.lot_number, second.lot_number), (f"{day}A", f"{day}A-2"))
        self.assertEqual(first.expiration_date, add_months(self.today, 24))  # 24개월 품목
        done = complete_batch(batch_id=pack.pk, staff_id=self.staff.pk)
        self.assertEqual(done.status, BatchStatus.COMPLETED)
        self.assertIsNotNone(done.completed_at)

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT derived_lot_id FROM v_lot_trace WHERE source_lot_id = %s ORDER BY 1",
                [raw_lot.pk],
            )
            self.assertEqual(
                [row[0] for row in cursor.fetchall()], [semi_lot.pk, first.pk, second.pk]
            )
        summary = batch_summary(pack.pk)
        self.assertEqual(len(summary["usages"]), 2)
        self.assertEqual([row["stock_e6"] for row in summary["outputs"]], [to_e6(100)] * 2)
        self.assertEqual(
            AuditLog.objects.filter(table_name="production_batches").count(), 5
        )  # 2 creates, 1 start, 2 completes
        self.assert_consistent()

    def test_completed_after_the_fact_without_start(self):
        made = self.today - datetime.timedelta(days=1)
        raw_lot = self.receive(self.raw, "10", "r1", day=made)
        batch = self.batch(self.semi, manufactured_date=made)
        self.use(batch, raw_lot, "5", "u1", occurred_at=made)
        lot = self.output(batch, "500", "o1", occurred_at=made).lot
        self.assertEqual(lot.lot_number, f"BGH{made:%y%m%d}")
        with patch("apps.inventory.document_bridge.batch_started") as hook:
            done = complete_batch(batch_id=batch.pk, staff_id=self.staff.pk)
        hook.assert_called_once_with(batch_id=batch.pk, staff_id=self.staff.pk)
        self.assertEqual(done.manufactured_date, made)
        self.assertIsNotNone(done.started_at)

    def test_finished_output_needs_a_shift(self):
        batch = self.batch(self.finished, process="PACKAGING")
        with self.assertRaises(LotNumberError):
            self.output(batch, "10", "o1")

    def test_complete_needs_output_and_closed_batches_take_nothing(self):
        raw_lot = self.receive(self.raw, "10", "r1")
        batch = self.batch(self.semi)
        with self.assertRaises(InventoryError):
            complete_batch(batch_id=batch.pk, staff_id=self.staff.pk)
        self.output(batch, "1", "o1")
        complete_batch(batch_id=batch.pk, staff_id=self.staff.pk)
        with self.assertRaises(InventoryError):
            self.use(batch, raw_lot, "1", "u1")
        with self.assertRaises(InventoryError):
            cancel_batch(batch_id=batch.pk, staff_id=self.staff.pk, reason="x")

    def test_cancel_only_after_everything_is_corrected(self):
        raw_lot = self.receive(self.raw, "10", "r1")
        batch = self.batch(self.semi)
        usage = self.use(batch, raw_lot, "3", "u1")
        with self.assertRaises(InventoryError):
            cancel_batch(batch_id=batch.pk, staff_id=self.staff.pk, reason="잘못 등록")
        correct_movement(
            movement_id=usage.stock_movement_id,
            reason="잘못 등록",
            staff_id=self.staff.pk,
            idempotency_key="c1",
        )
        cancelled = cancel_batch(batch_id=batch.pk, staff_id=self.staff.pk, reason="잘못 등록")
        self.assertEqual(cancelled.status, BatchStatus.CANCELLED)
        self.assertEqual(self.stock(raw_lot), to_e6(10))
        with self.assertRaises(InventoryError):
            cancel_batch(batch_id=batch.pk, staff_id=self.staff.pk, reason="")
        self.assert_consistent()

    def test_create_rules(self):
        with self.assertRaises(InventoryError):
            self.batch(self.raw)  # not a produced item
        with self.assertRaises(InventoryError):
            self.batch(self.semi, process="MIXING")
        with self.assertRaises(InventoryError):
            self.batch(self.semi, shift="C")
        with self.assertRaises(NotFound):
            create_batch(item_id=999999, process_type="MANUFACTURE", staff_id=self.staff.pk)
        self.batch(self.semi)
        self.assertTrue(self.batch(self.semi).batch_number.endswith("B"))


class UsageRuleTests(ProductionTestCase):
    def setUp(self):
        self.batch_ = self.batch(self.semi)

    def test_only_usable_unexpired_lots_with_stock(self):
        cases = {
            "검사대기": self.receive(self.raw, "10", "q", judgment=None),
            "부적합": self.receive(self.raw, "10", "f", judgment="FAIL"),
            "소비기한 경과": self.receive(
                self.raw, "10", "e", expiration=self.today - datetime.timedelta(days=1)
            ),
        }
        for label, lot in cases.items():
            with self.subTest(label), self.assertRaises(InventoryError):
                self.use(self.batch_, lot, "1", f"u-{label}")
        good = self.receive(self.raw, "10", "g")
        with self.assertRaises(InventoryError):
            self.use(self.batch_, good, "10.5", "u-over")
        semi_lot = self.output(self.batch_, "5", "o1").lot
        with self.assertRaises(InventoryError):
            self.use(self.batch_, semi_lot, "1", "u-self")  # same item as the output

    def test_replay_and_conflict(self):
        lot = self.receive(self.raw, "10", "r1")
        first = self.use(self.batch_, lot, "2", "u1")
        self.assertEqual(self.use(self.batch_, lot, "2", "u1").pk, first.pk)
        with self.assertRaises(InventoryError):
            self.use(self.batch_, lot, "3", "u1")
        output = self.output(self.batch_, "5", "o1")
        self.assertEqual(self.output(self.batch_, "5", "o1").pk, output.pk)
        self.assertEqual(self.stock(lot), to_e6(8))

    def test_bom_line_must_match(self):
        bom = Bom.objects.create(
            item=self.semi, version=1, base_quantity_e6=to_e6(1000), effective_from=self.today
        )
        line = BomLine.objects.create(
            bom=bom, line_no=1, component_item=self.raw, quantity_e6=to_e6(4)
        )
        batch = self.batch(self.semi)
        self.assertEqual(batch.bom_id, bom.pk)  # active BOM by default
        raw_lot = self.receive(self.raw, "10", "r1")
        pouch_lot = self.receive(self.pouch, "10", "r2")
        self.assertEqual(self.use(batch, raw_lot, "4", "u1", bom_line_id=line.pk).bom_line, line)
        with self.assertRaises(InventoryError):
            self.use(batch, pouch_lot, "1", "u2", bom_line_id=line.pk)
        need = standard_requirements(bom_id=bom.pk, quantity="2500")
        self.assertEqual([(row.pk, amount) for row, amount in need], [(line.pk, to_e6(10))])

    def test_manual_lot_number_and_expiration(self):
        lot = self.output(
            self.batch_,
            "5",
            "o1",
            lot_number="OLD-SEMI-1",
            expiration_date=self.today + datetime.timedelta(days=10),
        ).lot
        self.assertEqual(lot.lot_number, "OLD-SEMI-1")
        with self.assertRaises(InventoryError):
            self.output(self.batch_, "5", "o2", lot_number="OLD-SEMI-1")


class FefoTests(ProductionTestCase):
    def test_earliest_expiration_first_and_shortfall(self):
        later = self.receive(self.raw, "30", "r1", expiration=self.today + datetime.timedelta(60))
        sooner = self.receive(self.raw, "20", "r2", expiration=self.today + datetime.timedelta(10))
        no_date = self.receive(self.raw, "5", "r3")
        self.receive(self.raw, "50", "r4", judgment=None)  # QUARANTINE: left out
        picks = fefo_candidates(item_id=self.raw.pk, quantity="45")
        self.assertEqual(
            [(lot.pk, take) for lot, take, _ in picks],
            [(sooner.pk, to_e6(20)), (later.pk, to_e6(25))],
        )
        everything = fefo_candidates(item_id=self.raw.pk, quantity="1000")
        self.assertEqual([lot.pk for lot, _, _ in everything], [sooner.pk, later.pk, no_date.pk])
        self.assertEqual(sum(take for _, take, _ in everything), to_e6(55))
