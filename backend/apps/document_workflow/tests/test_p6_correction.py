"""P6 S4a 정정 테스트 (수준 M). 이름의 tcNNN은 document-workflow/p6-s2-spec.md 7장의 P6-TC ID.

구현 기준: p6-s4-basis.md(S4a). 실제 DOC·APR·WF 함수와 함께 실행하고(대역 없음),
쓰기 테스트는 끝에 불변식(P6-TC-090 = WF-TC-030 확장)을 확인한다.
"""

from unittest import mock

from django.db import connection
from django.test import TestCase

from apps.approvals import services as apr_services
from apps.core import trace
from apps.document_workflow import services
from apps.document_workflow.tests.base import (
    apr,
    complete_again,
    db_state,
    doc,
    invariant_violations,
    new_document,
    setup_reference_data,
    slot_ids,
    sql,
    version_of,
)
from apps.documents import errors as doc_errors
from apps.documents import flows as doc_flows
from apps.documents.tests.base import make_document, update_current

REASON = "판정 오기(부적합 → 적합)"


def corrections(document_id):
    return sql(
        "SELECT reason, start_version, prev_completed_at IS NOT NULL, prev_completed_by,"
        " closed_at IS NOT NULL, outcome FROM document_correction WHERE document_id=%s"
        " ORDER BY correction_id",
        [document_id],
    )


def doc_row(document_id):
    return sql(
        "SELECT status, version, completed_at IS NOT NULL, completed_by FROM document"
        " WHERE document_id=%s",
        [document_id],
    )[0]


class P6TestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.t = setup_reference_data()

    def tearDown(self):
        self.assertEqual(invariant_violations(), [])  # P6-TC-090

    # ---- 준비 도우미 (DOC·WF 공개 함수만)
    def submit(self, document_id):
        return services.submit(3, document_id, version_of(document_id))["request"]

    def approve(self, request):
        ids = slot_ids(request)
        for slot_no, actor in ((1, 3), (2, 5)):
            services.decide(actor, ids[slot_no], "approved")

    def reject(self, request, reason="온도 누락"):
        services.decide(3, slot_ids(request)[1], "rejected", reason)

    def approved_document(self):
        """작성(v1) → 작성완료(v2) → 상신(v3) → 승인(v4)."""
        document_id = new_document(self.t)
        self.approve(self.submit(document_id))
        return document_id

    def start(self, document_id, reason=REASON, actor=3):
        return doc.start_correction(actor, document_id, version_of(document_id), reason)

    def f1(self):
        """정정 작성완료(F1): 승인 → 정정 시작 → 작성완료."""
        document_id = self.approved_document()
        self.start(document_id)
        complete_again(document_id)
        return document_id

    def f2(self):
        document_id = self.f1()
        return document_id, self.submit(document_id)

    def traced(self, func):
        record, token = trace.start("TEST", "method")
        try:
            with connection.execute_wrapper(trace.SqlRecorder(record)):
                return func(), record.steps
        finally:
            trace.stop(token)


