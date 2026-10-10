"""API tests for /api/v1/inventory/ (A4-A6)."""

import json
from io import StringIO

from django.core.management import call_command
from django.test import Client, TestCase

from .fields import kst_now
from .models import Item, Lot, Staff, Supplier

BASE = "/api/v1/inventory"


class ApiTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_master", "--sample", stdout=StringIO())
        cls.staff = Staff.objects.get(staff_code="S001")
        cls.supplier = Supplier.objects.get(supplier_code="V001")
        cls.raw = Item.objects.get(item_code="1000001")
        cls.today = kst_now().date().isoformat()

    def post(self, url, data, client=None, **extra):
        return (client or self.client).post(
            f"{BASE}{url}", json.dumps(data), content_type="application/json", **extra
        )

    def patch(self, url, data):
        return self.client.patch(f"{BASE}{url}", json.dumps(data), content_type="application/json")

    def get(self, url, **params):
        return self.client.get(f"{BASE}{url}", params)

    def receive(self, key="k1", quantity="50"):
        response = self.post(
            "/receipts/",
            {
                "item_id": self.raw.pk,
                "supplier_id": self.supplier.pk,
                "staff_id": self.staff.pk,
                "received_date": self.today,
                "quantity": quantity,
                "idempotency_key": key,
                "expiration_date": "2027-10-01",
            },
        )
        self.assertEqual(response.status_code, 201, response.content.decode())
        return response.json()


class MasterApiTests(ApiTestCase):
    def test_lists_and_filters(self):
        self.assertEqual(len(self.get("/staff/").json()["results"]), 3)
        items = self.get("/items/", item_type="RAW").json()["results"]
        self.assertEqual([i["item_code"] for i in items], ["1000001", "1000002", "1000003"])
        self.assertEqual(items[1]["minimum_stock"], "20.5")
        found = self.get("/suppliers/", q="포장").json()["results"]
        self.assertEqual([s["supplier_code"] for s in found], ["V002"])
        types = self.get("/item-types/").json()["results"]
        self.assertEqual(types[0], {"code": "RAW", "name": "원료"})

    def test_create_update_and_deactivate(self):
        response = self.post(
            "/items/",
            {
                "item_code": "1000099",
                "item_type": "raw",
                "name": "새 원료",
                "base_unit": "kg",
                "minimum_stock": 12.5,
            },
        )
        self.assertEqual(response.status_code, 201, response.content)
        item = response.json()
        self.assertEqual((item["item_type"], item["minimum_stock"]), ("RAW", "12.5"))
        response = self.patch(f"/items/{item['id']}/", {"name": "이름 변경", "is_active": False})
        self.assertEqual(response.json()["name"], "이름 변경")
        self.assertFalse(response.json()["is_active"])
        self.assertEqual(response.json()["minimum_stock"], "12.5")  # untouched fields kept
        active = [i["item_code"] for i in self.get("/items/").json()["results"]]
        self.assertNotIn("1000099", active)
        every = [i["item_code"] for i in self.get("/items/", active="all").json()["results"]]
        self.assertIn("1000099", every)

    def test_master_errors(self):
        duplicate = self.post("/staff/", {"staff_code": "S001", "name": "중복"})
        self.assertEqual(duplicate.status_code, 409)
        missing = self.post("/suppliers/", {"supplier_code": "V9"})
        self.assertEqual(missing.status_code, 400)
        self.assertIn("name", missing.json()["error"]["message"])
        code_change = self.patch(f"/staff/{self.staff.pk}/", {"staff_code": "S999"})
        self.assertEqual(code_change.status_code, 400)
        self.assertEqual(self.get("/staff/999999/").status_code, 404)
        bad_type = self.post(
            "/items/", {"item_code": "X", "item_type": "NOPE", "name": "x", "base_unit": "kg"}
        )
        self.assertEqual(bad_type.status_code, 400)

    def test_item_type_locked_after_lot(self):
        self.receive()
        response = self.patch(f"/items/{self.raw.pk}/", {"item_type": "SEMI"})
        self.assertEqual(response.status_code, 409)

    def test_method_and_json_errors(self):
        self.assertEqual(self.client.delete(f"{BASE}/staff/").status_code, 405)
        response = self.client.post(f"{BASE}/staff/", "{not json", content_type="application/json")
        self.assertEqual(response.status_code, 400)


