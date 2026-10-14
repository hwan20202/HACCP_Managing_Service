import datetime
import tempfile
from decimal import Decimal
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.test import SimpleTestCase, TestCase

from .errors import InventoryError
from .fields import KST, kst_now, parse_kst_text, to_kst_text
from .lot_numbers import LotNumberError, next_lot_number, render, seq_to_letters
from .master_import import MasterImportError, ensure_default_lot_rules, import_items
from .models import (
    AppendOnlyError,
    AuditLog,
    BatchStatus,
    IncomingReceipt,
    Inventory,
    Item,
    ItemType,
    Lot,
    LotKind,
    LotNumberRule,
    LotStatus,
    ProcessType,
    ProductionBatch,
    ReceiptStatus,
    Staff,
    StockMovement,
    StockMovementType,
    Supplier,
)
from .movements import correct_movement
from .quantity import from_e6, to_e6
from .receiving import ReceiptInput, ReceivingError, cancel_receipt, register_receipt
from .shelf_life import add_months, expiration_for
from .sql_runner import read_sql, split_statements

CORE_TABLES = {
    "item_types",
    "stock_movement_types",
    "hold_source_types",
    "hold_dispositions",
    "staff",
    "suppliers",
    "items",
    "lots",
    "lot_number_rules",
    "lot_number_sequences",
    "stock_movements",
    "inventory",
    "incoming_receipts",
    "holds",
    "audit_logs",
    # 0002_production.sql
    "boms",
    "bom_lines",
    "production_batches",
    "production_material_usages",
    "production_outputs",
}


def fetch_one(sql, params=()):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchone()


def fetch_all(sql, params=()):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall()


class QuantityTests(SimpleTestCase):
    def test_examples_from_rule_s3(self):
        self.assertEqual(to_e6(50), 50_000_000)
        self.assertEqual(to_e6("0.25"), 250_000)
        self.assertEqual(to_e6(Decimal("12354")), 12_354_000_000)

    def test_round_trip(self):
        for text in ["50", "0.25", "12354", "0.000001", "1.5"]:
            self.assertEqual(from_e6(to_e6(text)), Decimal(text))

    def test_rejects_float_and_excess_precision(self):
        with self.assertRaises(TypeError):
            to_e6(0.1)
        with self.assertRaises(ValueError):
            to_e6("0.0000001")
        with self.assertRaises(ValueError):
            to_e6("abc")


class KSTTextTests(SimpleTestCase):
    def test_aware_utc_is_written_as_kst_without_microseconds(self):
        value = datetime.datetime(2026, 10, 8, 23, 30, 15, 123456, tzinfo=datetime.UTC)
        self.assertEqual(to_kst_text(value), "2026-10-09 08:30:15")

    def test_naive_value_is_taken_as_kst(self):
        self.assertEqual(to_kst_text(datetime.datetime(2026, 10, 9, 8, 0)), "2026-10-09 08:00:00")

    def test_parse_returns_aware_kst(self):
        parsed = parse_kst_text("2026-10-09 08:30:15")
        self.assertEqual(parsed.tzinfo, KST)
        self.assertEqual(parsed.hour, 8)


class SplitStatementTests(SimpleTestCase):
    def test_trigger_bodies_stay_whole(self):
        statements = split_statements(read_sql("0001_core.sql"))
        triggers = [s for s in statements if "CREATE TRIGGER" in s]
        self.assertEqual(len(triggers), 6)
        self.assertTrue(all(t.rstrip().endswith("END;") for t in triggers))


