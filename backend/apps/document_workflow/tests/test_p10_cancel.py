"""P10 S4 상신 취소 WF-F05·APR-A7·DOC-F23 (p10-s2-spec 6장 P10-TC-020~025).

이름의 tcNNN은 P10-TC ID. 동시 실행(TC-026)은 test_p10_concurrency(파일 DB).
"""

import json
from unittest import mock

from django.test import TestCase

from apps.approvals import services as apr
from apps.document_workflow import services
from apps.document_workflow.tests.base import (
    complete_again,
    db_state,
    doc,
    invariant_violations,
    new_document,
    setup_reference_data,
    slot_ids,
    slots,
    sql,
    version_of,
)
from apps.documents import signals
from apps.documents.tests.base import update_current

TWO = [
    {"slot_no": 1, "label": "담당자", "approver_id": 2},
    {"slot_no": 2, "label": "HACCP팀장", "approver_id": 1},
]


class CancelTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.t = setup_reference_data()

    def tearDown(self):
        self.assertEqual(invariant_violations(), [])

    def submitted(self, line=None, requester=3):
        document_id = new_document(self.t)
        request = services.submit(requester, document_id, version_of(document_id), line or TWO)
        return document_id, request["request"]

    def post(self, request_id, staff=3, raw=None):
        headers = {} if staff is None else {"HTTP_X_STAFF_ID": str(staff)}
        return self.client.post(
            f"/api/v1/approval-requests/{request_id}/cancel",
            data=raw if raw is not None else "",
            content_type="application/json",
            **headers,
        )

    def assertError(self, response, status, code):
        self.assertEqual(response.status_code, status, response.content)
        self.assertEqual(response.json()["code"], code)