class StartCorrectionTests(P6TestCase):
    def test_tc001_start(self):
        document_id = self.approved_document()
        requests_before = db_state(document_id)[1]
        out = self.start(document_id)
        self.assertEqual((out["status"], out["version"]), ("correcting", 5))
        self.assertIsNone(out["completed_at"])
        self.assertEqual(doc_row(document_id), ("correcting", 5, 0, None))
        self.assertEqual(corrections(document_id), [(REASON, 5, 1, 3, 0, None)])
        self.assertEqual(db_state(document_id)[1], requests_before)  # 회차 변화 없음
        self.assertEqual(out["correction"]["reason"], REASON)
        self.assertTrue(out["correction"]["cancellable"])
        self.assertEqual(len(out["corrections"]), 1)

    def test_tc002_reason(self):
        document_id = self.approved_document()
        for reason in (None, "   ", "가" * 201):
            with self.subTest(reason=reason), self.assertRaises(doc_errors.ValidationFailed) as ctx:
                self.start(document_id, reason)
            self.assertEqual(ctx.exception.details[0]["path"], "reason")
        self.assertEqual(doc_row(document_id)[:2], ("approved", 4))
        self.assertEqual(corrections(document_id), [])
        out = self.start(document_id, "  " + "가" * 200 + " ")
        self.assertEqual(out["correction"]["reason"], "가" * 200)  # 앞뒤 공백 제거

    def test_tc003_not_approved(self):
        draft = new_document(self.t, completed=False)
        completed = new_document(self.t)
        submitted = new_document(self.t)
        self.submit(submitted)
        rejected = new_document(self.t)
        self.reject(self.submit(rejected))
        correcting = self.approved_document()
        self.start(correcting)
        for document_id in (draft, completed, submitted, rejected, correcting):
            before = db_state(document_id)
            with self.subTest(document_id=document_id):
                with self.assertRaises(doc_errors.InvalidTransition):
                    self.start(document_id)
                self.assertEqual(db_state(document_id), before)

    def test_tc004_missing_deleted_version(self):
        deleted, _ = make_document(self.t["ccp"], status="approved", deleted=True)
        for document_id in (99999, deleted.document_id):
            with self.subTest(document_id), self.assertRaises(doc_errors.DocumentNotFound):
                doc.start_correction(3, document_id, 1, REASON)
        document_id = self.approved_document()
        with self.assertRaises(doc_errors.VersionConflict):
            doc.start_correction(3, document_id, 3, REASON)
        self.assertEqual(corrections(document_id), [])

    def test_open_correction_unique_guard(self):
        """NFR-05 방어선: 어긋난 데이터(승인 문서에 열린 정정)면 INSERT가 유니크에 걸려 거부."""
        document_id = self.approved_document()
        self.start(document_id)
        sql("UPDATE document SET status='approved' WHERE document_id=%s", [document_id])
        with self.assertRaises(doc_errors.InvalidTransition):
            self.start(document_id)
        self.assertEqual(len(corrections(document_id)), 1)
        sql("UPDATE document SET status='correcting' WHERE document_id=%s", [document_id])


class CancelCorrectionTests(P6TestCase):
    def test_tc006_cancel_right_after(self):
        document_id = self.approved_document()
        completed_before = sql(
            "SELECT completed_at, completed_by FROM document WHERE document_id=%s", [document_id]
        )
        latest = apr.latest_approved([document_id])[document_id]["request_id"]
        requests_before = db_state(document_id)[1]
        self.start(document_id)
        out = doc.cancel_correction(3, document_id, 5)
        self.assertEqual((out["status"], out["version"]), ("approved", 6))
        self.assertEqual(
            sql(
                "SELECT completed_at, completed_by FROM document WHERE document_id=%s",
                [document_id],
            ),
            completed_before,
        )
        self.assertEqual(corrections(document_id), [(REASON, 5, 1, 3, 1, "cancelled")])
        self.assertIsNone(out["correction"])
        self.assertEqual(out["corrections"][0]["outcome"], "cancelled")
        self.assertEqual(db_state(document_id)[1], requests_before)
        self.assertEqual(apr.latest_approved([document_id])[document_id]["request_id"], latest)

    def test_tc007_changed_after_start(self):
        document_id = self.approved_document()
        self.start(document_id)
        update_current(3, document_id, {"document": {"subject": "정정"}})  # v6
        self.assertFalse(doc.get_document(document_id)["correction"]["cancellable"])
        before = db_state(document_id)
        with self.assertRaises(doc_errors.CorrectionHasChanges):
            doc.cancel_correction(3, document_id, 6)
        self.assertEqual(db_state(document_id), before)
        self.assertEqual(corrections(document_id)[0][4:], (0, None))

    def test_tc008_cancel_failures(self):
        approved = self.approved_document()
        f1 = self.f1()
        f2, _ = self.f2()
        for document_id in (approved, f1, f2):
            with self.subTest(document_id), self.assertRaises(doc_errors.InvalidTransition):
                doc.cancel_correction(3, document_id, version_of(document_id))
        correcting = self.approved_document()
        self.start(correcting)
        with self.assertRaises(doc_errors.VersionConflict):
            doc.cancel_correction(3, correcting, 4)
        with self.assertRaises(doc_errors.DocumentNotFound):
            doc.cancel_correction(3, 99999, 1)


