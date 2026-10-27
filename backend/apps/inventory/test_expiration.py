"""소비기한 유무 (0007) and the stock / ledger queries the 재고장·수불일지 screens use.

Covers the confirmed checks in docs/history/planning/inventory-erd-review-20261014.md:
원료 채번 기준, NONE / UNKNOWN 구분, 같은 소비기한 반복 입고, 500 + 500 - 300 = 700 with
three ledger lines, 0 재고 기본 제외 with the history kept, LOT 번호·제조일 검색.
"""

import datetime
import json
from io import StringIO

from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.test import TestCase

from .expiration import resolve_status
from .fields import kst_now
from .ledger import stock_ledger
from .models import (
    Bom,
    BomLine,
    ExpirationStatus,
    IncomingReceipt,
    Item,
    Lot,
    Staff,
    StockMovement,
    Supplier,
)
from .production import add_output, add_usage, create_batch, fefo_candidates, start_batch
from .quantity import to_e6
from .receiving import ReceiptInput, ReceivingError, register_receipt
from .stock import lot_stock
from .test_support import seed_document_forms

BASE = "/api/v1/inventory"


class ExpirationTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_document_forms()
        call_command("seed_master", "--sample", stdout=StringIO())
        cls.raw = Item.objects.get(item_code="1000001")  # LOT 약어 AGA
        cls.pouch = Item.objects.get(item_code="2000001")  # CGP
        cls.semi = Item.objects.get(item_code="3000501")
        cls.supplier = Supplier.objects.get(supplier_code="V001")
        cls.staff = Staff.objects.get(staff_code="S001")
        cls.today = kst_now().date()

    def receive(self, key, item=None, quantity="10", day=None, **extra):
        values = {
            "item_id": (item or self.raw).pk,
            "supplier_id": self.supplier.pk,
            "staff_id": self.staff.pk,
            "received_date": day or self.today,
            "quantity": quantity,
            "idempotency_key": key,
            "judgment": "PASS",
            **extra,
        }
        return register_receipt(ReceiptInput(**values)).lot


class RawNumberingTests(ExpirationTestCase):
    def test_known_is_numbered_by_expiration_and_none_by_received_date(self):
        known = self.receive("k1", expiration_date=datetime.date(2028, 3, 5))
        self.assertEqual((known.lot_number, known.expiration_status), ("AGA280305", "KNOWN"))
        none = self.receive("k2", expiration_status="NONE")
        self.assertEqual(none.lot_number, f"AGA{self.today:%y%m%d}")
        self.assertEqual((none.expiration_date, none.expiration_status), (None, "NONE"))

    def test_a_missing_date_is_not_none(self):
        for extra in ({}, {"expiration_status": "UNKNOWN"}, {"expiration_status": "KNOWN"}):
            with self.subTest(extra), self.assertRaises(ReceivingError):
                self.receive("bad", **extra)
        with self.assertRaises(ReceivingError):  # 날짜가 있는데 '없음'
            self.receive("bad", expiration_status="NONE", expiration_date=self.today)
        self.assertEqual(Lot.objects.count(), 0)

    def test_same_expiration_again_gets_a_suffix_per_receipt(self):
        # 입고 1건 = LOT 1개 유지. 같은 기준일이면 -2, -3 (10/15 범위 정리)
        expires = datetime.date(2028, 3, 5)
        numbers = [self.receive(f"k{n}", expiration_date=expires).lot_number for n in range(3)]
        self.assertEqual(numbers, ["AGA280305", "AGA280305-2", "AGA280305-3"])
        self.assertEqual(IncomingReceipt.objects.count(), 3)

    def test_other_items_keep_the_received_date(self):
        pouch = self.receive("p1", item=self.pouch)
        self.assertEqual(
            (pouch.lot_number, pouch.expiration_status), (f"CGP{self.today:%y%m%d}", "UNKNOWN")
        )
        dated = self.receive("p2", item=self.pouch, expiration_date=datetime.date(2029, 1, 1))
        self.assertEqual(
            (dated.lot_number, dated.expiration_status), (f"CGP{self.today:%y%m%d}-2", "KNOWN")
        )
        semi = self.receive("s1", item=self.semi, expiration_status="NONE")
        self.assertEqual(
            (semi.lot_number, semi.expiration_status), (f"{self.today:%y%m%d}A", "NONE")
        )

    def test_status_rules(self):
        self.assertEqual(resolve_status(None, self.today), "KNOWN")
        self.assertIsNone(resolve_status("", None))
        self.assertEqual(resolve_status("none", None), "NONE")
        for status, date in (("KNOWN", None), ("NONE", self.today), ("MAYBE", None)):
            with self.subTest(status), self.assertRaises(Exception):
                resolve_status(status, date)


