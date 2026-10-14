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
    "supplier_name": " 고흥농협 ",
    "received_date": DAY,
    "quantity": 450,
    "expiration_date": "2027-05-01",
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
        # P6a-TC-040: 문서 단위라 section_id 없음(P6a-S2 Q4)
        self.assertTrue(all("section_id" not in d for d in res.json()["documents"]))
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
            # LOT 번호는 수불 규칙: 원료는 소비기한 있음 → LOT 약어 + 소비기한(수불 0007)
            ("X01270501", "고흥농협", 450),
        )
        self.assertEqual([d["result"] for d in body["result"]["documents"]], ["created"] * 3)
        steps = [s["step_id"] for s in body["trace"]["steps"]]
        self.assertTrue(flows.matches("REQ-DEV-LOT", steps), steps)
        self.assertEqual(
            self.post("/api/dev/req/lots", LOT_BODY).json()["lot"]["lot_number"], "X01270501-2"
        )

    def test_tc041_validation_failure_header(self):
        bad = {
            **LOT_BODY,
            "supplier_name": "가" * 51,
            "received_date": "2026-1-5",
            "quantity": 0,
            "item_id": 999,
        }
        res = self.post("/api/dev/req/lots", bad)
        self.assertError(res, 400, "VALIDATION_ERROR")
        self.assertEqual(
            {d["path"] for d in res.json()["details"]},
            {"item_id", "supplier_name", "received_date", "quantity"},
        )
        # 입고 품목은 원료·포장재만(C2 — 수불 입고 규칙). 품목 2는 완제품
        res = self.post("/api/dev/req/lots", {**LOT_BODY, "item_id": 2})
        self.assertError(res, 400, "VALIDATION_ERROR")
        self.assertEqual([d["path"] for d in res.json()["details"]], ["item_id"])
        # 구분·단위·원산지는 품목 값이라 받지 않는다(C2)
        for key, value in (("x", 1), ("material_kind", "원료"), ("unit", "kg"), ("origin", "국내")):
            with self.subTest(key=key):
                self.assertError(
                    self.post("/api/dev/req/lots", {**LOT_BODY, key: value}), 400, "INVALID_REQUEST"
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
        self.assertEqual([d["result"] for d in res.json()["documents"]], ["existing"] * 3)
        steps = [s["step_id"] for s in res.json()["trace"]["steps"]]
        self.assertTrue(flows.matches("REQ-DEV-RE-LOT", steps), steps)
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
        # 수불 0006(MVP 벌크 범위): 새 포장배치는 만들지 않는다. 포장배치 = CCP 없음은
        # REQ 서비스 테스트(예전 포장배치 13)로 확인
        res = self.post("/api/dev/req/batches", {**BATCH_BODY, "process_type": "PACKAGING"})
        self.assertError(res, 400, "INVENTORY_REJECTED")
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


@DEV
class DevSnapshotTests(ReqTestCase):
    """P5 S5: 개발 콘솔 ④ 패널용 LOT·배치 단위 스냅샷."""

    def test_scope_snapshot(self):
        self.post("/api/dev/req/lots/88/require")
        data = self.client.get("/api/dev/snapshot?lot_id=88").json()
        self.assertEqual((data["scope"], data["exists"]), ({"lot": 88}, True))
        self.assertEqual(len(data["tables"]["document"]), 3)
        self.assertEqual([r["lot_id"] for r in data["tables"]["incoming_receipts"]], [88])
        self.assertEqual(data["tables"]["lots"][0]["lot_number"], "RM-1011-01")
        data = self.client.get("/api/dev/snapshot?batch_id=12").json()
        self.assertEqual((data["exists"], data["tables"]["document"]), (True, []))
        self.assertFalse(self.client.get("/api/dev/snapshot?lot_id=999").json()["exists"])
        self.assertEqual(self.client.get("/api/dev/snapshot?lot_id=x").status_code, 400)

    def test_date_scope_snapshot(self):
        """S6-39 K1: 새 LOT·배치 호출은 실행 전 LOT id가 없어 그날 범위로 비교한다."""
        self.post("/api/dev/req/lots/88/require")
        self.post("/api/dev/req/lots/89/require")
        data = self.client.get(f"/api/dev/snapshot?received_date={DAY}").json()
        self.assertEqual((data["scope"], data["exists"]), ({"received_date": DAY}, True))
        self.assertEqual([r["id"] for r in data["tables"]["lots"]], [88, 89])
        types = sorted(d["template_id"] for d in data["tables"]["document"])
        self.assertEqual(len(types), 6)  # LOT 2개 × D01·D02·D03(P6a — D03도 LOT마다)
        data = self.client.get(f"/api/dev/snapshot?manufactured_date={DAY}").json()
        self.assertEqual([r["id"] for r in data["tables"]["production_batches"]], [12, 13, 14, 15])
        empty = self.client.get("/api/dev/snapshot?received_date=2026-01-01").json()
        self.assertEqual((empty["exists"], empty["tables"]["lots"]), (False, []))
        self.assertEqual(self.client.get("/api/dev/snapshot?received_date=1011").status_code, 400)
