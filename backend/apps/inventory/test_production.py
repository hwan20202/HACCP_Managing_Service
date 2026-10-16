"""Production services (production.py) on the Django test database."""

import datetime
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.test import TestCase

from .errors import InventoryError, NotFound
from .fields import KST, kst_now
from .models import (
    AuditLog,
    BatchStatus,
    Bom,
    BomLine,
    BomLineAlternative,
    Inventory,
    Item,
    Lot,
    LotKind,
    LotStatus,
    ProductionBatch,
    ProductionOutput,
    Staff,
    StockMovement,
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
from .test_support import seed_document_forms


class ProductionTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_document_forms()
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
                # 원료는 소비기한 유무를 정해야 함 (0007): 날짜가 없으면 '없음'으로 입고
                expiration_status=None if expiration else "NONE",
                judgment=judgment,
            )
        ).lot

    def batch(self, item, process="MANUFACTURE", **extra):
        # 제조일 = 생산 시작일 (10/14). Tests enter it at creation unless they test its absence.
        extra.setdefault("manufactured_date", self.today)
        extra.setdefault("planned_quantity", "1")
        if item == self.semi and not Bom.objects.filter(item=item).exists():
            bom = Bom.objects.create(
                item=item,
                version=999,
                base_quantity_e6=to_e6(1000),
                effective_from=self.today - datetime.timedelta(days=365),
            )
            BomLine.objects.create(
                bom=bom, line_no=1, component_item=self.raw, quantity_e6=to_e6(1)
            )
        return create_batch(item_id=item.pk, process_type=process, staff_id=self.staff.pk, **extra)

    def use(self, batch, lot, quantity, key, **extra):
        # Service-rule tests enter production explicitly before recording inputs.
        batch.refresh_from_db()
        if batch.status == BatchStatus.PLANNED:
            start_batch(batch_id=batch.pk, staff_id=self.staff.pk)
        return add_usage(
            batch_id=batch.pk,
            lot_id=lot.pk,
            quantity=quantity,
            staff_id=self.staff.pk,
            idempotency_key=key,
            **extra,
        )

    def output(self, batch, quantity, key, **extra):
        batch.refresh_from_db()
        if batch.status == BatchStatus.PLANNED and batch.manufactured_date:
            # Output-number tests need an eligible input supply before starting.
            from .production import material_readiness

            if not material_readiness(batch)["ready"]:
                self.receive(self.raw, "1", f"output-supply-{batch.pk}")
            start_batch(batch_id=batch.pk, staff_id=self.staff.pk)
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
        day = f"{self.today:%y%m%d}"

        mfg = self.batch(self.semi)
        self.assertEqual(mfg.batch_number, f"B-3000001-{day}A")
        self.assertEqual(mfg.status, BatchStatus.PLANNED)
        with patch("apps.inventory.document_bridge.batch_started") as hook:
            start_batch(batch_id=mfg.pk, staff_id=self.staff.pk)
        hook.assert_called_once_with(batch_id=mfg.pk, staff_id=self.staff.pk)
        self.use(mfg, raw_lot, "40", "u1")
        semi_lot = self.output(mfg, "6000", "o1").lot
        # 산출을 나눠 입력해도 LOT 은 하나 (10/15): 같은 LOT 에 더해진다
        self.assertEqual(self.output(mfg, "4000", "o2").lot, semi_lot)
        complete_batch(batch_id=mfg.pk, staff_id=self.staff.pk)
        self.assertEqual(semi_lot.lot_number, f"{day}A")
        self.assertEqual(semi_lot.lot_kind, LotKind.PRODUCED)
        self.assertEqual(semi_lot.status, LotStatus.AVAILABLE)
        # 소비기한은 하루 전 (10/14 B3): 365일 품목 -> 364일 뒤
        self.assertEqual(semi_lot.expiration_date, self.today + datetime.timedelta(days=364))
        self.assertEqual(self.stock(raw_lot), to_e6(60))
        self.assertEqual(self.stock(semi_lot), to_e6(10000))

        summary = batch_summary(mfg.pk)
        self.assertEqual(len(summary["outputs"]), 2)  # 산출 행 2, LOT 1
        self.assertEqual(
            summary["output_lot"],
            {
                "lot_id": semi_lot.pk,
                "lot_number": f"{day}A",
                "net_quantity_e6": to_e6(10000),
                "stock_e6": to_e6(10000),
            },
        )
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT derived_lot_id, depth FROM v_lot_trace WHERE source_lot_id = %s",
                [raw_lot.pk],
            )
            self.assertEqual(cursor.fetchall(), [(semi_lot.pk, 1)])
            cursor.execute(
                "SELECT output_lot_count, output_lot_number, output_quantity_e6 FROM v_doc_batch"
                " WHERE production_batch_id = %s",
                [mfg.pk],
            )
            self.assertEqual(cursor.fetchone(), (1, f"{day}A", to_e6(10000)))

        # 같은 날 같은 반제품의 두 번째 배치는 B
        second = self.batch(self.semi)
        self.assertEqual(self.output(second, "1", "o3").lot.lot_number, f"{day}B")
        self.assertEqual(
            AuditLog.objects.filter(table_name="production_batches").count(), 5
        )  # 2 creates, 1 start, 1 complete
        self.assert_consistent()

    def test_historical_manufactured_date_with_explicit_start(self):
        made = self.today - datetime.timedelta(days=1)
        raw_lot = self.receive(self.raw, "10", "r1", day=made)
        batch = self.batch(self.semi, manufactured_date=made)
        self.use(batch, raw_lot, "5", "u1", occurred_at=made)
        lot = self.output(batch, "500", "o1", occurred_at=made).lot
        self.assertEqual(lot.lot_number, f"{made:%y%m%d}A")
        with patch("apps.inventory.document_bridge.batch_started") as hook:
            done = complete_batch(batch_id=batch.pk, staff_id=self.staff.pk)
        hook.assert_not_called()  # already created by explicit start
        self.assertEqual(done.manufactured_date, made)
        self.assertIsNotNone(done.started_at)

    def test_lot_date_is_the_production_start_date(self):
        # 사후 입력인데 제조일(생산 시작일)이 없으면 산출 불가 — 산출일로 대신하지 않는다
        batch = self.batch(self.semi, manufactured_date=None)
        with self.assertRaises(InventoryError):
            self.output(batch, "10", "o1")
        # 시작하면 시작일이 제조일. 며칠 뒤 산출해도 LOT·소비기한은 시작일 기준
        self.receive(self.raw, "1", "start-supply")
        started = self.today - datetime.timedelta(days=3)
        start_batch(
            batch_id=batch.pk,
            staff_id=self.staff.pk,
            started_at=datetime.datetime.combine(started, datetime.time(9), tzinfo=KST),
        )
        lot = self.output(batch, "10", "o1").lot
        self.assertEqual(lot.lot_number, f"{started:%y%m%d}A")
        self.assertEqual(lot.manufactured_date, started)
        # 365일 품목, 하루 전
        self.assertEqual(lot.expiration_date, started + datetime.timedelta(days=364))
        # 산출일이 제조일보다 빠를 수 없음
        late = self.batch(self.semi, manufactured_date=self.today)
        with self.assertRaises(InventoryError):
            self.output(late, "1", "o2", occurred_at=started)

    def test_start_date_cannot_be_after_the_start(self):
        batch = self.batch(self.semi, manufactured_date=self.today)
        with self.assertRaises(InventoryError):
            start_batch(
                batch_id=batch.pk,
                staff_id=self.staff.pk,
                started_at=datetime.datetime.combine(
                    self.today - datetime.timedelta(days=1), datetime.time(9), tzinfo=KST
                ),
            )

    def test_complete_needs_output_and_closed_batches_take_nothing(self):
        raw_lot = self.receive(self.raw, "10", "r1")
        batch = self.batch(self.semi)
        with self.assertRaises(InventoryError):
            complete_batch(batch_id=batch.pk, staff_id=self.staff.pk)
        self.use(batch, raw_lot, "1", "required-input")
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
            self.batch(self.finished)  # 판매 단위 완제품으로 제조하지 않음 (MVP, 10/15)
        with self.assertRaises(InventoryError):
            self.batch(self.semi, process="PACKAGING")  # 포장배치는 범위 밖
        with self.assertRaises(InventoryError):
            self.batch(self.semi, process="MIXING")
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
        with self.assertRaises(InventoryError):  # 다른 배치가 같은 번호를 쓸 수 없음
            self.output(self.batch(self.semi), "5", "o2", lot_number="OLD-SEMI-1")


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