class DatabaseRuleTests(ExpirationTestCase):
    def lot(self, number, **extra):
        return Lot.objects.create(
            lot_number=number, item=self.raw, lot_kind="INCOMING", status="AVAILABLE", **extra
        )

    def test_status_follows_the_date(self):
        self.assertEqual(self.lot("A", expiration_date=self.today).expiration_status, "KNOWN")
        self.assertEqual(self.lot("B").expiration_status, "UNKNOWN")
        bad = [
            {"expiration_status": "KNOWN"},
            {"expiration_status": "NONE", "expiration_date": self.today},
            {"expiration_status": "UNKNOWN", "expiration_date": self.today},
        ]
        for extra in bad:
            with self.subTest(extra), self.assertRaises(IntegrityError), transaction.atomic():
                self.lot("X", **extra)
        lot = self.lot("C", expiration_status="NONE")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Lot.objects.filter(pk=lot.pk).update(expiration_date=self.today)

    def test_raw_receipt_needs_a_known_status(self):
        lot = self.lot("D")  # UNKNOWN
        movement = StockMovement.objects.create(
            lot=lot,
            movement_type_id="RECEIPT",
            quantity_e6=to_e6(1),
            staff=self.staff,
            occurred_at=kst_now(),
            idempotency_key="raw-1",
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            IncomingReceipt.objects.create(
                lot=lot,
                supplier=self.supplier,
                received_date=self.today,
                quantity_e6=to_e6(1),
                staff=self.staff,
                stock_movement=movement,
            )

    def test_document_view_shows_the_status(self):
        lot = self.receive("k1", expiration_status="NONE")
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT expiration_status, expiration_date FROM v_doc_incoming_lot"
                " WHERE lot_id = %s",
                [lot.pk],
            )
            self.assertEqual(cursor.fetchone(), ("NONE", None))


