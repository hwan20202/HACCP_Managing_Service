"""API tests for /api/v1/inventory/ (A4-A6)."""

import datetime
import json
from io import StringIO

from django.core.management import call_command
from django.test import Client, TestCase

from .fields import kst_now
from .models import Bom, BomLine, Item, Lot, Staff, Supplier
from .test_support import seed_document_forms

BASE = "/api/v1/inventory"


class ApiTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_document_forms()
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
        self.assertTrue(receipt["lot_number"].startswith("AGA"))
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


class ReceiptWithJudgmentApiTests(ApiTestCase):
    def test_judgment_sent_with_receipt(self):
        data = {
            "item_id": self.raw.pk,
            "supplier_id": self.supplier.pk,
            "staff_id": self.staff.pk,
            "received_date": self.today,
            "quantity": "10",
            "idempotency_key": "j1",
            "expiration_status": "NONE",
            "judgment": "fail",
        }
        response = self.post("/receipts/", data)
        self.assertEqual(response.status_code, 201, response.content.decode())
        self.assertEqual(response.json()["lot_status"], "REJECTED")
        bad = self.post("/receipts/", {**data, "idempotency_key": "j2", "judgment": "maybe"})
        self.assertEqual(bad.status_code, 400)


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
            (disposed.json()["lot_quantity"], disposed.json()["lot_status"]), ("0", "QUARANTINE")
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


class LedgerChangesApiTests(ApiTestCase):
    def test_changes_endpoint(self):
        self.receive()
        params = {"from": self.today, "to": self.today}
        before = self.get("/ledger/changes/", since="2000-01-01T00:00:00", **params).json()
        self.assertTrue(before["changed"])
        self.assertEqual(before["results"][0]["affects"], "PERIOD")
        self.assertEqual(before["results"][0]["quantity"], "50")
        after = self.get("/ledger/changes/", since="2999-01-01T00:00:00", **params).json()
        self.assertEqual(after, {"changed": False, "results": []})
        self.assertEqual(
            self.get("/ledger/changes/", since="2026-10-01", **params).status_code, 400
        )


class JudgmentApiTests(ApiTestCase):
    def test_judgment_endpoint(self):
        receipt = self.receive()
        url = f"/lots/{receipt['lot_id']}/judgment/"
        response = self.post(url, {"result": "pass", "staff_id": self.staff.pk, "document_id": 5})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["status"], "AVAILABLE")
        changed = self.post(url, {"result": "FAIL", "staff_id": self.staff.pk})
        self.assertEqual(changed.status_code, 400)
        self.assertIn("사유", changed.json()["error"]["message"])
        self.assertEqual(
            self.post(
                "/lots/999999/judgment/", {"result": "PASS", "staff_id": self.staff.pk}
            ).status_code,
            404,
        )