class ReceiptApiTests(ApiTestCase):
    def test_register_list_detail_cancel(self):
        receipt = self.receive()
        self.assertEqual(receipt["quantity"], "50")
        self.assertEqual(receipt["lot_status"], "QUARANTINE")
        self.assertTrue(receipt["lot_number"].startswith("1000001-"))
        listed = self.get("/receipts/", **{"from": self.today}).json()
        self.assertEqual(listed["count"], 1)
        detail = self.get(f"/receipts/{receipt['id']}/").json()
        self.assertEqual(detail["supplier"]["name"], "가상원료상사")
        cancelled = self.post(
            f"/receipts/{receipt['id']}/cancel/", {"staff_id": self.staff.pk, "reason": "오입력"}
        ).json()
        self.assertEqual(cancelled["receipt_status"], "CANCELLED")
        self.assertEqual(self.get("/receipts/", status="CANCELLED").json()["count"], 1)

    def test_decimal_quantity_is_exact(self):
        receipt = self.receive(quantity=0.1)
        self.assertEqual(receipt["quantity"], "0.1")

    def test_receipt_errors(self):
        missing = self.post("/receipts/", {"item_id": self.raw.pk})
        self.assertEqual(missing.status_code, 400)
        self.assertIn("supplier_id", missing.json()["error"]["fields"])
        bad_date = self.post(
            "/receipts/",
            {
                "item_id": self.raw.pk,
                "supplier_id": self.supplier.pk,
                "staff_id": self.staff.pk,
                "received_date": "2026/10/09",
                "quantity": "1",
                "idempotency_key": "x",
            },
        )
        self.assertEqual(bad_date.status_code, 400)
        self.assertEqual(self.get("/receipts/999999/").status_code, 404)
        not_found = self.post(
            "/receipts/999999/cancel/", {"staff_id": self.staff.pk, "reason": "x"}
        )
        self.assertEqual(not_found.status_code, 404)

    def test_csrf_is_enforced_and_cookie_is_issued(self):
        client = Client(enforce_csrf_checks=True)
        data = {"staff_code": "S050", "name": "x"}
        self.assertEqual(self.post("/staff/", data, client=client).status_code, 403)
        client.get(f"{BASE}/staff/")
        token = client.cookies["csrftoken"].value
        response = self.post("/staff/", data, client=client, HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 201)


class StockAndLedgerApiTests(ApiTestCase):
    def setUp(self):
        self.receipt = self.receive()
        self.lot_id = self.receipt["lot_id"]

    def test_movement_endpoints(self):
        adjusted = self.post(
            "/movements/adjust/",
            {
                "lot_id": self.lot_id,
                "direction": "out",
                "quantity": "5",
                "reason": "실사",
                "staff_id": self.staff.pk,
                "idempotency_key": "a1",
            },
        )
        self.assertEqual(adjusted.status_code, 201, adjusted.content)
        self.assertEqual(adjusted.json()["lot_quantity"], "45")
        self.assertEqual(adjusted.json()["signed_quantity"], "-5")
        corrected = self.post(
            f"/movements/{adjusted.json()['id']}/correct/",
            {"reason": "오입력", "staff_id": self.staff.pk, "idempotency_key": "c1"},
        )
        self.assertEqual(corrected.json()["movement_type"], "CORRECTION_IN")
        self.assertEqual(corrected.json()["lot_quantity"], "50")
        disposed = self.post(
            "/movements/disposal/",
            {
                "lot_id": self.lot_id,
                "reason": "부적합",
                "staff_id": self.staff.pk,
                "idempotency_key": "d1",
            },
        )
        self.assertEqual(
            (disposed.json()["lot_quantity"], disposed.json()["lot_status"]), ("0", "DISPOSED")
        )
        too_much = self.post(
            "/movements/return/",
            {
                "lot_id": self.lot_id,
                "quantity": "1",
                "reason": "x",
                "staff_id": self.staff.pk,
                "idempotency_key": "r1",
            },
        )
        self.assertEqual(too_much.status_code, 400)
        self.assertIn("재고가 부족", too_much.json()["error"]["message"])

    def test_opening_balance_endpoint(self):
        response = self.post(
            "/movements/opening-balance/",
            {
                "item_id": self.raw.pk,
                "quantity": "7",
                "staff_id": self.staff.pk,
                "occurred_at": "2026-10-01",
                "idempotency_key": "o1",
                "lot_number": "OLD-1",
            },
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["occurred_at"], "2026-10-01T00:00:00+09:00")
        self.assertTrue(Lot.objects.filter(lot_number="OLD-1").exists())

    def test_lot_detail_and_stock(self):
        lot = self.get(f"/lots/{self.lot_id}/").json()
        self.assertEqual(lot["quantity"], "50")
        self.assertEqual([m["movement_type"] for m in lot["movements"]], ["RECEIPT"])
        lots = self.get("/stock/lots/", item_id=self.raw.pk).json()["results"]
        self.assertEqual(lots[0]["supplier_name"], "가상원료상사")
        self.assertFalse(lots[0]["is_usable"])
        items = self.get("/stock/items/", item_type="RAW", below_minimum="1").json()["results"]
        self.assertIn("1000001", [i["item"]["item_code"] for i in items])
        self.assertEqual(self.get("/stock/lots/", status="WRONG").status_code, 400)

    def test_ledger_json_and_csv(self):
        response = self.get(
            "/ledger/", **{"from": self.today, "to": self.today, "item_type": "RAW"}
        )
        body = response.json()
        lot = body["results"][0]["lots"][0]
        self.assertEqual((lot["opening"], lot["in"], lot["closing"]), ("0", "50", "50"))
        self.assertEqual(lot["lines"][0]["movement_name"], "입고")
        csv_response = self.client.get(
            f"{BASE}/ledger/export.csv", {"from": self.today, "to": self.today}
        )
        self.assertEqual(csv_response.status_code, 200)
        text = csv_response.content.decode("utf-8")
        self.assertTrue(text.startswith("﻿원료수불대장"))
        self.assertIn("품목 합계", text)
        self.assertIn("attachment;", csv_response["Content-Disposition"])

    def test_ledger_parameter_errors(self):
        self.assertEqual(self.get("/ledger/", to=self.today).status_code, 400)
        response = self.get("/ledger/", **{"from": "2026-10-10", "to": "2026-10-01"})
        self.assertEqual(response.status_code, 400)
        response = self.get("/ledger/", **{"from": "2024-01-01", "to": "2026-01-01"})
        self.assertEqual(response.status_code, 400)