class StockAndLedgerTests(ExpirationTestCase):
    def started_batch(self, item, component):
        bom = Bom.objects.create(
            item=item, version=1, base_quantity_e6=to_e6(1), effective_from=self.today
        )
        BomLine.objects.create(bom=bom, line_no=1, component_item=component, quantity_e6=to_e6(1))
        batch = create_batch(
            item_id=item.pk,
            staff_id=self.staff.pk,
            manufactured_date=self.today,
            planned_quantity="1",
        )
        start_batch(batch_id=batch.pk, staff_id=self.staff.pk)
        return batch

    def test_500_plus_500_minus_300(self):
        # 한 배치의 산출 두 번(500 + 500)이 한 LOT 에 쌓이고, 다른 배치에 300 투입 -> 700, 이력 3건
        self.receive("input-stock", expiration_status="NONE")
        make = self.started_batch(self.semi, self.raw)
        lot = add_output(
            batch_id=make.pk, quantity="500", staff_id=self.staff.pk, idempotency_key="o1"
        ).lot
        add_output(batch_id=make.pk, quantity="500", staff_id=self.staff.pk, idempotency_key="o2")
        # 같은 요청 재시도는 한 번만 등록
        add_output(batch_id=make.pk, quantity="500", staff_id=self.staff.pk, idempotency_key="o2")
        other = Item.objects.create(
            item_type_id="SEMI", item_code="3000502", name="다음 반제품", base_unit="개"
        )
        use = self.started_batch(other, self.semi)
        add_usage(
            batch_id=use.pk,
            lot_id=lot.pk,
            quantity="300",
            staff_id=self.staff.pk,
            idempotency_key="u1",
        )
        [row] = lot_stock(lot_number=lot.lot_number, item_type="SEMI")
        self.assertEqual(row.quantity_e6, to_e6(700))
        [item] = stock_ledger(self.today, self.today, lot_id=lot.pk)
        lines = item.lots[0].lines
        self.assertEqual(
            [line.signed_quantity_e6 for line in lines], [to_e6(500), to_e6(500), -to_e6(300)]
        )
        self.assertEqual(lines[-1].balance_e6, to_e6(700))

    def test_empty_lots_are_left_out_but_their_history_stays(self):
        lot = self.receive("k1", expiration_status="NONE")
        StockMovement.objects.create(
            lot=lot,
            movement_type_id="DISPOSAL",
            quantity_e6=to_e6(10),
            staff=self.staff,
            occurred_at=kst_now(),
            reason="폐기",
            idempotency_key="d1",
        )
        self.assertEqual(lot_stock(item_type="RAW"), [])
        self.assertEqual(len(lot_stock(item_type="RAW", include_empty=True)), 1)
        [item] = stock_ledger(self.today, self.today, item_type="RAW")
        self.assertEqual(len(item.lots[0].lines), 2)

    def test_search_filters(self):
        self.receive("k1", expiration_date=datetime.date(2028, 1, 1))
        self.receive("k2", expiration_status="NONE")
        self.receive("p1", item=self.pouch)
        self.assertEqual([r.lot_number for r in lot_stock(lot_number="2801")], ["AGA280101"])
        self.assertEqual(
            [r.expiration_status for r in lot_stock(item_type="RAW,PACKAGING")],
            ["KNOWN", "NONE", "UNKNOWN"],
        )
        self.assertEqual(len(lot_stock(expiration_status="NONE")), 1)
        made = self.started_batch(self.semi, self.raw)
        add_output(batch_id=made.pk, quantity="1", staff_id=self.staff.pk, idempotency_key="o1")
        yesterday = self.today - datetime.timedelta(days=1)
        self.assertEqual(
            len(lot_stock(manufactured_from=self.today, manufactured_to=self.today)), 1
        )
        self.assertEqual(lot_stock(manufactured_to=yesterday, item_type="SEMI"), [])
        found = stock_ledger(self.today, self.today, lot_number="2801")
        self.assertEqual([lot.lot_number for item in found for lot in item.lots], ["AGA280101"])

    def test_fefo_puts_undated_lots_after_dated_ones_oldest_received_first(self):
        later = self.receive("k1", expiration_status="NONE")
        earlier = self.receive(
            "k2", expiration_status="NONE", day=self.today - datetime.timedelta(days=5)
        )
        dated = self.receive("k3", expiration_date=self.today + datetime.timedelta(days=90))
        picks = fefo_candidates(item_id=self.raw.pk, quantity="30")
        self.assertEqual([lot.pk for lot, _, _ in picks], [dated.pk, earlier.pk, later.pk])


class ApiTests(ExpirationTestCase):
    def post(self, url, data):
        return self.client.post(f"{BASE}{url}", json.dumps(data), content_type="application/json")

    def test_receipt_and_stock_endpoints(self):
        body = {
            "item_id": self.raw.pk,
            "supplier_id": self.supplier.pk,
            "staff_id": self.staff.pk,
            "received_date": self.today.isoformat(),
            "quantity": "3",
            "idempotency_key": "a1",
        }
        refused = self.post("/receipts/", body)
        self.assertEqual(refused.status_code, 400)
        self.assertIn("소비기한 유무", refused.json()["error"]["message"])
        created = self.post("/receipts/", {**body, "expiration_status": "none"})
        self.assertEqual(created.status_code, 201, created.content.decode())
        self.assertEqual(created.json()["expiration_status"], "NONE")
        rows = self.client.get(f"{BASE}/stock/lots/", {"expiration_status": "NONE"}).json()
        self.assertEqual([r["expiration_status"] for r in rows["results"]], ["NONE"])
        bad = self.client.get(f"{BASE}/stock/lots/", {"expiration_status": "MAYBE"})
        self.assertEqual(bad.status_code, 400)
        ledger = self.client.get(
            f"{BASE}/ledger/",
            {"from": self.today.isoformat(), "to": self.today.isoformat(), "lot_number": "AGA"},
        ).json()
        self.assertEqual(ledger["results"][0]["lots"][0]["expiration_status"], "NONE")
        csv_text = self.client.get(
            f"{BASE}/ledger/export.csv",
            {"from": self.today.isoformat(), "to": self.today.isoformat()},
        ).content.decode("utf-8-sig")
        self.assertIn(ExpirationStatus.NONE.label, csv_text)