class AlternativeAndSemiLotTests(ProductionTestCase):
    def test_semi_sequence_without_abbreviation(self):
        self.semi.short_code = None
        self.semi.save(update_fields=["short_code"])
        first = self.output(self.batch(self.semi), "1", "a").lot
        second = self.output(self.batch(self.semi), "1", "b").lot
        self.assertEqual(first.lot_number, f"{self.today:%y%m%d}A")
        self.assertEqual(second.lot_number, f"{self.today:%y%m%d}B")

    def test_alternative_conversion_and_correction(self):
        alternate = Item.objects.create(
            item_code="1000099",
            item_type_id="RAW",
            name="가상 대체 원료",
            short_code="AXX",
            base_unit="g",
        )
        bom = Bom.objects.create(
            item=self.semi, version=1, base_quantity_e6=to_e6(1000), effective_from=self.today
        )
        line = BomLine.objects.create(
            bom=bom, line_no=1, component_item=self.raw, quantity_e6=to_e6(1)
        )
        BomLineAlternative.objects.create(bom_line=line, item=alternate)
        batch = self.batch(self.semi)
        lot = self.receive(alternate, "1000", "alt")
        usage = self.use(batch, lot, "500", "use-alt", bom_line_id=line.pk)
        self.output(batch, "1000", "out-alt")
        self.assertEqual(
            batch_summary(batch.pk)["bom_check"]["lines"][0]["actual_e6"], to_e6("0.5")
        )
        correct_movement(
            movement_id=usage.stock_movement_id,
            quantity="100",
            staff_id=self.staff.pk,
            reason="투입 정정",
            idempotency_key="correct-alt",
        )
        self.assertEqual(
            batch_summary(batch.pk)["bom_check"]["lines"][0]["actual_e6"], to_e6("0.4")
        )
        outside = self.receive(self.pouch, "10", "outside")
        with self.assertRaises(InventoryError):
            self.use(batch, outside, "1", "reject-alt", bom_line_id=line.pk)
        self.assert_consistent()


