"""WF 메소드 테스트 (수준 M). 이름의 tcNNN은 document-workflow/s2-spec.md 7장의 WF-TC ID.

실제 DOC·APR 함수와 함께 실행한다(대역 없음). 쓰기 테스트는 끝에 불변식(TC-030)을 함께 확인한다.
"""

from django.test import SimpleTestCase, TestCase

from apps.approvals import errors as apr_errors
from apps.core import trace
from apps.document_workflow import flows, services
from apps.document_workflow.tests.base import (
    apr,
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
from apps.documents import errors as doc_errors
from apps.documents.tests.base import update_current


class WfTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.t = setup_reference_data()

    def tearDown(self):
        self.assertEqual(invariant_violations(), [])  # WF-TC-030

    def submit(self, document_id=None, actor=3, slot_list=None, expected=None):
        document_id = document_id or new_document(self.t)
        version = expected if expected is not None else version_of(document_id)
        return services.submit(actor, document_id, version, slot_list or slots())

    def _submit_new(self):
        document_id = new_document(self.t)
        return services.submit(3, document_id, version_of(document_id), slots())

    def traced(self, func):
        record, token = trace.start("TEST", "method")
        try:
            return func(), [s.step_id for s in record.steps]
        except Exception as error:  # noqa: BLE001 - 실패 trace 확인용
            return error, [s.step_id for s in record.steps]
        finally:
            trace.stop(token)


class SubmitTests(WfTestCase):
    def test_tc001_submit(self):
        document_id = new_document(self.t)
        out = services.submit(3, document_id, version_of(document_id), slots())
        self.assertEqual(out["document"]["status"], "submitted")
        self.assertEqual(out["document"]["version"], 3)  # 작성 1 → 작성완료 2 → 잠금 3
        self.assertIsNotNone(out["document"]["submitted_at"])
        req = out["request"]
        self.assertEqual(
            (req["attempt"], req["status"], req["document_version"]), (1, "in_progress", 3)
        )
        self.assertEqual(req["requested_by"], 3)
        self.assertEqual([s["state"] for s in req["slots"]], ["pending"] * 3)
        self.assertNotIn("snapshot", req)

    def test_tc002_invalid_slots_no_transaction(self):
        document_id = new_document(self.t)
        before = db_state(document_id)
        bad = [{"slot_no": 1, "approver_id": 2}, {"slot_no": 2, "approver_id": 2}]
        error, ids = self.traced(
            lambda: services.submit(3, document_id, version_of(document_id), bad)
        )
        self.assertIsInstance(error, apr_errors.InvalidSlots)
        self.assertNotIn("WF-SUB-04", ids)  # 트랜잭션을 시작하지 않음 (NFR-06)
        self.assertEqual(db_state(document_id), before)

    def test_tc003_version_conflict(self):
        document_id = new_document(self.t)  # v2 (작성완료)
        doc.reopen_document(3, document_id, 2)  # v3
        doc.complete_document(3, document_id, 3)  # v4
        before = db_state(document_id)
        with self.assertRaises(doc_errors.VersionConflict):
            services.submit(3, document_id, 2, slots())
        self.assertEqual(db_state(document_id), before)

    def test_tc004_locked_or_missing(self):
        submitted = self.submit()["document"]["document_id"]
        approved = self.approve_all(self.submit())
        deleted = new_document(self.t, completed=False)
        doc.delete_document(3, deleted)
        draft = new_document(self.t, completed=False)  # P4: 작성완료 전에는 상신 불가
        cases = [
            (submitted, doc_errors.DocumentLocked),
            (draft, doc_errors.DocumentLocked),
            (approved, doc_errors.DocumentLocked),
            (deleted, doc_errors.DocumentNotFound),
            (99999, doc_errors.DocumentNotFound),
        ]
        for document_id, error in cases:
            with self.subTest(document_id), self.assertRaises(error):
                services.submit(3, document_id, version_of(document_id), slots())

    def approve_all(self, out):
        for no, who in ((1, 3), (2, 2), (3, 1)):
            services.decide(who, slot_ids(out["request"])[no], "approved")
        return out["document"]["document_id"]

    def test_tc005_open_request_failure_rolls_back_lock(self):
        document_id = new_document(self.t)
        # 어긋난 데이터: 작성완료 문서에 진행 중 회차 (불변식 검사 대상이므로 끝에서 지운다)
        sql(
            "INSERT INTO approval_request (document_id, attempt, status, document_version,"
            " template_id, work_date, snapshot_json, requested_by, requested_at)"
            " VALUES (%s, 1, 'in_progress', 1, %s, '2026-10-09', '{}', 3, '2026-10-09')",
            [document_id, self.t["ccp"].template_id],
        )
        before = db_state(document_id)
        error, ids = self.traced(
            lambda: services.submit(3, document_id, version_of(document_id), slots())
        )
        self.assertIsInstance(error, apr_errors.OpenRequestExists)
        self.assertIn("DOC-LCK-01", ids)  # 잠금까지는 실행됐다
        self.assertEqual(db_state(document_id), before)  # 잠금도 되돌려짐
        self.assertEqual(doc.get_document(document_id)["status"], "completed")
        sql("DELETE FROM approval_request WHERE document_id=%s", [document_id])

    def test_tc006_snapshot_is_locked_document(self):
        out = self.submit()
        document_id = out["document"]["document_id"]
        stored = apr.get_request(out["request"]["request_id"])
        current = doc.get_document(document_id)
        self.assertEqual(stored["snapshot"], current)
        self.assertEqual(stored["snapshot"]["version"], out["document"]["version"])
        self.assertEqual(
            (stored["subject"], stored["work_date"], stored["template_id"]),
            (current["subject"], current["work_date"], current["template"]["template_id"]),
        )

    def test_tc007_requester_as_approver(self):
        out = self.submit(actor=3)  # 1번 칸 결재자도 3
        self.assertEqual(out["request"]["slots"][0]["approver_id"], 3)


class DecideTests(WfTestCase):
    def setUp(self):
        self.out = self._submit_new()
        self.document_id = self.out["document"]["document_id"]
        self.ids = slot_ids(self.out["request"])

    def test_tc010_middle_approval(self):
        result = services.decide(3, self.ids[1], "approved")
        self.assertEqual((result["request_status"], result["pending_count"]), ("in_progress", 2))
        self.assertIsNone(result["document"])
        current = doc.get_document(self.document_id)
        self.assertEqual((current["status"], current["version"]), ("submitted", 3))

    def test_tc011_all_approved(self):
        services.decide(3, self.ids[1], "approved")
        services.decide(2, self.ids[2], "approved", "확인")
        result = services.decide(1, self.ids[3], "approved")
        self.assertEqual(result["request_status"], "approved")
        self.assertEqual(
            (result["document"]["status"], result["document"]["version"]), ("approved", 4)
        )
        req = apr.get_request(self.out["request"]["request_id"])
        self.assertEqual(req["status"], "approved")
        self.assertIsNotNone(req["closed_at"])

    def test_tc012_partial_reject(self):
        services.decide(3, self.ids[1], "approved")
        result = services.decide(2, self.ids[2], "rejected", "온도 기록 누락")
        self.assertEqual(result["request_status"], "rejected")
        self.assertEqual(
            (result["document"]["status"], result["document"]["version"]), ("rejected", 4)
        )
        req = apr.get_request(self.out["request"]["request_id"])
        self.assertEqual([s["state"] for s in req["slots"]], ["approved", "rejected", "skipped"])
        self.assertEqual(req["status"], "rejected")

    def test_tc013_failures_change_nothing(self):
        before = db_state(self.document_id)
        cases = [
            (lambda: services.decide(2, self.ids[2], "rejected", "  "), apr_errors.CommentRequired),
            (lambda: services.decide(4, self.ids[2], "approved"), apr_errors.NotYourSlot),
            (lambda: services.decide(2, 99999, "approved"), apr_errors.ApprovalNotFound),
        ]
        for func, error in cases:
            with self.subTest(error.__name__), self.assertRaises(error):
                func()
        self.assertEqual(db_state(self.document_id), before)

    def test_tc014_double_decision(self):
        services.decide(3, self.ids[1], "approved")
        with self.assertRaises(apr_errors.AlreadyDecided):
            services.decide(3, self.ids[1], "approved")
        services.decide(2, self.ids[2], "rejected", "누락")
        before = db_state(self.document_id)
        with self.assertRaises(apr_errors.RequestClosed):
            services.decide(1, self.ids[3], "approved")  # skipped 칸
        self.assertEqual(db_state(self.document_id), before)

    def test_tc015_sync_failure_rolls_back_decision(self):
        services.decide(3, self.ids[1], "approved")
        services.decide(2, self.ids[2], "approved")
        # 어긋난 데이터: 회차는 진행 중인데 문서를 completed로 (끝에서 되돌린다)
        sql("UPDATE document SET status='completed' WHERE document_id=%s", [self.document_id])
        before = db_state(self.document_id)
        error, ids = self.traced(lambda: services.decide(1, self.ids[3], "approved"))
        self.assertIsInstance(error, doc_errors.InvalidTransition)
        self.assertIn("APR-DEC-04", ids)  # 회차 종료까지 실행됐다
        self.assertEqual(db_state(self.document_id), before)  # 칸·회차 모두 되돌려짐
        req = apr.get_request(self.out["request"]["request_id"])
        self.assertEqual((req["status"], req["slots"][2]["state"]), ("in_progress", "pending"))
        sql("UPDATE document SET status='submitted' WHERE document_id=%s", [self.document_id])


class ResubmitTests(WfTestCase):
    def reject_first(self):
        out = self._submit_new()
        services.decide(2, slot_ids(out["request"])[2], "rejected", "온도 누락")
        return out

    def test_tc016_history_preserved(self):
        first = self.reject_first()
        document_id = first["document"]["document_id"]
        old = apr.get_request(first["request"]["request_id"])
        update_current(3, document_id, {"document": {"subject": "CCP-2B/라인B"}})
        complete_again(document_id)  # P4: 반려 → 수정 → 작성완료 → 재상신
        second = services.submit(3, document_id, version_of(document_id), slots())
        self.assertEqual(
            (second["request"]["attempt"], second["document"]["status"]), (2, "submitted")
        )
        self.assertEqual(apr.get_request(first["request"]["request_id"]), old)  # 1회차 그대로
        new = apr.get_request(second["request"]["request_id"])
        self.assertEqual(new["snapshot"]["subject"], "CCP-2B/라인B")
        history = apr.list_requests(document_id)["items"]
        self.assertEqual(
            [(h["attempt"], h["status"]) for h in history], [(2, "in_progress"), (1, "rejected")]
        )

    def test_tc017_resubmit_without_change(self):
        first = self.reject_first()
        document_id = first["document"]["document_id"]
        with self.assertRaises(doc_errors.DocumentLocked):  # P4: 반려 상태에서 바로 상신 불가
            services.submit(3, document_id, version_of(document_id), slots())
        complete_again(document_id)
        second = services.submit(3, document_id, version_of(document_id), slots())
        a = apr.get_request(first["request"]["request_id"])["snapshot"]
        b = apr.get_request(second["request"]["request_id"])["snapshot"]
        self.assertEqual(a["sections"], b["sections"])
        self.assertEqual(b["version"] - a["version"], 3)  # 반려 +1, 작성완료 +1, 잠금 +1


class TraceTests(WfTestCase):
    """WF-TC-047 보강(메소드 수준): WF 단계 안에 도메인 단계가 이어서 기록된다."""

    def test_flows(self):
        document_id = new_document(self.t)
        version = version_of(document_id)
        out, ids = self.traced(lambda: services.submit(3, document_id, version, slots()))
        # API 단계(01·02)는 API 테스트에서 확인한다.
        self.assertTrue(flows.matches("WF-SUB", ["WF-SUB-01", "WF-SUB-02", *ids]), ids)
        sids = slot_ids(out["request"])
        head = ["WF-DEC-01", "WF-DEC-02"]
        _, ids = self.traced(lambda: services.decide(3, sids[1], "approved"))
        self.assertTrue(flows.matches("WF-DEC-PROGRESS", head + ids), ids)
        _, ids = self.traced(lambda: services.decide(2, sids[2], "rejected", "누락"))
        self.assertTrue(flows.matches("WF-DEC-REJECTED", head + ids), ids)

    def test_rollback_recorded(self):
        document_id = new_document(self.t)
        record, token = trace.start("TEST", "method")
        try:
            with self.assertRaises(doc_errors.VersionConflict):
                services.submit(3, document_id, 9, slots())
        finally:
            trace.stop(token)
        tx = next(s for s in record.steps if s.step_id == "WF-SUB-04")
        self.assertEqual(tx.result, "fail")
        self.assertIn("롤백", tx.detail)


class InvariantHelperTests(SimpleTestCase):
    def test_tc030_allowed_pairs(self):
        from apps.document_workflow.tests.base import ALLOWED_PAIRS

        self.assertEqual(len(ALLOWED_PAIRS), 10)  # P4: completed·작성 재개, P6: 정정 F0·F1
        self.assertNotIn(("submitted", "rejected"), ALLOWED_PAIRS)