class CorrectionLifecycleTests(P6TestCase):
    def test_tc010_edit_and_complete(self):
        document_id = self.approved_document()
        self.start(document_id)
        out = update_current(3, document_id, {"document": {"subject": "정정 수정"}})
        self.assertEqual((out["status"], out["version"]), ("correcting", 6))
        out = complete_again(document_id)
        self.assertEqual(out["status"], "completed")
        self.assertIsNotNone(out["completed_at"])
        self.assertEqual(out["correction"]["reason"], REASON)  # 정정 진행 유지
        self.assertFalse(out["correction"]["cancellable"])

    def test_tc011_reopen_destination(self):
        f1 = self.f1()
        out = doc.reopen_document(3, f1, version_of(f1))
        self.assertEqual(out["status"], "correcting")
        self.assertIsNone(out["completed_at"])
        normal = new_document(self.t)
        out = doc.reopen_document(3, normal, version_of(normal))
        self.assertEqual((out["status"], out["completed_at"]), ("draft", None))

    def test_tc012_submit_correction(self):
        document_id, request = self.f2()
        self.assertEqual((request["attempt"], request["status"]), (2, "in_progress"))
        snapshot = apr.get_request(request["request_id"])["snapshot"]
        self.assertEqual(snapshot["correction"]["reason"], REASON)
        self.assertTrue(request["is_correction"])
        first = apr.list_requests(document_id)["items"][-1]
        self.assertEqual((first["attempt"], first["status"]), (1, "approved"))
        self.assertFalse(first["is_correction"])

    def test_tc013_approve_correction(self):
        document_id, request = self.f2()
        self.approve(request)
        self.assertEqual(doc_row(document_id)[0], "approved")
        self.assertEqual(corrections(document_id)[0][4:], (1, "approved"))
        items = {r["attempt"]: r for r in apr.list_requests(document_id)["items"]}
        self.assertEqual((items[1]["superseded_by"], items[1]["effective"]), (2, False))
        self.assertEqual((items[2]["superseded_by"], items[2]["effective"]), (None, True))
        self.assertEqual(items[1]["superseded_at"], items[2]["closed_at"])

    def test_tc014_reject_correction(self):
        document_id, request = self.f2()
        self.reject(request)
        self.assertEqual(doc_row(document_id), ("correcting", version_of(document_id), 0, None))
        self.assertEqual(apr.get_request(request["request_id"])["status"], "rejected")
        self.assertEqual(corrections(document_id)[0][4:], (0, None))  # 정정 열림 그대로
        self.assertEqual(apr.latest_approved([document_id])[document_id]["attempt"], 1)

    def test_tc015_reject_regression(self):
        document_id = new_document(self.t)
        self.reject(self.submit(document_id))
        status, _, completed, completed_by = doc_row(document_id)
        self.assertEqual((status, completed, completed_by), ("rejected", 1, 3))

    def build_tc016(self):
        """1 승인 → 정정 A → 2 반려 → 3 승인 → 정정 B → 4 승인."""
        document_id = self.approved_document()
        self.start(document_id, "정정 A")
        complete_again(document_id)
        self.reject(self.submit(document_id))
        complete_again(document_id)
        self.approve(self.submit(document_id))
        self.start(document_id, "정정 B")
        complete_again(document_id)
        self.approve(self.submit(document_id))
        return document_id

    def test_tc016_two_corrections(self):
        document_id = self.build_tc016()
        rows = corrections(document_id)
        self.assertEqual(
            [(r[0], r[4], r[5]) for r in rows],
            [("정정 A", 1, "approved"), ("정정 B", 1, "approved")],
        )
        items = {r["attempt"]: r for r in apr.list_requests(document_id)["items"]}
        self.assertEqual(
            {a: (r["status"], r["superseded_by"], r["effective"]) for a, r in items.items()},
            {
                1: ("approved", 3, False),
                2: ("rejected", None, False),
                3: ("approved", 4, False),
                4: ("approved", None, True),
            },
        )

    def test_tc017_latest_approved_during_correction(self):
        document_id = self.approved_document()
        self.start(document_id)  # F0
        self.assertEqual(apr.latest_approved([document_id])[document_id]["attempt"], 1)
        complete_again(document_id)  # F1
        self.assertEqual(apr.latest_approved([document_id])[document_id]["attempt"], 1)
        self.submit(document_id)  # F2
        self.assertEqual(apr.latest_approved([document_id])[document_id]["attempt"], 1)


