"""APR API 테스트 (수준 A). 쓰기 API는 P3 WF가 열기 때문에 준비 데이터는 서비스 함수로 만든다."""

import copy

from django.conf import settings
from django.db import transaction
from django.test import TestCase, override_settings

from apps.approvals import flows, services
from apps.approvals.tests.base import (
    SLOTS,
    ensure_staff,
    make_document,
    make_template,
    ref,
    snapshot_for,
)

TRACE_MIDDLEWARE = "apps.devtools.middleware.TraceMiddleware"


class AprApiTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_staff()
        cls.tpl = make_template()
        cls.doc = make_document(cls.tpl)
        with transaction.atomic():
            cls.req = services.open_request(
                ref(cls.doc, cls.tpl), snapshot_for(cls.doc), 3, copy.deepcopy(SLOTS)
            )
            services.decide(cls.req["slots"][0]["approval_id"], 3, "approved")

    def get(self, path, staff=2):
        headers = {} if staff is None else {"HTTP_X_STAFF_ID": str(staff)}
        return self.client.get(f"/api/v1/{path}", **headers)

    def assertError(self, response, status, code):
        self.assertEqual(response.status_code, status, response.content)
        self.assertEqual(response.json()["code"], code)
        self.assertEqual(set(response.json()), {"code", "message", "details"})


class InboxApiTests(AprApiTestCase):
    def test_tc040_staff_header(self):
        self.assertError(self.get("approval-inbox", staff=None), 400, "STAFF_HEADER_MISSING")
        self.assertError(self.get("approval-inbox", staff=99), 403, "INVALID_STAFF")

    def test_tc041_pending_and_done(self):
        body = self.get("approval-inbox?box=pending").json()
        self.assertEqual((body["total"], body["page"]), (1, 1))
        item = body["items"][0]
        self.assertEqual(item["slot_no"], 2)
        self.assertEqual(item["request"]["progress"], {"total": 3, "approved": 1, "pending": 2})
        self.assertEqual(item["request"]["work_date"], "2026-10-10")
        self.assertNotIn("snapshot", item["request"])
        done = self.get("approval-inbox?box=done", staff=3).json()
        self.assertEqual([i["state"] for i in done["items"]], ["approved"])
        self.assertNotIn("trace", body)  # 테스트 설정 = 개발 콘솔 꺼짐 (TC-046)

    def test_tc042_invalid_filter(self):
        for query in ("box=all", "from=2026-10-09&to=2026-10-01", "page=0", "template_id=x"):
            with self.subTest(query):
                self.assertError(self.get(f"approval-inbox?{query}"), 400, "INVALID_FILTER")

    def test_tc043_request_detail(self):
        body = self.get(f"approval-requests/{self.req['request_id']}").json()
        self.assertEqual(body["snapshot"]["document_id"], self.doc)
        self.assertEqual([s["state"] for s in body["slots"]], ["approved", "pending", "pending"])
        self.assertError(self.get("approval-requests/99999"), 404, "REQUEST_NOT_FOUND")

    def test_tc044_document_history(self):
        items = self.get(f"documents/{self.doc}/approval-requests").json()["items"]
        self.assertEqual([i["attempt"] for i in items], [1])
        self.assertEqual(
            self.get("documents/99999/approval-requests").json(),
            {"document_id": 99999, "items": []},
        )

    def test_read_only_methods(self):
        self.assertEqual(self.client.post("/api/v1/approval-inbox").status_code, 405)


@override_settings(
    ROOT_URLCONF="apps.devtools.test_urls", MIDDLEWARE=[*settings.MIDDLEWARE, TRACE_MIDDLEWARE]
)
class AprTraceTests(AprApiTestCase):
    """APR-TC-045: 개발 콘솔이 켜졌을 때 trace 단계 순서가 s2-flows와 같다."""

    def ids(self, response):
        return [s["step_id"] for s in response.json()["trace"]["steps"]]

    def test_tc045_inbox(self):
        ids = self.ids(self.get("approval-inbox"))
        self.assertTrue(flows.matches("APR-INB", ids), ids)

    def test_tc045_detail_and_history(self):
        ids = self.ids(self.get(f"approval-requests/{self.req['request_id']}"))
        self.assertTrue(flows.matches("APR-GET", ids), ids)
        ids = self.ids(self.get(f"documents/{self.doc}/approval-requests"))
        self.assertTrue(flows.matches("APR-HIS", ids), ids)

    def test_tc045_snapshot_shows_approval_tables(self):
        snap = self.client.get(f"/api/dev/snapshot?document_id={self.doc}").json()
        self.assertEqual(len(snap["tables"]["approval_request"]), 1, snap)
        self.assertNotIn("snapshot_json", snap["tables"]["approval_request"][0])
        self.assertEqual(len(snap["tables"]["approval"]), 3)
