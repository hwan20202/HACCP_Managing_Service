"""WF API 테스트 (수준 A). Django 테스트 Client로 /api/v1/ 을 호출한다."""

import json

from django.conf import settings
from django.test import TestCase, override_settings

from apps.document_workflow import flows
from apps.document_workflow.tests.base import (
    invariant_violations,
    new_document,
    setup_reference_data,
    slot_ids,
    slots,
    version_of,
)

TRACE_MIDDLEWARE = "apps.devtools.middleware.TraceMiddleware"


class WfApiTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.t = setup_reference_data()

    def tearDown(self):
        self.assertEqual(invariant_violations(), [])  # WF-TC-030

    def post(self, path, body=None, staff=3, raw=None):
        headers = {} if staff is None else {"HTTP_X_STAFF_ID": str(staff)}
        data = raw if raw is not None else json.dumps(body)
        return self.client.post(
            f"/api/v1/{path}", data=data, content_type="application/json", **headers
        )

    def submit(self, document_id=None, **overrides):
        document_id = document_id or new_document(self.t)
        body = {"expected_version": version_of(document_id), "slots": slots(), **overrides}
        return self.post(f"documents/{document_id}/submit", body)

    def assertError(self, response, status, code):
        self.assertEqual(response.status_code, status, response.content)
        self.assertEqual(response.json()["code"], code)
        self.assertEqual(set(response.json()), {"code", "message", "details"})


class SubmitApiTests(WfApiTestCase):
    def test_tc040_submit(self):
        response = self.submit()
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(set(body), {"document", "request"})
        self.assertEqual(body["document"]["status"], "submitted")
        self.assertEqual(body["request"]["attempt"], 1)
        self.assertNotIn("snapshot", body["request"])
        self.assertNotIn("trace", body)  # WF-TC-048: 테스트 설정 = 개발 콘솔 꺼짐

    def test_tc041_staff_header(self):
        document_id = new_document(self.t)
        body = {"expected_version": 2, "slots": slots()}
        path = f"documents/{document_id}/submit"
        self.assertError(self.post(path, body, staff=None), 400, "STAFF_HEADER_MISSING")
        self.assertError(self.post(path, body, staff=99), 403, "INVALID_STAFF")
        decision = "approvals/1/decision"
        self.assertError(
            self.post(decision, {"result": "approved"}, staff=None), 400, "STAFF_HEADER_MISSING"
        )

    def test_tc042_invalid_body(self):
        document_id = new_document(self.t)
        path = f"documents/{document_id}/submit"
        cases = {
            "JSON 아님": dict(raw="{"),
            "배열 본문": dict(raw="[]"),
            "알 수 없는 키": dict(body={"expected_version": 1, "slots": slots(), "x": 1}),
            "버전 없음": dict(body={"slots": slots()}),
            "결재선 없음": dict(body={"expected_version": 1}),
            "버전 문자열": dict(body={"expected_version": "1", "slots": slots()}),
            "버전 bool": dict(body={"expected_version": True, "slots": slots()}),
            "버전 0": dict(body={"expected_version": 0, "slots": slots()}),
        }
        for name, kwargs in cases.items():
            with self.subTest(name):
                self.assertError(self.post(path, **kwargs), 400, "INVALID_REQUEST")
        self.assertEqual(version_of(document_id), 2)  # 작성완료 상태 그대로

    def test_tc043_domain_errors(self):
        document_id = new_document(self.t)
        bad = [{"slot_no": 1, "approver_id": 2}, {"slot_no": 2, "approver_id": 2}]
        self.assertError(self.submit(document_id, slots=bad), 400, "INVALID_SLOTS")
        conflict = self.submit(document_id, expected_version=9)
        self.assertError(conflict, 409, "VERSION_CONFLICT")
        self.assertEqual(conflict.json()["details"][0]["current"], 2)
        self.assertEqual(self.submit(document_id).status_code, 201)
        self.assertError(self.submit(document_id), 409, "DOCUMENT_LOCKED")
        self.assertError(
            self.post("documents/99999/submit", {"expected_version": 1, "slots": slots()}),
            404,
            "DOCUMENT_NOT_FOUND",
        )

    def test_tc046_methods(self):
        document_id = new_document(self.t)
        self.assertEqual(
            self.client.get(f"/api/v1/documents/{document_id}/submit").status_code, 405
        )
        self.assertEqual(self.client.put("/api/v1/approvals/1/decision").status_code, 405)