class UsablePriorityTests(ExpirationTestCase):
    def test_expired_quality_passed_lot_is_not_usable_stock(self):
        from .stock import item_stock

        expired = self.receive("expired", expiration_date=self.today - datetime.timedelta(days=1))
        valid = self.receive("today", expiration_date=self.today)
        rows = {r.lot_id: r for r in lot_stock(item_id=self.raw.pk)}
        self.assertTrue(rows[expired.pk].is_usable)  # Existing quality-only contract.
        self.assertTrue(rows[expired.pk].is_expired)
        self.assertFalse(rows[expired.pk].can_use)
        self.assertIsNone(rows[expired.pk].use_priority)
        self.assertFalse(rows[valid.pk].is_expired)
        self.assertTrue(rows[valid.pk].can_use)  # Expiration day is inclusive.
        self.assertEqual([r.lot_id for r in lot_stock(usable_only=True)], [valid.pk])
        [summary] = item_stock(item_id=self.raw.pk)
        self.assertEqual((summary.usable_e6, summary.unusable_e6), (to_e6(10), to_e6(10)))

    def test_ranks_match_fefo_and_are_not_renumbered_by_search(self):
        from .holds import hold_lot
        from .movements import dispose

        none_new = self.receive("none-new", expiration_status="NONE")
        none_old = self.receive(
            "none-old", expiration_status="NONE", day=self.today - datetime.timedelta(days=5)
        )
        late = self.receive("late", expiration_date=self.today + datetime.timedelta(days=90))
        early = self.receive("early", expiration_date=self.today + datetime.timedelta(days=1))
        self.receive("fail", expiration_date=self.today, judgment="FAIL")
        held = self.receive("held", expiration_date=self.today)
        hold_lot(lot_id=held.pk, source_type="MANUAL", reason="test", staff_id=self.staff.pk)
        empty = self.receive("empty", expiration_status="NONE")
        dispose(lot_id=empty.pk, staff_id=self.staff.pk, reason="test", idempotency_key="empty")
        expected = [early.pk, late.pk, none_old.pk, none_new.pk]
        rows = lot_stock(item_id=self.raw.pk, usable_only=True, include_empty=True)
        self.assertEqual([r.lot_id for r in rows], expected)
        self.assertEqual([r.use_priority for r in rows], [1, 2, 3, 4])
        self.assertEqual(
            [lot.pk for lot, _, _ in fefo_candidates(item_id=self.raw.pk, quantity="100")], expected
        )
        [found] = lot_stock(item_id=self.raw.pk, lot_number=late.lot_number)
        self.assertEqual(found.use_priority, 2)
        filtered = lot_stock(item_id=self.raw.pk, expiration_status="NONE", usable_only=True)
        self.assertEqual([r.use_priority for r in filtered], [3, 4])

    def test_api_exposes_usability_and_keeps_expired_history(self):
        expired = self.receive("expired", expiration_date=self.today - datetime.timedelta(days=1))
        valid = self.receive("valid", expiration_status="NONE")
        args = {"item_id": self.raw.pk, "usable_only": "1"}
        response = self.client.get(f"{BASE}/stock/lots/", args)
        self.assertEqual(response.status_code, 200)
        [row] = response.json()["results"]
        self.assertEqual(row["lot_id"], valid.pk)
        self.assertEqual((row["can_use"], row["is_expired"], row["use_priority"]), (True, False, 1))
        ledger = self.client.get(
            f"{BASE}/ledger/",
            {"from": str(self.today), "to": str(self.today), "lot_id": expired.pk},
        ).json()
        self.assertEqual(len(ledger["results"][0]["lots"][0]["lines"]), 1)
