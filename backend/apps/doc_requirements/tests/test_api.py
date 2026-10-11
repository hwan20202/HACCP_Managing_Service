"""REQ API 테스트 A (s2-spec 7장 REQ-TC-040~043)."""

import json

from django.conf import settings
from django.test import TestCase, override_settings

from apps.doc_requirements import flows
from apps.documents.models import Document

from .base import DAY, setup_req

DEV = override_settings(
    ROOT_URLCONF="apps.devtools.test_urls",
    MIDDLEWARE=[*settings.MIDDLEWARE, "apps.devtools.middleware.TraceMiddleware"],
)

LOT_BODY = {
    "item_id": 1,
    "material_kind": "원료",
    "supplier_name": " 고흥농협 ",
    "received_date": DAY,
    "quantity": 450,
    "unit": "kg",
    "expiration_date": "2027-05-01",
    "origin": "국내",
}
BATCH_BODY = {
    "item_id": 2,
    "process_type": "MANUFACTURE",
    "manufactured_date": DAY,
    "quantity_kg": 900,
}


def lot_count():
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM lots")
        return cursor.fetchone()[0]


class ReqTestCase(TestCase):
    def setUp(self):
        setup_req()

    def post(self, path, body=None, staff="3"):
        headers = {"HTTP_X_STAFF_ID": staff} if staff else {}
        return self.client.post(
            path, data=json.dumps(body or {}), content_type="application/json", **headers
        )

    def assertError(self, response, status, code):
        self.assertEqual(
            (response.status_code, response.json()["code"]), (status, code), response.content
        )


class LookupApiTests(ReqTestCase):
    def test_tc040(self):
        from django.db import transaction

        from apps.doc_requirements import services

        with transaction.atomic():
            services.require_for_lot(3, 88)
            services.require_for_batch(3, 12)
        res = self.client.get("/api/v1/lots/88/documents")
        self.assertEqual(res.status_code, 200)
        self.assertEqual([d["type_code"] for d in res.json()["documents"]], ["D01", "D02", "D03"])
        self.assertEqual(res.json()["lot"]["lot_number"], "RM-1011-01")
        self.assertError(self.client.get("/api/v1/lots/999/documents"), 404, "LOT_NOT_FOUND")
        self.assertError(self.client.get("/api/v1/lots/90/documents"), 409, "LOT_NOT_INCOMING")
        res = self.client.get("/api/v1/batches/12/documents")
        self.assertEqual([d["process_code"] for d in res.json()["documents"]], ["1P", "2B", "3P"])
        self.assertError(self.client.get("/api/v1/batches/999/documents"), 404, "BATCH_NOT_FOUND")
        self.assertEqual(self.client.post("/api/v1/lots/88/documents").status_code, 405)


@DEV
class DevLotApiTests(ReqTestCase):
    def test_tc041_create_and_require(self):
        res = self.post("/api/dev/req/lots", LOT_BODY)
        self.assertEqual(res.status_code, 201, res.content)
        body = res.json()
        self.assertEqual(
            (body["lot"]["lot_number"], body["lot"]["supplier_name"], body["lot"]["quantity"]),
            ("RM-1011-04", "고흥농협", 450),
        )
        self.assertEqual(
            [d["result"] for d in body["result"]["documents"]], ["created", "created", "row_added"]
        )
        steps = [s["step_id"] for s in body["trace"]["steps"]]
        self.assertTrue(flows.matches("REQ-DEV-LOT", steps), steps)
        self.assertEqual(
            self.post("/api/dev/req/lots", LOT_BODY).json()["lot"]["lot_number"], "RM-1011-05"
        )

    def test_tc041_validation_failure_header(self):
        bad = {
            **LOT_BODY,
            "material_kind": "RAW",
            "supplier_name": "가" * 51,
            "received_date": "2026-1-5",
            "quantity": 0,
            "unit": "lb",
            "origin": "중국",
            "item_id": 999,
        }
        res = self.post("/api/dev/req/lots", bad)
        self.assertError(res, 400, "VALIDATION_ERROR")
        self.assertEqual(
            {d["path"] for d in res.json()["details"]},
            {
                "item_id",
                "material_kind",
                "supplier_name",
                "received_date",
                "quantity",
                "unit",
                "origin",
            },
        )
        self.assertError(
            self.post("/api/dev/req/lots", {**LOT_BODY, "x": 1}), 400, "INVALID_REQUEST"
        )
        before = (lot_count(), Document.objects.count())
        self.assertError(
            self.post("/api/dev/req/lots", {**LOT_BODY, "fail_after": True}),
            500,
            "SIMULATED_FAILURE",
        )
        self.assertEqual((lot_count(), Document.objects.count()), before)
        self.assertError(
            self.post("/api/dev/req/lots", LOT_BODY, staff=None), 400, "STAFF_HEADER_MISSING"
        )

    def test_tc041_recall(self):
        self.post("/api/dev/req/lots", LOT_BODY)
        res = self.post("/api/dev/req/lots/88/require")
        self.assertEqual(res.status_code, 200, res.content)
        res = self.post("/api/dev/req/lots/88/require")
        self.assertEqual(
            [d["result"] for d in res.json()["documents"]], ["existing", "existing", "row_existing"]
        )
        steps = [s["step_id"] for s in res.json()["trace"]["steps"]]
        self.assertTrue(flows.matches("REQ-DEV-RE-LOT", steps), steps)
        from apps.devstock.models import DevLotReceipt

        self.assertIsNotNone(DevLotReceipt.objects.get(pk=88).touched_at)
        self.assertError(self.post("/api/dev/req/lots/999/require"), 404, "LOT_NOT_FOUND")
        self.assertError(
            self.post("/api/dev/req/lots/88/require", {"x": 1}), 400, "INVALID_REQUEST"
        )


