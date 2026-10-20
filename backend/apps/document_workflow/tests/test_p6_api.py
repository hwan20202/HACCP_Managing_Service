"""P6 S4a 정정 API 테스트 (수준 A). 이름의 tcNNN은 p6-s2-spec.md 7장의 P6-TC ID."""

import json

from django.conf import settings
from django.test import TestCase, override_settings

from apps.document_workflow import services
from apps.document_workflow.tests.base import (
    complete_again,
    doc,
    invariant_violations,
    new_document,
    setup_reference_data,
    slot_ids,
    version_of,
)
from apps.documents import flows as doc_flows
from apps.documents.tests.base import update_current
from apps.documents.tests.test_api import TRACE_MIDDLEWARE

REASON = "판정 오기"


class P6ApiTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.t = setup_reference_data()

    def tearDown(self):
        self.assertEqual(invariant_violations(), [])

    def post(self, path, body=None, staff=3, raw=None):
        headers = {} if staff is None else {"HTTP_X_STAFF_ID": str(staff)}
        data = raw if raw is not None else json.dumps(body if body is not None else {})
        return self.client.post(
            f"/api/v1/{path}", data=data, content_type="application/json", **headers
        )

    def assertError(self, response, status, code):
        self.assertEqual(response.status_code, status, response.content)
        self.assertEqual(response.json()["code"], code)

    def approved_document(self):
        document_id = new_document(self.t)
        request = services.submit(3, document_id, version_of(document_id))["request"]
        ids = slot_ids(request)
        for slot_no, actor in ((1, 3), (2, 5)):
            services.decide(actor, ids[slot_no], "approved")
        return document_id


class CorrectionApiTests(P6ApiTestCase):
    def test_tc060_request_format_and_staff(self):
        document_id = self.approved_document()
        path = f"documents/{document_id}/correction"
        v = version_of(document_id)
        for raw in ("[]", "not json"):
            with self.subTest(raw=raw):
                self.assertError(self.post(path, raw=raw), 400, "INVALID_REQUEST")
        for body in (
            {"expected_version": v, "reason": REASON, "x": 1},
            {"expected_version": str(v), "reason": REASON},
            {"reason": REASON},
            {"expected_version": True, "reason": REASON},
        ):
            with self.subTest(body=body):
                self.assertError(self.post(path, body), 400, "INVALID_REQUEST")
        body = {"expected_version": v, "reason": REASON}
        self.assertError(self.post(path, body, staff=None), 400, "STAFF_HEADER_MISSING")
        self.assertError(self.post(path, body, staff=99), 403, "INVALID_STAFF")
        self.assertEqual(doc.get_document(document_id)["status"], "approved")

    def test_tc061_start(self):
        document_id = self.approved_document()
        path = f"documents/{document_id}/correction"
        v = version_of(document_id)
        self.assertError(
            self.post(path, {"expected_version": v, "reason": " "}), 400, "VALIDATION_ERROR"
        )
        self.assertEqual(
            self.post(path, {"expected_version": v, "reason": ""}).json()["details"][0]["path"],
            "reason",
        )
        self.assertError(
            self.post(path, {"expected_version": v - 1, "reason": REASON}), 409, "VERSION_CONFLICT"
        )
        self.assertError(
            self.post("documents/99999/correction", {"expected_version": 1, "reason": REASON}),
            404,
            "DOCUMENT_NOT_FOUND",
        )
        ok = self.post(path, {"expected_version": v, "reason": REASON})
        self.assertEqual(ok.status_code, 200, ok.content)
        self.assertEqual(
            (ok.json()["status"], ok.json()["correction"]["reason"]), ("correcting", REASON)
        )
        self.assertError(
            self.post(path, {"expected_version": v + 1, "reason": REASON}),
            409,
            "INVALID_TRANSITION",
        )
        draft = new_document(self.t, completed=False)
        self.assertError(
            self.post(f"documents/{draft}/correction", {"expected_version": 1, "reason": REASON}),
            409,
            "INVALID_TRANSITION",
        )

    def test_tc062_methods(self):
        document_id = self.approved_document()
        for suffix in ("correction", "correction/cancel"):
            for method in ("get", "patch"):
                with self.subTest(suffix=suffix, method=method):
                    response = getattr(self.client, method)(
                        f"/api/v1/documents/{document_id}/{suffix}", HTTP_X_STAFF_ID="3"
                    )
                    self.assertEqual(response.status_code, 405)

    def test_tc066_cancel(self):
        document_id = self.approved_document()
        doc.start_correction(3, document_id, version_of(document_id), REASON)
        path = f"documents/{document_id}/correction/cancel"
        self.assertError(
            self.post(path, {"expected_version": version_of(document_id), "reason": "x"}),
            400,
            "INVALID_REQUEST",
        )
        ok = self.post(path, {"expected_version": version_of(document_id)})
        self.assertEqual((ok.status_code, ok.json()["status"]), (200, "approved"))
        self.assertError(
            self.post(path, {"expected_version": version_of(document_id)}),
            409,
            "INVALID_TRANSITION",
        )
        doc.start_correction(3, document_id, version_of(document_id), REASON)
        update_current(3, document_id, {"document": {"subject": "정정"}})
        self.assertError(
            self.post(path, {"expected_version": version_of(document_id)}),
            409,
            "CORRECTION_HAS_CHANGES",
        )