class ProductionApiTests(ApiTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.finished = Item.objects.get(item_code="4000001")
        cls.semi = Item.objects.create(
            item_type_id="SEMI",
            item_code="3000001",
            short_code="BGH",
            name="가상환(벌크)",
            base_unit="개",
            shelf_life_months=12,
        )
        cls.bom = Bom.objects.create(
            item=cls.semi,
            version=1,
            base_quantity_e6=1000 * 1_000_000,
            effective_from=datetime.date(2026, 1, 1),
        )
        cls.line = BomLine.objects.create(
            bom=cls.bom, line_no=1, component_item=cls.raw, quantity_e6=4 * 1_000_000
        )

    def receive_pass(self, key, quantity):
        response = self.post(
            "/receipts/",
            {
                "item_id": self.raw.pk,
                "supplier_id": self.supplier.pk,
                "staff_id": self.staff.pk,
                "received_date": self.today,
                "quantity": quantity,
                "idempotency_key": key,
                "expiration_status": "NONE",
                "judgment": "PASS",
            },
        )
        self.assertEqual(response.status_code, 201, response.content.decode())
        return response.json()["lot_id"]

    def test_batch_flow(self):
        lot_id = self.receive_pass("r1", "50")
        created = self.post(
            "/batches/",
            {
                "item_id": self.semi.pk,
                "process_type": "manufacture",
                "staff_id": self.staff.pk,
                "planned_quantity": "2000",
            },
        )
        self.assertEqual(created.status_code, 201, created.content.decode())
        batch = created.json()
        self.assertEqual((batch["status"], batch["bom_id"]), ("PLANNED", self.bom.pk))
        url = f"/batches/{batch['id']}"

        started = self.post(f"{url}/start/", {"staff_id": self.staff.pk}).json()
        self.assertEqual(started["status"], "IN_PROGRESS")

        fefo = self.get("/batches/fefo/", item_id=self.raw.pk, quantity="60").json()
        self.assertEqual((fefo["covered"], fefo["shortfall"]), ("50", "10"))
        self.assertEqual(fefo["results"][0]["lot_id"], lot_id)

        used = self.post(
            f"{url}/usages/",
            {
                "lot_id": lot_id,
                "quantity": "8",
                "staff_id": self.staff.pk,
                "idempotency_key": "u1",
                "bom_line_id": self.line.pk,
            },
        )
        self.assertEqual(used.status_code, 201, used.content.decode())
        output = self.post(
            f"{url}/outputs/",
            {"quantity": "2000", "staff_id": self.staff.pk, "idempotency_key": "o1"},
        ).json()
        self.assertEqual(
            output["outputs"][0]["lot_number"],
            f"{self.today[2:4]}{self.today[5:7]}{self.today[8:10]}A",
        )
        self.assertEqual(output["outputs"][0]["lot_quantity"], "2000")
        self.assertEqual(
            (output["output_lot"]["lot_number"], output["output_lot"]["stock"]),
            (output["outputs"][0]["lot_number"], "2000"),
        )
        self.assertEqual(
            output["bom_check"],
            {
                "basis": "output",
                "basis_quantity": "2000",
                "lines": [
                    {
                        "line_no": 1,
                        "item": {"id": self.raw.pk, "item_code": "1000001", "name": "가상원료A"},
                        "unit": "kg",
                        "standard": "8",
                        "actual": "8",
                        "stock_managed": True,
                    }
                ],
            },
        )
        done = self.post(f"{url}/complete/", {"staff_id": self.staff.pk}).json()
        self.assertEqual(done["status"], "COMPLETED")
        self.assertEqual(self.get(f"{url}/").json()["usages"][0]["net_quantity"], "8")

        listed = self.get("/batches/", status="COMPLETED", **{"from": self.today}).json()
        self.assertEqual(listed["count"], 1)
        self.assertEqual(
            self.get("/boms/", item_id=self.semi.pk).json()["results"][0]["id"], self.bom.pk
        )

    def test_errors(self):
        bad = self.post(
            "/batches/",
            {"item_id": self.raw.pk, "process_type": "MANUFACTURE", "staff_id": self.staff.pk},
        )
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(self.get("/batches/999999/").status_code, 404)
        # 포장배치·완제품 제조는 MVP 범위 밖 (10/15)
        for body in (
            {"item_id": self.semi.pk, "process_type": "PACKAGING"},
            {"item_id": self.finished.pk},
        ):
            refused = self.post("/batches/", {**body, "staff_id": self.staff.pk})
            self.assertEqual(refused.status_code, 400, body)
        batch = self.post("/batches/", {"item_id": self.semi.pk, "staff_id": self.staff.pk}).json()
        self.assertEqual(batch["process_type"], "MANUFACTURE")
        # 계획 상태에서 제조일(생산 시작일) 없이 산출하면 거부 (10/14)
        no_date = self.post(
            f"/batches/{batch['id']}/outputs/",
            {"quantity": "1", "staff_id": self.staff.pk, "idempotency_key": "o1"},
        )
        self.assertEqual(no_date.status_code, 400)
        self.assertIn("생산을 시작", no_date.json()["error"]["message"])
        missing = self.post(f"/batches/{batch['id']}/cancel/", {"staff_id": self.staff.pk})
        self.assertEqual(missing.status_code, 400)
        cancelled = self.post(
            f"/batches/{batch['id']}/cancel/", {"staff_id": self.staff.pk, "reason": "잘못 등록"}
        )
        self.assertEqual(cancelled.json()["status"], "CANCELLED")
        self.assertEqual(self.get("/batches/", status="NOPE").status_code, 400)
        self.assertEqual(self.get("/batches/fefo/", item_id=self.raw.pk).status_code, 400)

    def test_holds(self):
        lot_id = self.receive_pass("r1", "10")
        held = self.post(
            "/holds/",
            {
                "lot_id": lot_id,
                "source_type": "manual",
                "reason": "이물 의심",
                "staff_id": self.staff.pk,
            },
        )
        self.assertEqual(held.status_code, 201, held.content.decode())
        hold = held.json()
        self.assertEqual((hold["target"], hold["is_open"]), ("lot", True))
        stock = self.get("/stock/lots/", item_id=self.raw.pk).json()["results"][0]
        self.assertEqual((stock["is_usable"], stock["active_hold_count"]), (False, 1))
        both = self.post(
            "/holds/",
            {
                "lot_id": lot_id,
                "batch_id": 1,
                "source_type": "MANUAL",
                "reason": "x",
                "staff_id": self.staff.pk,
            },
        )
        self.assertEqual(both.status_code, 400)
        ccp = self.post(
            "/holds/",
            {"lot_id": lot_id, "source_type": "CCP", "reason": "x", "staff_id": self.staff.pk},
        )
        self.assertEqual(ccp.status_code, 400)
        self.assertEqual(self.get("/holds/", open=1).json()["count"], 1)
        released = self.post(
            f"/holds/{hold['id']}/release/",
            {"disposition": "release", "reason": "이상 없음", "staff_id": self.staff.pk},
        ).json()
        self.assertEqual((released["is_open"], released["disposition"]), (False, "RELEASE"))
        self.assertEqual(self.get("/holds/", open=1).json()["count"], 0)
        self.assertEqual(self.get("/holds/999999/").status_code, 404)