class AprCorrectionViewTests(P6TestCase):
    def test_tc020_history_and_detail(self):
        document_id = CorrectionLifecycleTests.build_tc016(self)
        items = {r["attempt"]: r for r in apr.list_requests(document_id)["items"]}
        self.assertEqual(
            {a: (r["is_correction"], r["correction_reason"]) for a, r in items.items()},
            {1: (False, None), 2: (True, "정정 A"), 3: (True, "정정 A"), 4: (True, "정정 B")},
        )
        self.assertEqual(items[1]["superseded_at"], items[3]["closed_at"])
        self.assertEqual(items[3]["superseded_at"], items[4]["closed_at"])
        for attempt, row in items.items():
            detail = apr.get_request(row["request_id"])
            keys = (
                "effective",
                "superseded_by",
                "superseded_at",
                "is_correction",
                "correction_reason",
            )
            with self.subTest(attempt=attempt):
                self.assertEqual({k: detail[k] for k in keys}, {k: row[k] for k in keys})

    def test_tc021_inbox(self):
        document_id = CorrectionLifecycleTests.build_tc016(self)
        pending_doc, _ = self.f2()  # staff 5(팀장) 대기 칸(정정 상신)
        pending = apr.list_inbox(5, "pending")["items"]
        row = next(i for i in pending if i["request"]["document_id"] == pending_doc)
        self.assertEqual(
            (row["request"]["is_correction"], row["request"]["correction_reason"]), (True, REASON)
        )
        # 처리 완료 탭을 1건씩 나눠 1회차와 그것을 대체한 회차가 다른 페이지에 있게 한다
        with mock.patch.object(apr_services, "PAGE_SIZE", 1):
            first = apr.list_inbox(5, "done", page=1)
            seen = {}
            for page in range(1, first["total"] + 1):
                for item in apr.list_inbox(5, "done", page=page)["items"]:
                    req = item["request"]
                    if req["document_id"] == document_id:
                        seen[req["attempt"]] = req["superseded"]
        # staff 5는 회차 1·3·4를 승인(2는 staff 3이 반려해 팀장 칸은 skipped)
        self.assertEqual(seen, {1: True, 3: True, 4: False})

    def test_tc022_sql_counts(self):
        document_id = CorrectionLifecycleTests.build_tc016(self)
        with self.assertNumQueries(3):  # P14: + 결재 후보 1(역할 칸)
            apr.list_requests(document_id)
        with self.assertNumQueries(3):
            apr.list_inbox(5, "done")
        requests = {r["attempt"]: r["request_id"] for r in apr.list_requests(document_id)["items"]}
        with self.assertNumQueries(4):  # 승인 회차: + 다음 승인 회차 1개, + 후보 1
            apr.get_request(requests[1])
        with self.assertNumQueries(3):  # 반려 회차: + 후보 1
            apr.get_request(requests[2])