@DEV
class DevBatchApiTests(ReqTestCase):
    def test_tc042(self):
        res = self.post("/api/dev/req/batches", BATCH_BODY)
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.json()["batch"]["batch_number"], "PB-1011-06")
        self.assertEqual(len(res.json()["result"]["documents"]), 3)
        steps = [s["step_id"] for s in res.json()["trace"]["steps"]]
        self.assertTrue(flows.matches("REQ-DEV-BAT", steps), steps)
        res = self.post("/api/dev/req/batches", {**BATCH_BODY, "process_type": "PACKAGING"})
        self.assertEqual((res.status_code, res.json()["result"]["documents"]), (201, []))
        res = self.post(
            "/api/dev/req/batches",
            {**BATCH_BODY, "quantity_kg": -1, "process_type": "X", "manufactured_date": "x"},
        )
        self.assertEqual(
            {d["path"] for d in res.json()["details"]},
            {"quantity_kg", "process_type", "manufactured_date"},
        )
        before = Document.objects.count()
        self.assertError(
            self.post("/api/dev/req/batches", {**BATCH_BODY, "fail_after": True}),
            500,
            "SIMULATED_FAILURE",
        )
        self.assertEqual(Document.objects.count(), before)
        res = self.post("/api/dev/req/batches/12/require")
        self.assertEqual(res.status_code, 200)
        res = self.post("/api/dev/req/batches/12/require")
        self.assertEqual([d["result"] for d in res.json()["documents"]], ["existing"] * 3)
        self.assertTrue(
            flows.matches("REQ-DEV-RE-BAT", [s["step_id"] for s in res.json()["trace"]["steps"]])
        )
        self.assertError(self.post("/api/dev/req/batches/999/require"), 404, "BATCH_NOT_FOUND")
        self.assertError(self.post("/api/dev/req/batches/14/require"), 409, "BATCH_CANCELLED")


class DevListApiTests(ReqTestCase):
    @DEV
    def test_tc043_lists(self):
        self.post("/api/dev/req/lots/88/require")
        res = self.client.get(f"/api/dev/req/lots?date={DAY}")
        items = res.json()["items"]
        self.assertEqual([i["lot_id"] for i in items], [89, 88])
        self.assertEqual([d["type_code"] for d in items[1]["documents"]], ["D01", "D02", "D03"])
        self.assertEqual(items[0]["documents"], [])
        self.assertEqual(self.client.get("/api/dev/req/lots?date=2026-01-01").json()["items"], [])
        self.assertError(self.client.get("/api/dev/req/lots?date=bad"), 400, "VALIDATION_ERROR")
        batches = self.client.get("/api/dev/req/batches").json()["items"]
        self.assertEqual([b["production_batch_id"] for b in batches], [15, 14, 13, 12])
        names = [i["name"] for i in self.client.get("/api/dev/req/items").json()["items"]]
        self.assertEqual(names, ["유자", "유자차", "유자환"])

    def test_tc043_not_routed_without_console(self):
        self.assertEqual(self.client.get("/api/dev/req/lots").status_code, 404)
        self.assertEqual(self.post("/api/dev/req/lots", LOT_BODY).status_code, 404)