class SchemaTests(TestCase):
    def test_core_tables_exist_and_are_strict(self):
        rows = dict(fetch_all("SELECT name, sql FROM sqlite_master WHERE type = 'table'"))
        self.assertTrue(CORE_TABLES.issubset(rows))
        for table in CORE_TABLES:
            self.assertTrue(rows[table].rstrip().endswith("STRICT"), table)

    def test_triggers_and_views_exist(self):
        names = {name for (name,) in fetch_all("SELECT name FROM sqlite_master")}
        for name in [
            "trg_sm_no_update",
            "trg_sm_no_delete",
            "trg_sm_inventory",
            "trg_sm_correction_lot",
            "trg_items_type_locked",
            "trg_lots_updated_at",
            "v_lot_availability",
            "v_doc_incoming_lot",
            "v_stock_ledger",
            "v_inventory_mismatch",
            "v_batch_usages",
            "v_batch_outputs",
            "v_lot_trace",
            "v_doc_batch",
        ]:
            self.assertIn(name, names)

    def test_ledger_view_has_0002_columns(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM v_stock_ledger LIMIT 0")
            columns = [column[0] for column in cursor.description]
        self.assertEqual(columns[-4:], ["lot_id", "item_id", "receipt_id", "batch_id"])

    def test_production_models_map_to_tables(self):
        staff = Staff.objects.create(staff_code="S900", name="x")
        item = Item.objects.create(
            item_type_id="SEMI", item_code="3000900", name="시험반제품", base_unit="개"
        )
        batch = ProductionBatch.objects.create(
            batch_number="B-3000900-261009A",
            process_type=ProcessType.MANUFACTURE,
            item=item,
            status=BatchStatus.PLANNED,
            staff=staff,
        )
        row = fetch_one(
            "SELECT production_batch_id, status FROM v_doc_batch WHERE batch_number = %s",
            [batch.batch_number],
        )
        self.assertEqual(row, (batch.pk, "PLANNED"))
        with self.assertRaises(IntegrityError), transaction.atomic():
            batch.delete()  # cancel instead (trigger)

    def test_reference_codes_are_seeded(self):
        self.assertEqual(ItemType.objects.count(), 4)
        self.assertEqual(StockMovementType.objects.count(), 12)
        self.assertEqual(StockMovementType.objects.get(code="RECEIPT").direction, 1)

    def test_connection_rules(self):
        self.assertEqual(fetch_one("PRAGMA foreign_keys")[0], 1)  # S1
        self.assertEqual(settings.DATABASES["default"]["OPTIONS"]["transaction_mode"], "IMMEDIATE")

    def test_strict_rejects_wrong_type(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            fetch_one("INSERT INTO staff (staff_code, name, is_active) VALUES ('S9', 'x', 'yes')")


class StockFixtureMixin:
    @classmethod
    def setUpTestData(cls):
        cls.staff = Staff.objects.create(staff_code="S001", name="홍길동")
        cls.item = Item.objects.create(
            item_type_id="RAW", item_code="1000019", name="테스트 원료", base_unit="kg"
        )
        cls.lot = Lot.objects.create(
            lot_number="1000019-261009A",
            item=cls.item,
            lot_kind=LotKind.INCOMING,
            status=LotStatus.QUARANTINE,
            expiration_date=datetime.date(2027, 10, 9),
        )
        cls.other_lot = Lot.objects.create(
            lot_number="1000019-261009B",
            item=cls.item,
            lot_kind=LotKind.INCOMING,
            status=LotStatus.QUARANTINE,
        )

    def move(self, code, quantity, lot=None, key=None, **extra):
        return StockMovement.objects.create(
            lot=lot or self.lot,
            movement_type_id=code,
            quantity_e6=to_e6(quantity),
            staff=self.staff,
            occurred_at=kst_now(),
            idempotency_key=key or f"{code}-{StockMovement.objects.count()}",
            **extra,
        )

    def stock(self, lot=None):
        return Inventory.objects.get(lot=lot or self.lot).quantity_e6

    def assert_no_mismatch(self):
        self.assertEqual(fetch_all("SELECT * FROM v_inventory_mismatch"), [])


class LotNumberUniqueTests(StockFixtureMixin, TestCase):
    def test_lot_number_is_unique_per_item(self):
        other = Item.objects.create(
            item_type_id="RAW", item_code="1000020", name="다른 원료", base_unit="kg"
        )
        values = {"lot_kind": LotKind.INCOMING, "status": LotStatus.QUARANTINE}
        Lot.objects.create(lot_number=self.lot.lot_number, item=other, **values)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Lot.objects.create(lot_number=self.lot.lot_number, item=self.item, **values)

    def test_status_is_quality_only(self):
        for status in ["CONSUMED", "DISPOSED"]:
            with self.subTest(status=status), self.assertRaises(IntegrityError):
                with transaction.atomic():
                    Lot.objects.filter(pk=self.lot.pk).update(status=status)


class ModelMappingTests(StockFixtureMixin, TestCase):
    def test_db_defaults_are_filled_by_sqlite(self):
        self.staff.refresh_from_db()
        self.assertIsInstance(self.staff.created_at, datetime.datetime)
        self.assertEqual(self.staff.created_at.tzinfo, KST)
        self.assertTrue(self.staff.is_active)

    def test_datetime_is_stored_as_kst_text(self):
        utc = datetime.datetime(2026, 10, 8, 23, 30, 15, 999999, tzinfo=datetime.UTC)
        movement = StockMovement.objects.create(
            lot=self.lot,
            movement_type_id="RECEIPT",
            quantity_e6=to_e6(1),
            staff=self.staff,
            occurred_at=utc,
            idempotency_key="kst-1",
        )
        raw = fetch_one("SELECT occurred_at FROM stock_movements WHERE id = %s", [movement.pk])
        self.assertEqual(raw[0], "2026-10-09 08:30:15")
        self.assertEqual(
            StockMovement.objects.filter(occurred_at__gte=utc.replace(microsecond=0)).count(), 1
        )

    def test_dates_round_trip(self):
        self.lot.refresh_from_db()
        self.assertEqual(self.lot.expiration_date, datetime.date(2027, 10, 9))


class InvariantTests(StockFixtureMixin, TestCase):
    def test_i3_inventory_follows_movements(self):
        self.move("RECEIPT", "50")
        self.move("ADJUST_OUT", "0.25", reason="실사 차이")
        self.assertEqual(self.stock(), to_e6("49.75"))
        self.assert_no_mismatch()

    def test_i3_negative_stock_rejects_the_movement(self):
        self.move("RECEIPT", "10")
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.move("ADJUST_OUT", "10.000001", reason="초과 출고")
        self.assertEqual(self.stock(), to_e6("10"))
        self.assertEqual(StockMovement.objects.count(), 1)

    def test_i1_quantity_must_be_positive(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.move("RECEIPT", "0")

    def test_i2_database_blocks_update_and_delete(self):
        movement = self.move("RECEIPT", "5")
        with self.assertRaises(IntegrityError), transaction.atomic():
            fetch_one("UPDATE stock_movements SET quantity_e6 = 1 WHERE id = %s", [movement.pk])
        with self.assertRaises(IntegrityError), transaction.atomic():
            fetch_one("DELETE FROM stock_movements WHERE id = %s", [movement.pk])

    def test_i2_orm_blocks_update_and_delete(self):
        movement = self.move("RECEIPT", "5")
        with self.assertRaises(AppendOnlyError):
            movement.save()
        with self.assertRaises(AppendOnlyError):
            movement.delete()
        with self.assertRaises(AppendOnlyError):
            StockMovement.objects.filter(pk=movement.pk).update(reason="x")
        with self.assertRaises(AppendOnlyError):
            StockMovement.objects.all().delete()

    def test_i3_orm_cannot_write_inventory(self):
        self.move("RECEIPT", "5")
        inventory = Inventory.objects.get(lot=self.lot)
        with self.assertRaises(AppendOnlyError):
            inventory.save()
        with self.assertRaises(AppendOnlyError):
            Inventory.objects.update(quantity_e6=0)

    def test_correction_rules(self):
        receipt = self.move("RECEIPT", "5")
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.move("CORRECTION_OUT", "5", reason="취소")  # no corrects_movement
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.move("ADJUST_OUT", "1")  # adjustment without reason
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.move(
                "CORRECTION_OUT", "5", lot=self.other_lot, corrects_movement=receipt, reason="x"
            )
        self.move("CORRECTION_OUT", "5", corrects_movement=receipt, reason="입고 취소")
        self.assertEqual(self.stock(), 0)
        self.assert_no_mismatch()

    def test_i4_item_type_locked_after_lots(self):
        self.item.item_type_id = "SEMI"
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.item.save()

    def test_foreign_keys_are_enforced(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            fetch_one(
                "INSERT INTO lots (lot_number, item_id, lot_kind, status) "
                "VALUES ('X', 999999, 'INCOMING', 'QUARANTINE')"
            )

    def test_datetime_check_rejects_microseconds(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            fetch_one(
                "INSERT INTO stock_movements (lot_id, movement_type_code, quantity_e6, staff_id, "
                "occurred_at, idempotency_key) VALUES (%s, 'RECEIPT', 1, %s, "
                "'2026-10-09 08:00:00.123', 'raw-1')",
                [self.lot.pk, self.staff.pk],
            )

    def test_stock_ledger_running_balance(self):
        self.move("RECEIPT", "50", key="a")
        self.move("ADJUST_OUT", "20", reason="사용", key="b")
        rows = fetch_all(
            "SELECT movement_code, signed_quantity_e6, lot_balance_e6 FROM v_stock_ledger "
            "WHERE lot_number = %s ORDER BY occurred_at, movement_id",
            [self.lot.lot_number],
        )
        self.assertEqual(
            rows,
            [("RECEIPT", to_e6(50), to_e6(50)), ("ADJUST_OUT", -to_e6(20), to_e6(30))],
        )

    def test_lot_availability_view(self):
        usable = fetch_one(
            "SELECT is_usable FROM v_lot_availability WHERE lot_id = %s", [self.lot.pk]
        )
        self.assertEqual(usable[0], 0)  # QUARANTINE
        self.lot.status = LotStatus.AVAILABLE
        self.lot.save()
        usable = fetch_one(
            "SELECT is_usable FROM v_lot_availability WHERE lot_id = %s", [self.lot.pk]
        )
        self.assertEqual(usable[0], 1)


class ReadinessTests(TestCase):
    def test_missing_core_table_is_not_ready(self):
        tables = [t for t in connection.introspection.table_names() if t != "lots"]
        with patch("apps.core.views.connection.introspection.table_names", return_value=tables):
            self.assertEqual(self.client.get("/health/ready/").status_code, 503)


class SeqLetterTests(SimpleTestCase):
    def test_bijective_letters(self):
        cases = {1: "A", 2: "B", 26: "Z", 27: "AA", 52: "AZ", 53: "BA", 702: "ZZ", 703: "AAA"}
        for number, letters in cases.items():
            self.assertEqual(seq_to_letters(number), letters)


class LotNumberTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_default_lot_rules()
        cls.item = Item.objects.create(
            item_type_id="RAW",
            item_code="1000019",
            short_code="ATS",
            name="테스트 원료",
            base_unit="kg",
        )
        cls.day = datetime.date(2026, 10, 9)

    def draw(self, item=None, day=None, kind=LotKind.INCOMING):
        return next_lot_number(lot_kind=kind, item=item or self.item, base_date=day or self.day)

    def item_of(self, item_type, code, short_code=None):
        return Item.objects.create(
            item_type_id=item_type,
            item_code=code,
            short_code=short_code,
            name=f"테스트 {code}",
            base_unit="개",
        )

    def test_incoming_is_short_code_and_date_with_suffix_from_the_second(self):
        self.assertEqual(self.draw(), "ATS261009")
        self.assertEqual(self.draw(), "ATS261009-2")
        self.assertEqual(self.draw(), "ATS261009-3")
        self.assertEqual(self.draw(day=datetime.date(2026, 10, 10)), "ATS261010")
        key = fetch_one(
            "SELECT current_seq FROM lot_number_sequences WHERE seq_key = %s",
            ["1000019:ATS261009"],
        )
        self.assertEqual(key[0], 3)

    def test_skips_numbers_that_already_exist(self):
        Lot.objects.create(
            lot_number="ATS261009",
            item=self.item,
            lot_kind=LotKind.INCOMING,
            status=LotStatus.QUARANTINE,
        )
        self.assertEqual(self.draw(), "ATS261009-2")

    def test_item_type_rule_wins_over_generic_rule(self):
        LotNumberRule.objects.create(
            lot_kind=LotKind.INCOMING,
            item_type_id="RAW",
            pattern="R{item_code}{received:yyyyMMdd}-{seq:000}",
            effective_from=datetime.date(2026, 10, 1),
        )
        self.assertEqual(self.draw(), "R100001920261009-001")
        # Before the specific rule takes effect the generic rule applies.
        self.assertEqual(self.draw(day=datetime.date(2026, 9, 30)), "ATS260930")

    def test_semi_finished_lot_is_short_code_and_manufacturing_date(self):
        semi = self.item_of("SEMI", "3000019", "BTS")
        self.assertEqual(self.draw(semi, kind=LotKind.PRODUCED), "261009A")

    def test_finished_lot_is_date_and_sequence_per_product(self):
        # 근무조 폐지 (10/14): 제조일 + 품목별 생산 순번
        first = self.item_of("FINISHED", "4000019")
        second = self.item_of("FINISHED", "4000020")
        produced = LotKind.PRODUCED
        self.assertEqual(self.draw(first, kind=produced), "261009A")
        # Another product on the same day gets the same number (read with its code).
        self.assertEqual(self.draw(second, kind=produced), "261009A")
        self.assertEqual(self.draw(first, kind=produced), "261009B")

    def test_purchased_semi_lot_is_date_and_sequence(self):
        # 반제품 입고 (10/14 D2): 약어 없이 입고일 + 순번 (가정)
        semi = self.item_of("SEMI", "3000020")
        self.assertEqual(self.draw(semi), "261009A")
        self.assertEqual(self.draw(semi), "261009B")

    def test_shift_token_is_gone(self):
        with self.assertRaises(LotNumberError):
            render("{date:yyMMdd}{shift}{seq:-N}", item=self.item, base_date=self.day, seq=1)

    def test_missing_short_code_is_an_error(self):
        with self.assertRaises(LotNumberError):
            self.draw(self.item_of("RAW", "1000020"))

    def test_date_and_received_tokens_are_the_same(self):
        new = render("{item_code}-{date:yyMMdd}{seq:A}", item=self.item, base_date=self.day, seq=1)
        old = render(
            "{item_code}-{received:yyMMdd}{seq:A}", item=self.item, base_date=self.day, seq=1
        )
        self.assertEqual(new, old)

    def test_no_rule_is_an_error(self):
        LotNumberRule.objects.update(is_active=False)
        with self.assertRaises(LotNumberError):
            self.draw()

    def test_invalid_patterns(self):
        for pattern in ["{item_code}", "{item_code}{seq:A}{seq:A}", "{nope}{seq:A}", "{seq:X}"]:
            with self.assertRaises(LotNumberError, msg=pattern):
                render(pattern, item=self.item, base_date=self.day, seq=1)

    def test_must_run_inside_a_transaction(self):
        with patch("apps.inventory.lot_numbers.connection.in_atomic_block", False):
            with self.assertRaises(LotNumberError):
                self.draw()


class MasterImportTests(TestCase):
    def test_sample_command_loads_and_is_idempotent(self):
        out = StringIO()
        call_command("seed_master", "--sample", stdout=out)
        self.assertIn("staff: created 3, updated 0", out.getvalue())
        self.assertIn("created default INCOMING rule", out.getvalue())
        self.assertIn("created default INCOMING SEMI rule", out.getvalue())
        self.assertIn("created default PRODUCED SEMI rule", out.getvalue())
        self.assertIn("created default PRODUCED FINISHED rule", out.getvalue())
        call_command("seed_master", "--sample", stdout=(out := StringIO()))
        self.assertIn("items: created 0, updated 6", out.getvalue())
        self.assertEqual(LotNumberRule.objects.count(), 4)
        self.assertFalse(LotNumberRule.objects.filter(pattern__contains="{shift}").exists())
        self.assertEqual(Item.objects.get(item_code="1000002").minimum_stock_e6, to_e6("20.5"))

    def test_dry_run_saves_nothing(self):
        call_command("seed_master", "--sample", "--dry-run", stdout=StringIO())
        self.assertEqual(Staff.objects.count(), 0)
        self.assertEqual(LotNumberRule.objects.count(), 0)

    def test_invalid_rows_reject_the_whole_file(self):
        rows = [
            {"item_code": "1", "item_type": "RAW", "name": "a", "base_unit": "kg"},
            {"item_code": "2", "item_type": "XXX", "name": "b", "base_unit": "kg"},
            {"item_code": "3", "item_type": "RAW", "name": "", "base_unit": "kg"},
            {"item_code": "1", "item_type": "RAW", "name": "c", "base_unit": "kg"},
            {
                "item_code": "4",
                "item_type": "RAW",
                "name": "d",
                "base_unit": "kg",
                "minimum_stock": "0.0000001",
            },
        ]
        with self.assertRaises(MasterImportError) as caught:
            import_items(rows)
        self.assertEqual(len(caught.exception.errors), 4)
        self.assertIn("line 3", caught.exception.errors[0])
        self.assertEqual(Item.objects.count(), 0)

    def test_csv_import_with_cp949(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "staff.csv"
            path.write_text("staff_code,name,is_active\nS100,가상직원,N\n", encoding="cp949")
            call_command(
                "seed_master", "--staff", str(path), "--encoding", "cp949", stdout=StringIO()
            )
        staff = Staff.objects.get(staff_code="S100")
        self.assertEqual(staff.name, "가상직원")
        self.assertFalse(staff.is_active)

    def test_item_type_change_after_lot_is_reported(self):
        call_command("seed_master", "--sample", stdout=StringIO())
        item = Item.objects.get(item_code="1000001")
        Lot.objects.create(
            lot_number="L1", item=item, lot_kind=LotKind.INCOMING, status=LotStatus.QUARANTINE
        )
        rows = [{"item_code": "1000001", "item_type": "SEMI", "name": "x", "base_unit": "kg"}]
        with self.assertRaises(MasterImportError) as caught:
            import_items(rows)
        self.assertIn("DB 제약 위반", caught.exception.errors[0])


class ReceivingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_master", "--sample", stdout=StringIO())
        cls.item = Item.objects.get(item_code="1000001")
        cls.supplier = Supplier.objects.get(supplier_code="V001")
        cls.staff = Staff.objects.get(staff_code="S001")
        cls.today = kst_now().date()

    def receive(self, key="k1", **overrides):
        values = {
            "item_id": self.item.pk,
            "supplier_id": self.supplier.pk,
            "staff_id": self.staff.pk,
            "received_date": self.today,
            "quantity": "50",
            "idempotency_key": key,
            "supplier_lot_number": "SUP-001",
            "manufactured_date": datetime.date(2026, 9, 1),
            "expiration_date": datetime.date(2027, 9, 1),
        }
        values.update(overrides)
        return register_receipt(ReceiptInput(**values))

    def test_register_creates_lot_movement_receipt_and_audit(self):
        receipt = self.receive()
        lot = receipt.lot
        self.assertEqual(lot.status, LotStatus.QUARANTINE)
        # 소비기한 있는 원료: 약어 + 소비기한 (2027-09-01) (0007)
        self.assertEqual((lot.lot_number, lot.expiration_status), ("AGA270901", "KNOWN"))
        self.assertEqual(receipt.stock_movement.movement_type_id, "RECEIPT")
        self.assertEqual(Inventory.objects.get(lot=lot).quantity_e6, to_e6(50))
        self.assertEqual(AuditLog.objects.get(record_id=str(receipt.pk)).action, "INSERT")
        row = fetch_one(
            "SELECT lot_number, supplier_name, quantity_e6, lot_status, receipt_status "
            "FROM v_doc_incoming_lot WHERE lot_id = %s",
            [lot.pk],
        )
        self.assertEqual(
            row, (lot.lot_number, "가상원료상사", to_e6(50), "QUARANTINE", "COMPLETED")
        )
        self.assertEqual(fetch_all("SELECT * FROM v_inventory_mismatch"), [])

    def test_judgment_with_receipt_is_applied_in_the_same_transaction(self):
        passed = self.receive("k1", judgment="PASS").lot
        failed = self.receive("k2", judgment="FAIL").lot
        self.assertEqual((passed.status, failed.status), (LotStatus.AVAILABLE, LotStatus.REJECTED))
        log = AuditLog.objects.get(table_name="lots", record_id=str(failed.pk))
        self.assertEqual(log.before_json, {"status": "QUARANTINE"})
        self.assertEqual(log.after_json["judgment"], "FAIL")
        with self.assertRaises(ReceivingError):
            self.receive("k3", judgment="CONDITIONAL")
        self.assertEqual(Lot.objects.count(), 2)

    def test_doc_view_covers_every_lot(self):
        receipt = self.receive()
        produced = Lot.objects.create(
            lot_number="4000099-261009A",
            item=Item.objects.create(
                item_type_id="FINISHED", item_code="4000099", name="시험완제품", base_unit="개"
            ),
            lot_kind=LotKind.PRODUCED,
            status=LotStatus.AVAILABLE,
            manufactured_date=datetime.date(2026, 10, 9),
        )
        rows = {
            row[0]: row[1:]
            for row in fetch_all(
                "SELECT lot_id, lot_kind, item_type_name, supplier_name, received_date,"
                " receipt_status, subject_label FROM v_doc_incoming_lot"
            )
        }
        self.assertEqual(rows[receipt.lot_id][:2], ("INCOMING", "원료"))
        self.assertEqual(
            rows[produced.pk],
            (
                "PRODUCED",
                "완제품",
                None,
                None,
                None,
                "4000099 시험완제품 / 4000099-261009A / 2026-10-09",
            ),
        )

    def test_second_receipt_same_day_gets_suffix(self):
        # 소비기한 있는 원료는 소비기한으로 채번 (0007).
        # 같은 소비기한이 또 들어오면 -2 (입고 1건 = LOT 1개)
        self.receive("k1")
        self.assertEqual(self.receive("k2").lot.lot_number, "AGA270901-2")
        none = self.receive("k3", expiration_date=None, expiration_status="NONE").lot
        self.assertEqual(none.lot_number, f"AGA{self.today:%y%m%d}")

    def test_late_entry_is_dated_at_start_of_received_day(self):
        day = self.today - datetime.timedelta(days=3)
        receipt = self.receive(received_date=day)
        self.assertEqual(
            receipt.stock_movement.occurred_at, datetime.datetime.combine(day, datetime.time(), KST)
        )
        with self.assertRaises(ReceivingError):
            self.receive("k2", received_date=self.today + datetime.timedelta(days=1))

    def test_same_key_returns_first_receipt(self):
        first = self.receive()
        self.assertEqual(self.receive().pk, first.pk)
        self.assertEqual(Lot.objects.count(), 1)
        with self.assertRaises(ReceivingError):
            self.receive(quantity="51")

    def test_invalid_requests_save_nothing(self):
        Supplier.objects.filter(pk=self.supplier.pk).update(is_active=False)
        finished = Item.objects.get(item_code="4000001")
        cases = [
            {"supplier_id": self.supplier.pk},
            {"item_id": finished.pk},
            {"item_id": 999999},
            {"quantity": "0"},
            {"quantity": "abc"},
            {"quantity": 1.5},
            {"expiration_date": datetime.date(2026, 8, 1)},
            {"idempotency_key": ""},
        ]
        for overrides in cases:
            with self.subTest(overrides), self.assertRaises(ReceivingError):
                self.receive(**{"key": "bad", **overrides})
        self.assertEqual(Lot.objects.count(), 0)
        self.assertEqual(StockMovement.objects.count(), 0)

    def test_document_notification_failure_rolls_back(self):
        target = "apps.inventory.document_bridge.incoming_received"
        with patch(target, side_effect=RuntimeError("down")), self.assertRaises(RuntimeError):
            self.receive()
        self.assertEqual(Lot.objects.count(), 0)
        self.assertEqual(IncomingReceipt.objects.count(), 0)
        with patch(target) as notify:
            receipt = self.receive()
        notify.assert_called_once_with(lot_id=receipt.lot_id)

    def test_cancel_offsets_stock_and_marks_receipt(self):
        receipt = self.receive()
        with patch("apps.inventory.document_bridge.incoming_receipt_cancelled") as notify:
            cancelled = cancel_receipt(
                receipt_id=receipt.pk, staff_id=self.staff.pk, reason="오입력"
            )
        notify.assert_called_once_with(
            lot_id=receipt.lot_id, reason="오입력", staff_id=self.staff.pk
        )
        self.assertEqual(cancelled.receipt_status, ReceiptStatus.CANCELLED)
        self.assertEqual(cancelled.cancel_reason, "오입력")
        self.assertEqual(Inventory.objects.get(lot=receipt.lot).quantity_e6, 0)
        correction = StockMovement.objects.get(movement_type_id="CORRECTION_OUT")
        self.assertEqual(correction.corrects_movement_id, receipt.stock_movement_id)
        self.assertEqual(
            AuditLog.objects.filter(record_id=str(receipt.pk)).order_by("pk").last().action,
            "UPDATE",
        )
        balances = fetch_all(
            "SELECT lot_balance_e6 FROM v_stock_ledger WHERE lot_number = %s "
            "ORDER BY occurred_at, movement_id",
            [receipt.lot.lot_number],
        )
        self.assertEqual(balances, [(to_e6(50),), (0,)])
        # Cancelling again changes nothing.
        cancel_receipt(receipt_id=receipt.pk, staff_id=self.staff.pk, reason="다시")
        self.assertEqual(StockMovement.objects.filter(lot=receipt.lot).count(), 2)

    def test_cancel_rules(self):
        receipt = self.receive()
        with self.assertRaises(ReceivingError):
            cancel_receipt(receipt_id=receipt.pk, staff_id=self.staff.pk, reason=" ")
        with self.assertRaises(ReceivingError):
            cancel_receipt(receipt_id=999999, staff_id=self.staff.pk, reason="x")
        StockMovement.objects.create(
            lot=receipt.lot,
            movement_type_id="ADJUST_OUT",
            quantity_e6=to_e6(1),
            staff=self.staff,
            occurred_at=kst_now(),
            reason="실사",
            idempotency_key="adj-1",
        )
        with self.assertRaises(ReceivingError):
            cancel_receipt(receipt_id=receipt.pk, staff_id=self.staff.pk, reason="x")
        receipt.refresh_from_db()
        self.assertEqual(receipt.receipt_status, ReceiptStatus.COMPLETED)

    def doc_quantities(self, lot):
        return fetch_one(
            "SELECT quantity_e6, net_quantity_e6, receipt_status FROM v_doc_incoming_lot "
            "WHERE lot_id = %s",
            [lot.pk],
        )

    def test_receipt_quantity_can_be_corrected_in_part(self):
        # 과거 수불도 수정 가능해야 함 (10/14 D3): LOT 번호는 그대로, 원래 입고 시각으로 정정
        receipt = self.receive()
        lot = receipt.lot
        correction = correct_movement(
            movement_id=receipt.stock_movement_id,
            quantity="5",
            reason="수량 오입력 (45kg)",
            staff_id=self.staff.pk,
            idempotency_key="fix-1",
        )
        self.assertEqual(correction.movement_type_id, "CORRECTION_OUT")
        self.assertEqual(correction.occurred_at, receipt.stock_movement.occurred_at)
        self.assertEqual(Inventory.objects.get(lot=lot).quantity_e6, to_e6(45))
        self.assertEqual(self.doc_quantities(lot), (to_e6(50), to_e6(45), "COMPLETED"))
        with self.assertRaisesMessage(InventoryError, "입고 취소"):  # 0 이 되면 취소로
            correct_movement(
                movement_id=receipt.stock_movement_id,
                quantity="45",
                reason="x",
                staff_id=self.staff.pk,
                idempotency_key="fix-2",
            )
        # 취소는 정정 후 남은 수량을 뺀다
        cancel_receipt(receipt_id=receipt.pk, staff_id=self.staff.pk, reason="오입력")
        self.assertEqual(Inventory.objects.get(lot=lot).quantity_e6, 0)
        self.assertEqual(self.doc_quantities(lot), (to_e6(50), 0, "CANCELLED"))
        with self.assertRaises(InventoryError):
            correct_movement(
                movement_id=receipt.stock_movement_id,
                quantity="1",
                reason="x",
                staff_id=self.staff.pk,
                idempotency_key="fix-3",
            )
        self.assertEqual(fetch_all("SELECT * FROM v_inventory_mismatch"), [])

    def test_semi_finished_goods_can_be_received(self):
        # 반제품도 사 온다 (10/14 D2). 약어 없이 입고일 + 순번 (가정)
        semi = Item.objects.create(
            item_type_id="SEMI", item_code="3000099", name="구매 반제품", base_unit="kg"
        )
        first = self.receive(item_id=semi.pk).lot
        second = self.receive("k2", item_id=semi.pk).lot
        day = f"{self.today:%y%m%d}"
        self.assertEqual((first.lot_number, second.lot_number), (f"{day}A", f"{day}B"))
        self.assertEqual(first.lot_kind, LotKind.INCOMING)

    def test_non_stock_items_are_not_received(self):
        water = Item.objects.create(
            item_type_id="RAW",
            item_code="1000097",
            name="정제수",
            base_unit="kg",
            is_stock_managed=False,
        )
        with self.assertRaisesMessage(InventoryError, "재고 관리 대상이 아닌"):
            self.receive(item_id=water.pk)
        self.assertEqual(Lot.objects.count(), 0)


class ShelfLifeTests(SimpleTestCase):
    def test_months_keep_the_day_and_clamp_month_end(self):
        item = Item(shelf_life_months=24)
        # 라벨은 하루 전 (10/14 PM 미팅 B3)
        self.assertEqual(
            expiration_for(item, datetime.date(2026, 10, 13)), datetime.date(2028, 10, 12)
        )
        self.assertEqual(add_months(datetime.date(2026, 1, 31), 1), datetime.date(2026, 2, 28))
        self.assertEqual(add_months(datetime.date(2027, 2, 28), 12), datetime.date(2028, 2, 28))

    def test_days_and_missing(self):
        made = datetime.date(2026, 10, 13)
        self.assertEqual(
            expiration_for(Item(shelf_life_days=10), made), datetime.date(2026, 10, 22)
        )
        self.assertIsNone(expiration_for(Item(), made))
        self.assertIsNone(expiration_for(Item(shelf_life_months=1), None))


class ShelfLifeMasterTests(TestCase):
    def test_months_or_days_not_both(self):
        call_command("seed_master", "--sample", stdout=StringIO())
        finished = Item.objects.get(item_code="4000001")
        self.assertEqual((finished.shelf_life_months, finished.shelf_life_days), (24, None))
        row = {
            "item_code": "1000099",
            "item_type": "RAW",
            "name": "x",
            "base_unit": "kg",
            "shelf_life_months": "12",
            "shelf_life_days": "30",
        }
        with self.assertRaises(MasterImportError):
            import_items([row])
        with self.assertRaises(IntegrityError), transaction.atomic():
            Item.objects.filter(pk=finished.pk).update(shelf_life_days=30)