class DocCorrectionViewTests(P6TestCase):
    def test_tc030_detail_and_list(self):
        f0 = self.approved_document()
        self.start(f0)
        f1 = self.f1()
        f2, _ = self.f2()
        plain = self.approved_document()
        detail = doc.get_document(f0)
        self.assertEqual(
            {k: detail["correction"][k] for k in ("reason", "started_by", "closed_at", "outcome")},
            {"reason": REASON, "started_by": 3, "closed_at": None, "outcome": None},
        )
        self.assertEqual(len(detail["corrections"]), 1)
        self.assertIsNone(doc.get_document(plain)["correction"])
        ids = lambda f: {i["document_id"] for i in doc.list_documents(f)["items"]}  # noqa: E731
        self.assertEqual(ids({"correcting": "true"}), {f0, f1, f2})
        self.assertEqual(ids({"status": "correcting"}), {f0})
        self.assertNotIn(f0, ids({"correcting": "false"}))
        rows = {i["document_id"]: i["correcting"] for i in doc.list_documents({})["items"]}
        self.assertEqual((rows[f1], rows[plain]), (True, False))

    def test_tc031_invalid_filter(self):
        with self.assertRaises(doc_errors.InvalidFilter):
            doc.list_documents({"correcting": "yes"})

    def test_list_query_count_unchanged(self):
        """목록 SQL 수 그대로(정정 여부는 페이지 SQL 안의 EXISTS)."""
        self.approved_document()
        with self.assertNumQueries(3):
            doc.list_documents({})

    def test_tc050_not_deletable(self):
        document_id = self.approved_document()
        self.start(document_id)
        with self.assertRaises(doc_errors.DocumentNotDeletable):
            doc.delete_document(3, document_id)

    def test_tc051_inconsistent_final_approval_rolls_back(self):
        document_id, request = self.f2()
        ids = slot_ids(request)
        services.decide(3, ids[1], "approved")
        # 어긋난 데이터: 회차는 진행 중인데 문서를 completed로(WF-TC-015와 같은 방법, 끝에서 되돌림)
        sql("UPDATE document SET status='completed' WHERE document_id=%s", [document_id])
        before = (db_state(document_id), corrections(document_id))
        with self.assertRaises(doc_errors.InvalidTransition):
            services.decide(5, ids[2], "approved")
        self.assertEqual((db_state(document_id), corrections(document_id)), before)
        self.assertEqual(corrections(document_id)[0][4:], (0, None))  # 정정 열림 그대로
        sql("UPDATE document SET status='submitted' WHERE document_id=%s", [document_id])


class CorrectionTraceTests(P6TestCase):
    def test_flows(self):
        document_id = self.approved_document()
        version = version_of(document_id)
        _, steps = self.traced(lambda: doc.start_correction(3, document_id, version, REASON))
        ids = ["DOC-COR-01", *[s.step_id for s in steps]]  # 01은 API 단계
        self.assertTrue(doc_flows.matches("DOC-COR", ids), ids)
        first = next(s for s in steps if s.step_id == "DOC-COR-03").sql
        self.assertTrue(first[0]["sql"].startswith("INSERT INTO document_correction"), first)
        _, steps = self.traced(lambda: doc.cancel_correction(3, document_id, version + 1))
        ids = ["DOC-CCN-01", *[s.step_id for s in steps]]
        self.assertTrue(doc_flows.matches("DOC-CCN", ids), ids)

    def test_tc053_first_sql_is_update(self):
        f1 = self.f1()
        _, steps = self.traced(lambda: doc.reopen_document(3, f1, version_of(f1)))
        rop = next(s for s in steps if s.step_id == "DOC-ROP-02").sql
        self.assertTrue(rop[0]["sql"].startswith('UPDATE "document"'), rop)
        self.assertEqual(len(rop), 1)  # 목적지 판단 SELECT 없음
        complete_again(f1)
        request = self.submit(f1)
        _, steps = self.traced(lambda: self.reject(request))
        rjt = next(s for s in steps if s.step_id == "DOC-RJT-01").sql
        self.assertTrue(rjt[0]["sql"].startswith('UPDATE "document"'), rjt)
        self.assertEqual(len(rjt), 1)
        self.assertEqual(doc_row(f1)[0], "correcting")

    def test_approve_closes_correction_in_same_step(self):
        document_id, request = self.f2()
        ids = slot_ids(request)
        services.decide(3, ids[1], "approved")
        _, steps = self.traced(lambda: services.decide(5, ids[2], "approved"))
        apv = next(s for s in steps if s.step_id == "DOC-APV-01")
        self.assertEqual(len(apv.sql), 2)
        self.assertIn("document_correction", apv.sql[1]["sql"])