class CorrectionReadApiTests(P6ApiTestCase):
    def test_tc063_response_fields(self):
        document_id = self.approved_document()
        doc.start_correction(3, document_id, version_of(document_id), REASON)
        detail = self.client.get(f"/api/v1/documents/{document_id}").json()
        self.assertEqual(detail["correction"]["reason"], REASON)
        self.assertIn("corrections", detail)
        listed = self.client.get("/api/v1/documents?correcting=true").json()["items"]
        self.assertEqual([i["document_id"] for i in listed], [document_id])
        self.assertTrue(listed[0]["correcting"])
        self.assertError(self.client.get("/api/v1/documents?correcting=1"), 400, "INVALID_FILTER")
        complete_again(document_id)
        services.submit(3, document_id, version_of(document_id))
        history = self.client.get(f"/api/v1/documents/{document_id}/approval-requests").json()
        keys = {"effective", "superseded_by", "superseded_at", "is_correction", "correction_reason"}
        self.assertTrue(keys <= set(history["items"][0]))
        self.assertEqual(history["items"][0]["correction_reason"], REASON)
        request_id = history["items"][1]["request_id"]
        self.assertTrue(
            keys <= set(self.client.get(f"/api/v1/approval-requests/{request_id}").json())
        )
        inbox = self.client.get("/api/v1/approval-inbox?box=pending", HTTP_X_STAFF_ID="3").json()
        row = next(i for i in inbox["items"] if i["request"]["document_id"] == document_id)
        self.assertTrue({"is_correction", "correction_reason", "superseded"} <= set(row["request"]))


@override_settings(
    ROOT_URLCONF="apps.devtools.test_urls",
    MIDDLEWARE=[*settings.MIDDLEWARE, TRACE_MIDDLEWARE],
)
class CorrectionTraceApiTests(P6ApiTestCase):
    def ids(self, response):
        return [s["step_id"] for s in response.json()["trace"]["steps"]]

    def test_tc064_trace(self):
        document_id = self.approved_document()
        started = self.post(
            f"documents/{document_id}/correction",
            {"expected_version": version_of(document_id), "reason": REASON},
        )
        self.assertTrue(doc_flows.matches("DOC-COR", self.ids(started)), self.ids(started))
        cancelled = self.post(
            f"documents/{document_id}/correction/cancel",
            {"expected_version": version_of(document_id)},
        )
        self.assertTrue(doc_flows.matches("DOC-CCN", self.ids(cancelled)), self.ids(cancelled))
        snapshot = self.client.get(f"/api/dev/snapshot?document_id={document_id}").json()
        self.assertEqual(len(snapshot["tables"]["document_correction"]), 1)


class CorrectionNoTraceTests(P6ApiTestCase):
    def test_tc065_no_trace_outside_dev(self):
        document_id = self.approved_document()
        response = self.post(
            f"documents/{document_id}/correction",
            {"expected_version": version_of(document_id), "reason": REASON},
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("trace", response.json())
        self.assertNotIn("X-Trace-Id", response)