class NonStockComponentTests(ProductionTestCase):
    """정제수 같은 공정용수: 재고 아님 (10/14 PM 미팅 C1)."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.water = Item.objects.create(
            item_code="1000098",
            item_type_id="RAW",
            name="가상 정제수",
            base_unit="kg",
            is_stock_managed=False,
        )

    def test_no_receipt_and_no_lot(self):
        with self.assertRaises(InventoryError):
            self.receive(self.water, "10", "w1")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Lot.objects.create(
                    item=self.water, lot_number="X", lot_kind="INCOMING", status="AVAILABLE"
                )

    def test_bom_check_leaves_the_actual_empty(self):
        bom = Bom.objects.create(
            item=self.semi, version=1, base_quantity_e6=to_e6(1000), effective_from=self.today
        )
        BomLine.objects.create(bom=bom, line_no=1, component_item=self.raw, quantity_e6=to_e6(1))
        BomLine.objects.create(bom=bom, line_no=2, component_item=self.water, quantity_e6=to_e6(9))
        batch = self.batch(self.semi)
        self.use(batch, self.receive(self.raw, "10", "r1"), "1", "u1")
        self.output(batch, "1000", "o1")
        lines = batch_summary(batch.pk)["bom_check"]["lines"]
        self.assertEqual(
            [(row["actual_e6"], row["stock_managed"]) for row in lines],
            [(to_e6(1), True), (None, False)],
        )

    def test_item_with_lots_cannot_become_non_stock(self):
        self.receive(self.raw, "1", "r1")
        self.raw.is_stock_managed = False
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.raw.save(update_fields=["is_stock_managed"])


class MvpBulkScopeTests(ProductionTestCase):
    """MVP = 입고 ~ 제조 벌크 산출 (10/15): 1 제조배치 = 1 산출 LOT, 포장배치 제외."""

    def sql(self, statement, params=()):
        with connection.cursor() as cursor:
            cursor.execute(statement, params)

    def test_lot_number_and_expiration_are_set_by_the_first_output(self):
        batch = self.batch(self.semi)
        expires = self.today + datetime.timedelta(days=30)
        lot = self.output(batch, "5", "o1", lot_number="OLD-1", expiration_date=expires).lot
        self.assertEqual(self.output(batch, "5", "o2", lot_number="OLD-1").lot, lot)
        self.assertEqual(self.output(batch, "5", "o3", expiration_date=expires).lot, lot)
        later = expires + datetime.timedelta(days=1)
        for extra in ({"lot_number": "OLD-2"}, {"expiration_date": later}):
            with self.subTest(extra), self.assertRaises(InventoryError):
                self.output(batch, "5", "o4", **extra)
        self.assertEqual(self.stock(lot), to_e6(15))
        self.assertEqual(Lot.objects.filter(item=self.semi).count(), 1)

    def test_database_keeps_one_lot_per_batch_and_no_new_packaging(self):
        first = self.batch(self.semi)
        lot = self.output(first, "5", "o1").lot
        other = self.output(self.batch(self.semi), "5", "o2").lot
        movement = StockMovement.objects.create(
            lot=other,
            movement_type_id="PRODUCTION_OUTPUT",
            quantity_e6=to_e6(1),
            staff=self.staff,
            occurred_at=kst_now(),
            idempotency_key="raw-1",
        )
        checks = [
            # another LOT for the first batch
            (
                "INSERT INTO production_outputs (batch_id, lot_id, quantity_e6, stock_movement_id)"
                " VALUES (%s, %s, %s, %s)",
                [first.pk, other.pk, to_e6(1), movement.pk],
            ),
            # a new packaging batch, or turning a batch into one
            (
                "INSERT INTO production_batches (batch_number, process_type, item_id, status,"
                " staff_id) VALUES ('B-X', 'PACKAGING', %s, 'PLANNED', %s)",
                [self.semi.pk, self.staff.pk],
            ),
            (
                "UPDATE production_batches SET process_type = 'PACKAGING' WHERE id = %s",
                [first.pk],
            ),
        ]
        for statement, params in checks:
            with self.subTest(statement[:50]), self.assertRaises(IntegrityError):
                with transaction.atomic():
                    self.sql(statement, params)
        third = self.batch(self.semi)
        movement3 = StockMovement.objects.create(
            lot=lot,
            movement_type_id="PRODUCTION_OUTPUT",
            quantity_e6=to_e6(1),
            staff=self.staff,
            occurred_at=kst_now(),
            idempotency_key="raw-2",
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.sql(
                "INSERT INTO production_outputs (batch_id, lot_id, quantity_e6, stock_movement_id)"
                " VALUES (%s, %s, %s, %s)",
                [third.pk, lot.pk, to_e6(1), movement3.pk],
            )

    def test_legacy_packaging_batch_only_closes(self):
        # 0006 전에 만들어진 포장배치: 남아 있고 조회·취소는 되지만 작업은 더할 수 없다
        self.sql("DROP TRIGGER trg_batches_no_packaging")  # rolled back with the test
        legacy = ProductionBatch.objects.create(
            batch_number="B-4000001-261001A",
            process_type="PACKAGING",
            item=self.finished,
            status=BatchStatus.PLANNED,
            manufactured_date=self.today,
            staff=self.staff,
        )
        raw_lot = self.receive(self.raw, "10", "r1")
        for action in (
            lambda: start_batch(batch_id=legacy.pk, staff_id=self.staff.pk),
            lambda: self.use(legacy, raw_lot, "1", "u1"),
            lambda: self.output(legacy, "1", "o1"),
        ):
            with self.assertRaises(InventoryError):
                action()
        self.assertEqual(batch_summary(legacy.pk)["batch"].process_type, "PACKAGING")
        cancelled = cancel_batch(batch_id=legacy.pk, staff_id=self.staff.pk, reason="범위 제외")
        self.assertEqual(cancelled.status, BatchStatus.CANCELLED)

    def test_legacy_batch_with_several_lots_takes_no_more_output(self):
        batch = self.batch(self.semi)
        self.output(batch, "5", "o1")
        self.sql("DROP TRIGGER trg_outputs_one_lot_per_batch")  # 0006 전 기록 흉내
        extra = Lot.objects.create(
            lot_number="OLD-B",
            item=self.semi,
            lot_kind=LotKind.PRODUCED,
            status=LotStatus.AVAILABLE,
            manufactured_date=self.today,
        )
        movement = StockMovement.objects.create(
            lot=extra,
            movement_type_id="PRODUCTION_OUTPUT",
            quantity_e6=to_e6(1),
            staff=self.staff,
            occurred_at=kst_now(),
            idempotency_key="legacy-o2",
        )
        ProductionOutput.objects.create(
            batch=batch, lot=extra, quantity_e6=to_e6(1), stock_movement=movement
        )
        with self.assertRaises(InventoryError):
            self.output(batch, "1", "o3")
        summary = batch_summary(batch.pk)
        self.assertIsNone(summary["output_lot"])
        self.assertEqual(len({row["lot_id"] for row in summary["outputs"]}), 2)