class DecisionApiTests(WfApiTestCase):
    def setUp(self):
        self.out = self.submit().json()
        self.ids = slot_ids(self.out["request"])

    def decide(self, slot_no, staff, body):
        return self.post(f"approvals/{self.ids[slot_no]}/decision", body, staff=staff)

    def test_tc044_middle_last_reject(self):
        middle = self.decide(1, 3, {"result": "approved"})
        self.assertEqual(middle.status_code, 200)
        self.assertEqual(
            set(middle.json()),
            {"request_id", "document_id", "request_status", "decided", "pending_count", "document"},
        )
        self.assertIsNone(middle.json()["document"])
        self.decide(2, 2, {"result": "approved", "comment": "확인"})
        last = self.decide(3, 1, {"result": "approved"}).json()
        self.assertEqual(
            (last["request_status"], last["document"]["status"]), ("approved", "approved")
        )

    def test_tc044_reject(self):
        body = self.decide(2, 2, {"result": "rejected", "comment": "온도 누락"}).json()
        self.assertEqual(
            (body["request_status"], body["document"]["status"]), ("rejected", "rejected")
        )

    def test_tc045_errors(self):
        self.assertError(self.decide(1, 3, {"result": "approved", "x": 1}), 400, "INVALID_REQUEST")
        self.assertError(self.decide(1, 3, {"comment": "a"}), 400, "INVALID_REQUEST")
        self.assertError(self.decide(1, 3, {"result": "ok"}), 400, "INVALID_DECISION")
        self.assertError(self.decide(2, 2, {"result": "rejected"}), 400, "COMMENT_REQUIRED")
        self.assertError(self.decide(1, 4, {"result": "approved"}), 403, "NOT_YOUR_SLOT")
        self.assertError(
            self.post("approvals/99999/decision", {"result": "approved"}), 404, "APPROVAL_NOT_FOUND"
        )
        self.decide(1, 3, {"result": "approved"})
        self.assertError(self.decide(1, 3, {"result": "approved"}), 409, "ALREADY_DECIDED")
        self.decide(2, 2, {"result": "rejected", "comment": "누락"})
        self.assertError(self.decide(3, 1, {"result": "approved"}), 409, "REQUEST_CLOSED")


@override_settings(
    ROOT_URLCONF="apps.devtools.test_urls",
    MIDDLEWARE=[*settings.MIDDLEWARE, TRACE_MIDDLEWARE],
)
class WfTraceApiTests(WfApiTestCase):
    """WF-TC-047: 개발 콘솔이 켜졌을 때 trace 단계 순서가 s2-flows 7장과 같다."""

    def ids(self, response):
        return [s["step_id"] for s in response.json()["trace"]["steps"]]

    def test_tc047_submit_and_decisions(self):
        response = self.submit()
        self.assertTrue(flows.matches("WF-SUB", self.ids(response)), self.ids(response))
        sids = slot_ids(response.json()["request"])
        cases = [
            (sids[1], 3, {"result": "approved"}, "WF-DEC-PROGRESS"),
            (sids[2], 2, {"result": "approved"}, "WF-DEC-PROGRESS"),
            (sids[3], 1, {"result": "approved"}, "WF-DEC-APPROVED"),
        ]
        for approval_id, staff, body, flow in cases:
            r = self.post(f"approvals/{approval_id}/decision", body, staff=staff)
            self.assertTrue(flows.matches(flow, self.ids(r)), (flow, self.ids(r)))

    def test_tc047_reject(self):
        sids = slot_ids(self.submit().json()["request"])
        r = self.post(
            f"approvals/{sids[2]}/decision", {"result": "rejected", "comment": "x"}, staff=2
        )
        self.assertTrue(flows.matches("WF-DEC-REJECTED", self.ids(r)), self.ids(r))

    def test_tc047_rollback_visible(self):
        document_id = new_document(self.t)
        r = self.submit(document_id, expected_version=9)
        tx = next(s for s in r.json()["trace"]["steps"] if s["step_id"] == "WF-SUB-04")
        self.assertEqual(tx["result"], "fail")
        snap = self.client.get(f"/api/dev/snapshot?document_id={document_id}").json()
        self.assertEqual(snap["tables"]["approval_request"], [])

    def test_tc047_dev_flows_listed(self):
        listed = self.client.get("/api/dev/flows").json()["flows"]
        self.assertTrue({"WF-SUB", "WF-DEC-APPROVED"} <= set(listed))

    def test_p7_s5_dev_flows_batch(self):
        """P7 S5: 콘솔 항목별 비교용 batch(머리·항목 묶음·꼬리) — 항목 1개면 FLOWS의 흐름과 같다."""
        data = self.client.get("/api/dev/flows").json()
        batch, listed = data["batch"], data["flows"]
        self.assertEqual(set(batch), {"WF-BAP", "WF-BSB", "DOC-BIN"})
        one = {"WF-BAP": "approved", "WF-BSB": "submitted", "DOC-BIN": "changed"}
        for flow_id, kind in one.items():
            spec = batch[flow_id]
            self.assertEqual(spec["head"] + spec["items"][kind] + spec["tail"], listed[flow_id])
            starts = {items[0] for items in spec["items"].values()}
            self.assertEqual(len(starts), 1, flow_id)  # 콘솔은 항목 시작 단계 하나로 끊는다