class CancelTests(CancelTestCase):
    def test_tc020_cancel_after_one_approval(self):
        document_id, request = self.submitted()
        ids = slot_ids(request)
        services.decide(2, ids[1], "approved")
        before = version_of(document_id)
        response = self.post(request["request_id"])
        self.assertEqual(response.status_code, 200, response.content)
        out = response.json()
        self.assertEqual(out["request"]["status"], "cancelled")
        self.assertIsNotNone(out["request"]["closed_at"])
        states = {s["slot_no"]: s["state"] for s in out["request"]["slots"]}
        self.assertEqual(states, {1: "approved", 2: "skipped"})
        self.assertEqual(out["document"]["status"], "completed")
        self.assertEqual(out["document"]["version"], before + 1)
        detail = doc.get_document(document_id)
        self.assertEqual(detail["status"], "completed")
        self.assertIsNotNone(detail["completed_at"])  # 작성완료 기록 그대로
        skipped = sql(
            "SELECT decided_at FROM approval WHERE request_id=%s AND slot_no=2",
            [request["request_id"]],
        )[0][0]
        self.assertIsNotNone(skipped)

    def test_flow_steps(self):
        from apps.core import trace
        from apps.document_workflow import flows

        _, request = self.submitted()
        record, token = trace.start("TEST", "p10")
        try:
            services.cancel_submission(3, request["request_id"])
        finally:
            trace.stop(token)
        steps = [s.step_id for s in record.steps]
        self.assertTrue(flows.matches("WF-CAN", ["WF-CAN-01", *steps]), steps)

    def test_tc020a_no_signal(self):
        document_id, request = self.submitted()
        calls = []

        def receiver(sender, **kwargs):
            calls.append(kwargs["event"])

        signals.document_transitioned.connect(receiver)
        try:
            with mock.patch("apps.doc_effects.adapter.judge_incoming_lot") as judge:
                services.cancel_submission(3, request["request_id"])
        finally:
            signals.document_transitioned.disconnect(receiver)
        self.assertEqual(calls, [])  # 생명주기 신호 없음
        judge.assert_not_called()  # 수불 판정 전달 0
        self.assertEqual(doc.get_document(document_id)["status"], "completed")

    def test_tc020b_queries_after_cancel(self):
        document_id, request = self.submitted()
        services.decide(2, slot_ids(request)[1], "approved")
        services.cancel_submission(3, request["request_id"])
        one = apr.get_request(request["request_id"])
        self.assertEqual(one["status"], "cancelled")
        self.assertEqual([s["state"] for s in one["slots"]], ["approved", "skipped"])
        history = apr.list_requests(document_id)["items"]
        self.assertEqual(history[0]["status"], "cancelled")
        progress = apr.document_progress([document_id], 2)["documents"][document_id]
        self.assertEqual(
            (progress["status"], progress["approved"], progress["total"], progress["my_slot"]),
            ("cancelled", 1, 2, None),
        )

    def test_tc021_correction_resubmission(self):
        document_id = new_document(self.t)
        request = services.submit(3, document_id, version_of(document_id), TWO)["request"]
        for slot_no, actor in ((1, 2), (2, 1)):
            services.decide(actor, slot_ids(request)[slot_no], "approved")
        doc.start_correction(3, document_id, version_of(document_id), "판정 오기")
        complete_again(document_id)
        again = services.submit(3, document_id, version_of(document_id), TWO)["request"]
        self.assertTrue(again["is_correction"])
        out = services.cancel_submission(3, again["request_id"])
        self.assertEqual(out["request"]["status"], "cancelled")
        self.assertTrue(out["request"]["is_correction"])
        detail = doc.get_document(document_id)
        self.assertEqual(detail["status"], "completed")
        open_corr = sql(
            "SELECT COUNT(*) FROM document_correction WHERE document_id=%s AND closed_at IS NULL",
            [document_id],
        )[0][0]
        self.assertEqual(open_corr, 1)  # 열린 정정 그대로("작성완료 · 정정")
        listed = doc.list_documents({"status": "completed"})["items"]
        row = next(r for r in listed if r.get("document_id") == document_id)
        self.assertTrue(row["correcting"])

    def test_tc022_failures(self):
        document_id, request = self.submitted()
        rid = request["request_id"]
        before = db_state(document_id)
        self.assertError(self.post(rid, staff=2), 403, "NOT_REQUESTER")
        self.assertError(self.post(rid, staff=None), 400, "STAFF_HEADER_MISSING")
        self.assertError(self.post(rid, staff=99), 403, "INVALID_STAFF")
        self.assertError(self.post(99999), 404, "REQUEST_NOT_FOUND")
        self.assertError(self.post(rid, raw=json.dumps({"reason": "x"})), 400, "INVALID_REQUEST")
        self.assertEqual(db_state(document_id), before)
        # 빈 객체 본문은 허용
        self.assertEqual(self.post(rid, raw="{}").status_code, 200)
        self.assertError(self.post(rid), 409, "REQUEST_CLOSED")  # 이미 취소
        # 승인으로 끝남 / 반려됨
        approved_doc, approved = self.submitted()
        for slot_no, actor in ((1, 2), (2, 1)):
            services.decide(actor, slot_ids(approved)[slot_no], "approved")
        rejected_doc, rejected = self.submitted()
        services.decide(2, slot_ids(rejected)[1], "rejected", "온도 누락")
        for document, req in ((approved_doc, approved), (rejected_doc, rejected)):
            with self.subTest(status=req["request_id"]):
                state = db_state(document)
                self.assertError(self.post(req["request_id"]), 409, "REQUEST_CLOSED")
                self.assertEqual(db_state(document), state)

    def test_tc023_document_not_submitted_rolls_back(self):
        document_id, request = self.submitted()
        # 데이터 어긋남 흉내: 회차는 진행 중, 문서는 작성완료
        sql("UPDATE document SET status='completed' WHERE document_id=%s", [document_id])
        before = db_state(document_id)
        self.assertError(self.post(request["request_id"]), 409, "INVALID_TRANSITION")
        self.assertEqual(db_state(document_id), before)
        sql("UPDATE document SET status='submitted' WHERE document_id=%s", [document_id])

    def test_tc024_resubmit_after_cancel(self):
        document_id, request = self.submitted()
        services.cancel_submission(3, request["request_id"])
        again = services.submit(3, document_id, version_of(document_id), TWO)["request"]
        self.assertEqual(again["attempt"], request["attempt"] + 1)
        self.assertEqual(again["status"], "in_progress")

    def test_tc024b_edit_after_cancel(self):
        """취소 뒤 작성완료 문서는 작성 재개 → 수정 → 다시 작성완료할 수 있다(P4 그대로)."""
        document_id, request = self.submitted()
        services.cancel_submission(3, request["request_id"])
        doc.reopen_document(3, document_id, version_of(document_id))
        update_current(3, document_id, {"document": {"subject": "취소 뒤 고침"}})
        complete_again(document_id)
        self.assertEqual(doc.get_document(document_id)["status"], "completed")

    def test_tc025_inbox(self):
        document_id, request = self.submitted(line=slots())
        ids = slot_ids(request)
        services.decide(3, ids[1], "approved")  # staff 3 = 상신자이자 1번 칸 결재자
        services.cancel_submission(3, request["request_id"])
        pending = apr.list_inbox(2, "pending")["items"]
        rid = request["request_id"]
        self.assertFalse([i for i in pending if i["request"]["request_id"] == rid])
        done = apr.list_inbox(3, "done")["items"]
        mine = next(i for i in done if i["request"]["request_id"] == request["request_id"])
        self.assertEqual(mine["request_status"], "cancelled")
        self.assertEqual(mine["state"], "approved")
