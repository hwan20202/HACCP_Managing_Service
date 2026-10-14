"""Tests for ledger, stock and movement services (A1-A3)."""

import datetime
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase

from .errors import InventoryError, NotFound
from .fields import KST, kst_now
from .judgment import apply_incoming_judgment
from .ledger import stock_ledger, stock_ledger_changes_since
from .models import (
    AuditLog,
    IncomingReceipt,
    Inventory,
    Item,
    Lot,
    LotStatus,
    ReceiptStatus,
    Staff,
    StockMovement,
    Supplier,
)
from .movements import (
    adjust_stock,
    correct_movement,
    dispose,
    record_opening_balance,
    return_to_supplier,
)
from .quantity import to_e6
from .receiving import ReceiptInput, cancel_receipt, register_receipt
from .stock import item_stock, lot_stock


def at(day, hour=9):
    return datetime.datetime.combine(day, datetime.time(hour), tzinfo=KST)


class ServiceTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_master", "--sample", stdout=StringIO())
        cls.raw_a = Item.objects.get(item_code="1000001")
        cls.raw_b = Item.objects.get(item_code="1000002")
        cls.pouch = Item.objects.get(item_code="2000001")
        cls.finished = Item.objects.get(item_code="4000001")
        cls.supplier = Supplier.objects.get(supplier_code="V001")
        cls.staff = Staff.objects.get(staff_code="S001")
        cls.today = kst_now().date()
        cls.day1 = cls.today - datetime.timedelta(days=10)
        cls.day2 = cls.today - datetime.timedelta(days=5)

    def receive(self, item, quantity, day, key, expiration=None):
        return register_receipt(
            ReceiptInput(
                item_id=item.pk,
                supplier_id=self.supplier.pk,
                staff_id=self.staff.pk,
                received_date=day,
                quantity=quantity,
                idempotency_key=key,
                expiration_date=expiration,
                expiration_status=None if expiration else "NONE",  # 0007
            )
        )

    def opening(self, item, quantity, key, lot_number=None, **extra):
        return record_opening_balance(
            item_id=item.pk,
            quantity=quantity,
            staff_id=self.staff.pk,
            occurred_at=self.day1,
            idempotency_key=key,
            lot_number=lot_number,
            **extra,
        )

    def stock(self, lot):
        return Inventory.objects.get(lot=lot).quantity_e6

    def assert_consistent(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM v_inventory_mismatch")
            self.assertEqual(cursor.fetchall(), [])


class OpeningBalanceTests(ServiceTestCase):
    def test_opening_with_existing_lot_number(self):
        movement = self.opening(self.raw_a, "120.5", "o1", lot_number="OLD-001")
        lot = movement.lot
        self.assertEqual(
            (lot.lot_number, lot.lot_kind, lot.status), ("OLD-001", "INCOMING", "AVAILABLE")
        )
        self.assertEqual(movement.movement_type_id, "OPENING_BALANCE")
        self.assertEqual(movement.occurred_at, at(self.day1, 0))
        self.assertEqual(self.stock(lot), to_e6("120.5"))

    def test_blank_lot_number_uses_incoming_rule(self):
        # 원료: 소비기한 없음 -> 기준일(입고일 자리)로, 있음 -> 소비기한으로 채번 (0007)
        lot = self.opening(self.raw_a, "1", "o1", expiration_status="NONE").lot
        self.assertEqual(lot.lot_number, f"AGA{self.day1:%y%m%d}")
        self.assertEqual(lot.expiration_status, "NONE")
        dated = self.opening(self.raw_a, "1", "o2", expiration_date=datetime.date(2027, 3, 1)).lot
        self.assertEqual((dated.lot_number, dated.expiration_status), ("AGA270301", "KNOWN"))
        with self.assertRaises(InventoryError):  # 미확인으로는 원료 채번 불가
            self.opening(self.raw_a, "1", "o3")
        legacy = self.opening(self.raw_a, "1", "o4", lot_number="OLD-9").lot  # 기존 번호는 허용
        self.assertEqual(legacy.expiration_status, "UNKNOWN")

    def test_finished_goods_need_lot_number(self):
        with self.assertRaises(InventoryError):
            self.opening(self.finished, "10", "o1")
        lot = self.opening(self.finished, "10", "o2", lot_number="F-001").lot
        self.assertEqual(lot.lot_kind, "PRODUCED")

    def test_lot_number_is_per_item(self):
        self.opening(self.raw_a, "5", "o1", lot_number="OLD-001")
        self.assertEqual(
            self.opening(self.raw_b, "5", "o2", lot_number="OLD-001").lot.item, self.raw_b
        )

    def test_duplicate_lot_and_replay(self):
        first = self.opening(self.raw_a, "5", "o1", lot_number="OLD-001")
        self.assertEqual(self.opening(self.raw_a, "5", "o1", lot_number="OLD-001").pk, first.pk)
        with self.assertRaises(InventoryError):
            self.opening(self.raw_a, "5", "o2", lot_number="OLD-001")
        with self.assertRaises(InventoryError):
            self.opening(self.raw_a, "6", "o1", lot_number="OLD-001")

    def test_status_and_date_rules(self):
        with self.assertRaises(InventoryError):
            self.opening(self.raw_a, "5", "o1", status="DISPOSED")
        with self.assertRaises(InventoryError):
            record_opening_balance(
                item_id=self.raw_a.pk,
                quantity="1",
                staff_id=self.staff.pk,
                occurred_at=self.today + datetime.timedelta(days=1),
                idempotency_key="o2",
            )
        with self.assertRaises(NotFound):
            record_opening_balance(
                item_id=999999,
                quantity="1",
                staff_id=self.staff.pk,
                occurred_at=self.day1,
                idempotency_key="o3",
            )


class MovementTests(ServiceTestCase):
    def setUp(self):
        self.lot = self.receive(self.raw_a, "50", self.day1, "r1").lot

    def test_adjust_in_and_out(self):
        adjust_stock(
            lot_id=self.lot.pk,
            direction="IN",
            quantity="2",
            reason="실사 증가",
            staff_id=self.staff.pk,
            idempotency_key="a1",
        )
        adjust_stock(
            lot_id=self.lot.pk,
            direction="OUT",
            quantity="0.5",
            reason="실사 감소",
            staff_id=self.staff.pk,
            idempotency_key="a2",
        )
        self.assertEqual(self.stock(self.lot), to_e6("51.5"))
        self.assert_consistent()

    def test_adjust_requires_reason_direction_and_stock(self):
        base = {"lot_id": self.lot.pk, "staff_id": self.staff.pk, "quantity": "1"}
        with self.assertRaises(InventoryError):
            adjust_stock(**base, direction="OUT", reason=" ", idempotency_key="a1")
        with self.assertRaises(InventoryError):
            adjust_stock(**base, direction="SIDEWAYS", reason="x", idempotency_key="a2")
        with self.assertRaises(InventoryError):
            adjust_stock(
                **{**base, "quantity": "50.000001"},
                direction="OUT",
                reason="x",
                idempotency_key="a3",
            )
        self.assertEqual(StockMovement.objects.count(), 1)

    def test_backdated_outflow_cannot_make_history_negative(self):
        adjust_stock(
            lot_id=self.lot.pk,
            direction="OUT",
            quantity="40",
            reason="사용",
            staff_id=self.staff.pk,
            idempotency_key="a1",
            occurred_at=at(self.day2),
        )
        # Today 10 left, but between day1 and day2 there were 50: 45 at day1+1 would push
        # the day2 balance to -35.
        with self.assertRaises(InventoryError):
            adjust_stock(
                lot_id=self.lot.pk,
                direction="OUT",
                quantity="45",
                reason="x",
                staff_id=self.staff.pk,
                idempotency_key="a2",
                occurred_at=at(self.day1 + datetime.timedelta(days=1)),
            )
        adjust_stock(
            lot_id=self.lot.pk,
            direction="OUT",
            quantity="10",
            reason="x",
            staff_id=self.staff.pk,
            idempotency_key="a3",
            occurred_at=at(self.day1 + datetime.timedelta(days=1)),
        )
        self.assertEqual(self.stock(self.lot), 0)

    def test_full_return_empties_lot_and_keeps_status(self):
        movement = return_to_supplier(
            lot_id=self.lot.pk, reason="부적합 반품", staff_id=self.staff.pk, idempotency_key="ret1"
        )
        self.assertEqual(movement.quantity_e6, to_e6(50))
        self.lot.refresh_from_db()
        self.assertEqual(self.lot.status, LotStatus.QUARANTINE)  # status = quality only
        self.assertEqual(self.stock(self.lot), 0)
        self.assertFalse(AuditLog.objects.filter(table_name="lots").exists())
        # Replaying the same request returns the same movement even though stock is now 0.
        again = return_to_supplier(
            lot_id=self.lot.pk, reason="부적합 반품", staff_id=self.staff.pk, idempotency_key="ret1"
        )
        self.assertEqual(again.pk, movement.pk)
        with self.assertRaises(InventoryError):
            dispose(lot_id=self.lot.pk, reason="x", staff_id=self.staff.pk, idempotency_key="d1")

    def test_partial_disposal_keeps_status(self):
        dispose(
            lot_id=self.lot.pk,
            quantity="5",
            reason="파손",
            staff_id=self.staff.pk,
            idempotency_key="d1",
        )
        self.lot.refresh_from_db()
        self.assertEqual(self.lot.status, LotStatus.QUARANTINE)
        self.assertEqual(self.stock(self.lot), to_e6(45))

    def test_correct_disposal_restores_stock(self):
        disposal = dispose(
            lot_id=self.lot.pk, reason="오입력", staff_id=self.staff.pk, idempotency_key="d1"
        )
        correction = correct_movement(
            movement_id=disposal.pk,
            reason="폐기 아님",
            staff_id=self.staff.pk,
            idempotency_key="c1",
        )
        self.assertEqual(correction.movement_type_id, "CORRECTION_IN")
        self.assertEqual(correction.occurred_at, disposal.occurred_at)
        self.lot.refresh_from_db()
        self.assertEqual(self.lot.status, LotStatus.QUARANTINE)
        self.assertEqual(self.stock(self.lot), to_e6(50))
        with self.assertRaises(InventoryError):  # nothing left to correct
            correct_movement(
                movement_id=disposal.pk, reason="x", staff_id=self.staff.pk, idempotency_key="c2"
            )
        self.assert_consistent()

    def test_partial_correction_limits(self):
        adjustment = adjust_stock(
            lot_id=self.lot.pk,
            direction="IN",
            quantity="10",
            reason="실사",
            staff_id=self.staff.pk,
            idempotency_key="a1",
        )
        correct_movement(
            movement_id=adjustment.pk,
            quantity="4",
            reason="과다",
            staff_id=self.staff.pk,
            idempotency_key="c1",
        )
        with self.assertRaises(InventoryError):
            correct_movement(
                movement_id=adjustment.pk,
                quantity="6.5",
                reason="x",
                staff_id=self.staff.pk,
                idempotency_key="c2",
            )
        correct_movement(
            movement_id=adjustment.pk, reason="나머지", staff_id=self.staff.pk, idempotency_key="c3"
        )
        self.assertEqual(self.stock(self.lot), to_e6(50))

    def test_full_receipt_correction_is_a_cancellation(self):
        receipt_movement = StockMovement.objects.get(movement_type_id="RECEIPT")
        with self.assertRaisesMessage(InventoryError, "입고 취소"):
            correct_movement(
                movement_id=receipt_movement.pk,
                reason="x",
                staff_id=self.staff.pk,
                idempotency_key="c1",
            )
        with self.assertRaises(NotFound):
            correct_movement(
                movement_id=999999, reason="x", staff_id=self.staff.pk, idempotency_key="c2"
            )


class LedgerTests(ServiceTestCase):
    def setUp(self):
        self.old = self.opening(self.raw_a, "100", "o1", lot_number="OLD-001").lot
        self.new = self.receive(self.raw_a, "50", self.day2, "r1").lot
        adjust_stock(
            lot_id=self.old.pk,
            direction="OUT",
            quantity="30",
            reason="사용",
            staff_id=self.staff.pk,
            idempotency_key="a1",
            occurred_at=at(self.day2, 10),
        )
        self.receive(self.pouch, "1000", self.day2, "r2")

    def test_period_totals_with_opening_balance(self):
        start = self.day1 + datetime.timedelta(days=1)
        items = stock_ledger(start, self.today, item_type="RAW")
        self.assertEqual([item.item_code for item in items], ["1000001"])
        item = items[0]
        self.assertEqual([lot.lot_number for lot in item.lots], [self.new.lot_number, "OLD-001"])
        new, old = item.lots
        self.assertEqual(
            (old.opening_e6, old.in_e6, old.out_e6, old.closing_e6),
            (to_e6(100), 0, to_e6(30), to_e6(70)),
        )
        self.assertEqual((new.opening_e6, new.in_e6, new.closing_e6), (0, to_e6(50), to_e6(50)))
        self.assertEqual(item.closing_e6, to_e6(120))
        self.assertEqual([line.balance_e6 for line in old.lines], [to_e6(70)])

    def test_period_includes_first_day_and_last_day(self):
        items = stock_ledger(self.day1, self.day2, item_id=self.raw_a.pk)
        old = next(lot for lot in items[0].lots if lot.lot_number == "OLD-001")
        self.assertEqual(old.opening_e6, 0)
        self.assertEqual(
            [line.movement_code for line in old.lines], ["OPENING_BALANCE", "ADJUST_OUT"]
        )

    def test_lot_without_activity_but_with_balance_is_listed(self):
        later = self.today
        items = stock_ledger(later, later, item_type="RAW")
        lots = {lot.lot_number: lot for lot in items[0].lots}
        self.assertEqual(lots["OLD-001"].opening_e6, to_e6(70))
        self.assertEqual(lots["OLD-001"].lines, [])

    def test_cancelled_receipt_shows_both_lines(self):
        receipt = self.new.incoming_receipt
        cancel_receipt(receipt_id=receipt.pk, staff_id=self.staff.pk, reason="오입력")
        lot = next(
            lot for lot in stock_ledger(self.day2, self.today)[0].lots if lot.lot_id == self.new.pk
        )
        self.assertEqual([line.movement_code for line in lot.lines], ["RECEIPT", "CORRECTION_OUT"])
        self.assertEqual(lot.closing_e6, 0)

    def test_matches_view_running_balance(self):
        lines = {
            line.movement_id: line.balance_e6
            for item in stock_ledger(self.day1, self.today)
            for lot in item.lots
            for line in lot.lines
        }
        with connection.cursor() as cursor:
            cursor.execute("SELECT movement_id, lot_balance_e6 FROM v_stock_ledger")
            self.assertEqual(dict(cursor.fetchall()), lines)

    def test_invalid_period(self):
        with self.assertRaises(ValueError):
            stock_ledger(self.today, self.day1)


class StockQueryTests(ServiceTestCase):
    def setUp(self):
        soon = self.today + datetime.timedelta(days=10)
        self.quarantine = self.receive(self.raw_a, "30", self.day2, "r1", expiration=soon).lot
        self.usable = self.opening(
            self.raw_a,
            "15",
            "o1",
            lot_number="OLD-001",
            expiration_date=self.today + datetime.timedelta(days=100),
        ).lot
        self.rejected = self.opening(
            self.raw_b, "7", "o2", lot_number="OLD-B", status=LotStatus.REJECTED
        ).lot
        self.empty = self.opening(self.raw_b, "1", "o3", lot_number="OLD-C").lot
        dispose(lot_id=self.empty.pk, reason="소진", staff_id=self.staff.pk, idempotency_key="d1")

    def test_lot_stock_fefo_and_flags(self):
        lots = lot_stock(item_id=self.raw_a.pk)
        self.assertEqual([lot.lot_number for lot in lots], [self.quarantine.lot_number, "OLD-001"])
        self.assertFalse(lots[0].is_usable)
        self.assertEqual(lots[0].days_to_expiry, 10)
        self.assertEqual(lots[0].supplier_name, "가상원료상사")
        self.assertTrue(lots[1].is_usable)
        self.assertIsNone(lots[1].received_date)

    def test_empty_lots_hidden_unless_asked(self):
        numbers = [lot.lot_number for lot in lot_stock(item_id=self.raw_b.pk)]
        self.assertEqual(numbers, ["OLD-B"])
        numbers = [lot.lot_number for lot in lot_stock(item_id=self.raw_b.pk, include_empty=True)]
        self.assertIn("OLD-C", numbers)

    def test_expiring_filter(self):
        lots = lot_stock(expiring_within_days=30)
        self.assertEqual([lot.lot_id for lot in lots], [self.quarantine.pk])

    def test_item_totals_and_minimum_stock(self):
        totals = {item.item_code: item for item in item_stock(item_type="RAW")}
        a = totals["1000001"]
        self.assertEqual(
            (a.total_e6, a.usable_e6, a.quarantine_e6), (to_e6(45), to_e6(15), to_e6(30))
        )
        self.assertTrue(a.below_minimum)  # minimum 50, usable 15
        b = totals["1000002"]
        self.assertEqual((b.total_e6, b.usable_e6, b.unusable_e6), (to_e6(7), 0, to_e6(7)))
        c = totals["1000003"]  # no stock at all, minimum 0
        self.assertEqual(c.total_e6, 0)
        self.assertFalse(c.below_minimum)
        self.assertEqual(a.nearest_expiration, self.today + datetime.timedelta(days=100))

    def test_empty_lot_keeps_status_and_is_hidden_by_default(self):
        self.assertEqual(Lot.objects.get(pk=self.empty.pk).status, LotStatus.AVAILABLE)
        self.assertNotIn(self.empty.pk, [lot.lot_id for lot in lot_stock()])
        self.assertIn(self.empty.pk, [lot.lot_id for lot in lot_stock(include_empty=True)])


class CheckInventoryCommandTests(ServiceTestCase):
    def test_clean_database_passes(self):
        self.receive(self.raw_a, "5", self.day2, "r1")
        out = StringIO()
        call_command("check_inventory", stdout=out)
        self.assertIn("이상 없음", out.getvalue())

    def test_cancelled_receipt_with_stock_fails(self):
        receipt = self.receive(self.raw_a, "5", self.day2, "r1")
        IncomingReceipt.objects.filter(pk=receipt.pk).update(
            receipt_status=ReceiptStatus.CANCELLED, cancelled_at=kst_now(), cancel_reason="x"
        )
        with self.assertRaises(CommandError):
            call_command("check_inventory", stdout=StringIO())


class ShowViewCommandTests(ServiceTestCase):
    def test_lists_views_and_shows_rows(self):
        self.receive(self.raw_a, "5", self.day2, "r1")
        out = StringIO()
        call_command("show_view", stdout=out)
        self.assertIn("v_doc_batch", out.getvalue().split())
        out = StringIO()
        call_command("show_view", "v_doc_incoming_lot", "--limit", "1", stdout=out)
        self.assertIn("receipt_status", out.getvalue())
        self.assertIn("[1]", out.getvalue())
        out = StringIO()
        call_command("show_view", "v_doc_batch", "--sql", stdout=out)
        self.assertIn("CREATE VIEW v_doc_batch", out.getvalue())

    def test_rejects_tables(self):
        with self.assertRaises(CommandError):
            call_command("show_view", "lots", stdout=StringIO())


class LedgerChangeTests(ServiceTestCase):
    def raw_move(self, lot, code, quantity, occurred_at, created_at, key, **extra):
        return StockMovement.objects.create(
            lot=lot,
            movement_type_id=code,
            quantity_e6=to_e6(quantity),
            staff=self.staff,
            occurred_at=occurred_at,
            created_at=created_at,
            idempotency_key=key,
            **extra,
        )

    def test_changes_after_approval_that_affect_the_period(self):
        lot = self.receive(self.raw_a, "50", self.day1, "r1").lot  # recorded before approval
        approved_at = kst_now() + datetime.timedelta(hours=1)
        later = approved_at + datetime.timedelta(hours=1)
        period_start = self.day1 + datetime.timedelta(days=2)
        period_end = self.day2
        before = self.raw_move(lot, "ADJUST_OUT", "1", at(self.day1, 12), later, "a1", reason="x")
        inside = self.raw_move(lot, "ADJUST_OUT", "2", at(self.day2, 8), later, "a2", reason="x")
        self.raw_move(lot, "ADJUST_OUT", "3", at(self.today, 8), later, "a3", reason="x")

        changes = stock_ledger_changes_since(
            approved_at, period_start, period_end, item_id=self.raw_a.pk
        )
        self.assertEqual(
            [(c.movement_id, c.affects) for c in changes],
            [(before.pk, "OPENING"), (inside.pk, "PERIOD")],
        )
        self.assertEqual(changes[0].signed_quantity_e6, -to_e6(1))

    def test_nothing_new_means_no_changes(self):
        self.receive(self.raw_a, "50", self.day1, "r1")
        approved_at = kst_now() + datetime.timedelta(hours=1)
        self.assertEqual(stock_ledger_changes_since(approved_at, self.day1, self.today), [])

    def test_same_second_counts_as_changed(self):
        self.receive(self.raw_a, "50", self.day1, "r1")
        recorded = StockMovement.objects.get().created_at
        changes = stock_ledger_changes_since(recorded, self.day1, self.today)
        self.assertEqual(len(changes), 1)


class JudgmentTests(ServiceTestCase):
    def setUp(self):
        self.lot = self.receive(self.raw_a, "50", self.day2, "r1").lot

    def judge(self, result, reason=None, lot=None):
        return apply_incoming_judgment(
            lot_id=(lot or self.lot).pk,
            result=result,
            staff_id=self.staff.pk,
            document_id=77,
            reason=reason,
        )

    def test_pass_and_fail_set_status(self):
        self.assertEqual(self.judge("PASS").status, LotStatus.AVAILABLE)
        other = self.receive(self.raw_a, "5", self.day2, "r2").lot
        self.assertEqual(self.judge("FAIL", lot=other).status, LotStatus.REJECTED)
        log = AuditLog.objects.filter(table_name="lots", record_id=str(self.lot.pk)).get()
        self.assertEqual(log.after_json["judgment"], "PASS")
        self.assertEqual(log.after_json["document_id"], 77)

    def test_same_result_again_changes_nothing(self):
        self.judge("PASS")
        self.judge("PASS")
        self.assertEqual(AuditLog.objects.filter(table_name="lots").count(), 1)

    def test_rejudgment_needs_reason_and_untouched_lot(self):
        self.judge("PASS")
        with self.assertRaises(InventoryError):
            self.judge("FAIL")  # no reason
        self.assertEqual(self.judge("FAIL", reason="재검토 결과 이물").status, LotStatus.REJECTED)
        self.assertEqual(self.judge("PASS", reason="오판정 정정").status, LotStatus.AVAILABLE)
        adjust_stock(
            lot_id=self.lot.pk,
            direction="OUT",
            quantity="1",
            reason="사용",
            staff_id=self.staff.pk,
            idempotency_key="a1",
        )
        with self.assertRaises(InventoryError):
            self.judge("FAIL", reason="늦게 발견")

    def test_fail_then_return_empties_the_lot(self):
        self.judge("FAIL")
        return_to_supplier(
            lot_id=self.lot.pk,
            reason="육안검사 부적합 전량 반품",
            staff_id=self.staff.pk,
            idempotency_key="ret1",
        )
        self.lot.refresh_from_db()
        self.assertEqual(self.lot.status, LotStatus.REJECTED)
        self.assertEqual(Inventory.objects.get(lot=self.lot).quantity_e6, 0)
        with self.assertRaises(InventoryError):
            self.judge("PASS", reason="정정")

    def test_rejects_invalid_targets(self):
        with self.assertRaises(InventoryError):
            self.judge("CONDITIONAL")
        opening = self.opening(self.raw_a, "3", "o1", lot_number="OLD-1").lot
        with self.assertRaises(InventoryError):
            self.judge("PASS", lot=opening)
        cancel_receipt(receipt_id=self.lot.incoming_receipt.pk, staff_id=self.staff.pk, reason="x")
        with self.assertRaises(InventoryError):
            self.judge("PASS")
        with self.assertRaises(NotFound):
            apply_incoming_judgment(lot_id=999999, result="PASS", staff_id=self.staff.pk)

    def test_judged_lot_becomes_usable_stock(self):
        self.judge("PASS")
        row = lot_stock(item_id=self.raw_a.pk)[0]
        self.assertTrue(row.is_usable)
        self.assertEqual(item_stock(item_id=self.raw_a.pk)[0].usable_e6, to_e6(50))
