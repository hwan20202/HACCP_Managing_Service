"""Mentor's stock/movement example, using only isolated synthetic business records."""

import datetime
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from .fields import KST, kst_now
from .models import Item, Staff
from .movements import adjust_stock, record_opening_balance
from .test_support import seed_document_forms


def build_overview_example(staff, today):
    """Two items, six LOTs, repeated inflows/outflows; four positive ending balances."""
    items = {
        label: Item.objects.create(
            item_type_id="RAW",
            item_code=f"QA_UI_{label}",
            short_code=label,
            name=f"가상 QA 원료 {label}",
            base_unit="kg",
        )
        for label in ("AAA", "BBB")
    }
    expected = {}

    def at(days, hour=9):
        planned = datetime.datetime.combine(
            today + datetime.timedelta(days=days), datetime.time(hour), tzinfo=KST
        )
        # Today's fixture must also work before 09:00; never create future movements.
        return min(planned, kst_now().replace(microsecond=0))

    def opening(label, days, quantity):
        number = at(days).strftime("%Y%m%d")
        movement = record_opening_balance(
            item_id=items[label].pk,
            quantity=quantity,
            staff_id=staff.pk,
            idempotency_key=f"overview-{label}-{number}",
            occurred_at=at(days),
            lot_number=number,
            expiration_status="NONE",
            reason="가상 통합 화면 검증",
        )
        expected[movement.lot_id] = {
            "quantity": quantity,
            "item_code": items[label].item_code,
            "lot_number": number,
        }
        return movement.lot_id

    def adjust(lot_id, direction, quantity, days, hour):
        adjust_stock(
            lot_id=lot_id,
            direction=direction,
            quantity=quantity,
            reason="가상 통합 화면 검증",
            staff_id=staff.pk,
            idempotency_key=f"overview-adjust-{lot_id}-{days}-{hour}",
            occurred_at=at(days, hour),
        )

    a1 = opening("AAA", -4, "1000")
    adjust(a1, "IN", "1000", -4, 10)
    a2 = opening("AAA", -3, "500")
    adjust(a1, "OUT", "1000", -3, 11)
    opening("AAA", -2, "1000")
    adjust(a1, "OUT", "1000", -2, 11)
    adjust(a2, "OUT", "500", -2, 12)
    opening("AAA", 0, "500")
    b1 = opening("BBB", -1, "1000")
    adjust(b1, "OUT", "200", -1, 11)
    opening("BBB", 0, "1000")
    expected[a1]["quantity"] = "0"
    expected[a2]["quantity"] = "0"
    expected[b1]["quantity"] = "800"
    return expected


class OverviewScenarioTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_document_forms()
        call_command("seed_master", "--sample", stdout=StringIO())
        cls.today = kst_now().date()
        cls.expected = build_overview_example(Staff.objects.get(staff_code="S001"), cls.today)

    def get(self, path, **params):
        response = self.client.get(f"/api/v1/inventory/{path}", params)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["results"]

    def test_mentor_example_current_stock_matches_all_movement_endings(self):
        stock = self.get("stock/lots/", q="QA_UI_")
        self.assertEqual(sorted(r["quantity"] for r in stock), ["1000", "1000", "500", "800"])
        ledger = self.get(
            "ledger/",
            q="QA_UI_",
            **{
                "from": (self.today - datetime.timedelta(days=4)).isoformat(),
                "to": self.today.isoformat(),
            },
        )
        lots = {lot["lot_id"]: lot for item in ledger for lot in item["lots"]}
        self.assertEqual(len(lots), 6)
        self.assertEqual(sum(len(lot["lines"]) for lot in lots.values()), 11)
        for lot_id, expected in self.expected.items():
            self.assertEqual(lots[lot_id]["closing"], expected["quantity"])
            self.assertEqual(lots[lot_id]["lines"][-1]["balance"], expected["quantity"])
        self.assertEqual(len(self.get("stock/lots/", q="QA_UI_", include_empty="1")), 6)

    def test_same_lot_number_on_different_items_selects_exact_lot_id(self):
        stocks = self.get("stock/lots/", q=self.today.strftime("%Y%m%d"))
        self.assertEqual(len(stocks), 2)
        self.assertEqual(len({r["item"]["id"] for r in stocks}), 2)
        result = self.get(
            "ledger/",
            lot_id=stocks[0]["lot_id"],
            **{
                "from": self.today.isoformat(),
                "to": self.today.isoformat(),
            },
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["lots"][0]["lot_id"], stocks[0]["lot_id"])

    def test_historical_period_keeps_opening_balances_and_current_stock_distinct(self):
        old_day = (self.today - datetime.timedelta(days=3)).isoformat()
        result = self.get("ledger/", q="QA_UI_AAA", **{"from": old_day, "to": old_day})
        self.assertEqual(result[0]["opening"], "2000")
        self.assertEqual(result[0]["closing"], "1500")
        current = self.get("stock/lots/", q="QA_UI_AAA")
        self.assertEqual(sorted(r["quantity"] for r in current), ["1000", "500"])
