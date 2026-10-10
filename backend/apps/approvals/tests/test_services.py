"""APR 메소드 테스트 (수준 M). 이름의 tcNNN은 approval/s2-spec.md 6장의 APR-TC ID."""

import copy

from django.db import IntegrityError, connection, transaction
from django.test import TestCase, TransactionTestCase

from apps.approvals import errors, services
from apps.approvals.models import Approval, ApprovalRequest
from apps.approvals.tests.base import (
    SLOTS,
    ensure_staff,
    make_document,
    make_template,
    ref,
    snapshot_for,
)
from apps.core.http import ApiError


class AprTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_staff()
        cls.tpl = make_template()

    def open(self, slots=SLOTS, **kw):
        doc = kw.pop("document_id", None) or make_document(self.tpl)
        return services.open_request(
            ref(doc, self.tpl, **kw), snapshot_for(doc), 3, copy.deepcopy(slots)
        )

    def slot_id(self, result, slot_no):
        return next(s["approval_id"] for s in result["slots"] if s["slot_no"] == slot_no)

    def db_state(self, request_id):
        req = ApprovalRequest.objects.get(pk=request_id)
        slots = list(Approval.objects.filter(request_id=request_id).order_by("slot_no").values())
        return (req.status, req.closed_at, slots)


class ValidateSlotsTests(AprTestCase):
    def test_tc001_cleans_and_sorts(self):
        slots = [
            {"slot_no": 3, "approver_id": 1},
            {"slot_no": 1, "label": "  담당 ", "approver_id": 3},
            {"slot_no": 2, "label": "", "approver_id": 2},
        ]
        self.assertEqual(
            services.validate_slots(slots),
            [
                {"slot_no": 1, "approver_id": 3, "label": "담당"},
                {"slot_no": 2, "approver_id": 2, "label": None},
                {"slot_no": 3, "approver_id": 1, "label": None},
            ],
        )

    def test_tc002_invalid_slots(self):
        cases = {
            "빈 목록": [],
            "목록 아님": {"slot_no": 1},
            "11개": [{"slot_no": i, "approver_id": 1} for i in range(1, 12)],
            "번호 중복": [{"slot_no": 1, "approver_id": 1}, {"slot_no": 1, "approver_id": 2}],
            "번호 0": [{"slot_no": 0, "approver_id": 1}],
            "번호 문자": [{"slot_no": "1", "approver_id": 1}],
            "없는 staff": [{"slot_no": 1, "approver_id": 99}],
            "결재자 중복": [{"slot_no": 1, "approver_id": 2}, {"slot_no": 2, "approver_id": 2}],
            "label 21자": [{"slot_no": 1, "approver_id": 1, "label": "가" * 21}],
            "알 수 없는 키": [{"slot_no": 1, "approver_id": 1, "order": 1}],
        }
        for name, slots in cases.items():
            with self.subTest(name), self.assertRaises(errors.InvalidSlots) as ctx:
                services.validate_slots(slots)
            self.assertTrue(ctx.exception.details)


class OpenRequestTests(AprTestCase):
    def test_tc003_open(self):
        doc = make_document(self.tpl)
        snap = snapshot_for(doc)
        result = services.open_request(ref(doc, self.tpl), snap, 3, copy.deepcopy(SLOTS))
        self.assertEqual((result["attempt"], result["status"]), (1, "in_progress"))
        req = ApprovalRequest.objects.get(pk=result["request_id"])
        self.assertEqual(req.snapshot_json, snap)
        self.assertEqual(
            (req.document_version, req.subject, str(req.work_date)),
            (2, "CCP-2B/라인A", "2026-10-10"),
        )
        self.assertIsNone(req.closed_at)
        self.assertEqual(
            [(s["slot_no"], s["state"]) for s in result["slots"]],
            [(1, "pending"), (2, "pending"), (3, "pending")],
        )

    def test_tc005_open_request_exists(self):
        doc = make_document(self.tpl)
        self.open(document_id=doc)
        with self.assertRaises(errors.OpenRequestExists):
            self.open(document_id=doc)
        self.assertEqual(ApprovalRequest.objects.filter(document_id=doc).count(), 1)

    def test_tc005_db_index_blocks_second_open(self):
        doc = make_document(self.tpl)
        self.open(document_id=doc)
        with self.assertRaises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO approval_request (document_id, attempt, status, document_version,"
                " template_id, work_date, snapshot_json, requested_by, requested_at)"
                " VALUES (%s, 2, 'in_progress', 2, %s, '2026-10-10', '{}', 3, '2026-10-10')",
                [doc, self.tpl],
            )

    def test_tc006_reopen_after_rejected(self):
        doc = make_document(self.tpl)
        first = self.open(document_id=doc)
        services.decide(self.slot_id(first, 2), 2, "rejected", "온도 누락")
        before = self.db_state(first["request_id"])
        second = self.open(document_id=doc, version=4)
        self.assertEqual((second["attempt"], second["status"]), (2, "in_progress"))
        self.assertEqual(self.db_state(first["request_id"]), before)

    def test_tc007_invalid_input_writes_nothing(self):
        doc = make_document(self.tpl)
        with self.assertRaises(errors.InvalidSlots):
            services.open_request(
                ref(doc, self.tpl), snapshot_for(doc), 3, [{"slot_no": 1, "approver_id": 99}]
            )
        bad_ref = ref(doc, self.tpl)
        del bad_ref["work_date"]
        with self.assertRaises(ApiError) as ctx:
            services.open_request(bad_ref, snapshot_for(doc), 3, SLOTS)
        self.assertEqual(ctx.exception.code, "INVALID_REQUEST")
        with self.assertRaises(ApiError):
            services.open_request(ref(doc, self.tpl), "not-object", 3, SLOTS)
        with self.assertRaises(ApiError):
            services.open_request(ref(doc, self.tpl, work_date="2026/10/10"), {}, 3, SLOTS)
        self.assertFalse(ApprovalRequest.objects.exists())


class DecideTests(AprTestCase):
    def test_tc010_approve_not_final(self):
        r = self.open()
        out = services.decide(self.slot_id(r, 1), 3, "approved")
        self.assertEqual((out["request_status"], out["pending_count"]), ("in_progress", 2))
        slot = Approval.objects.get(pk=self.slot_id(r, 1))
        self.assertEqual(slot.state, "approved")
        self.assertIsNotNone(slot.decided_at)

    def test_tc011_final_approval_closes(self):
        r = self.open()
        for no, who in ((1, 3), (2, 2)):
            services.decide(self.slot_id(r, no), who, "approved", "확인")
        out = services.decide(self.slot_id(r, 3), 1, "approved")
        self.assertEqual((out["request_status"], out["pending_count"]), ("approved", 0))
        req = ApprovalRequest.objects.get(pk=r["request_id"])
        self.assertEqual(req.status, "approved")
        self.assertIsNotNone(req.closed_at)

    def test_tc012_reject_skips_rest(self):
        r = self.open()
        services.decide(self.slot_id(r, 1), 3, "approved")
        out = services.decide(self.slot_id(r, 2), 2, "rejected", "  온도 기록 누락 ")
        self.assertEqual(out["request_status"], "rejected")
        status, closed, slots = self.db_state(r["request_id"])
        self.assertEqual(status, "rejected")
        self.assertIsNotNone(closed)
        self.assertEqual([s["state"] for s in slots], ["approved", "rejected", "skipped"])
        self.assertEqual(slots[1]["comment"], "온도 기록 누락")
        self.assertIsNotNone(slots[2]["decided_at"])

    def test_tc013_reject_needs_comment(self):
        r = self.open()
        before = self.db_state(r["request_id"])
        for comment in (None, "   "):
            with self.subTest(comment), self.assertRaises(errors.CommentRequired):
                services.decide(self.slot_id(r, 2), 2, "rejected", comment)
        with self.assertRaises(errors.InvalidDecision):
            services.decide(self.slot_id(r, 2), 2, "rejected", "가" * 501)
        self.assertEqual(self.db_state(r["request_id"]), before)

    def test_tc014_invalid_result(self):
        r = self.open()
        with self.assertRaises(errors.InvalidDecision):
            services.decide(self.slot_id(r, 1), 3, "ok")

    def test_tc015_not_your_slot(self):
        r = self.open()
        before = self.db_state(r["request_id"])
        with self.assertRaises(errors.NotYourSlot):
            services.decide(self.slot_id(r, 1), 4, "approved")
        self.assertEqual(self.db_state(r["request_id"]), before)

    def test_tc016_already_decided(self):
        r = self.open()
        services.decide(self.slot_id(r, 1), 3, "approved")
        with self.assertRaises(errors.AlreadyDecided):
            services.decide(self.slot_id(r, 1), 3, "approved")

    def test_tc017_request_closed(self):
        r = self.open()
        services.decide(self.slot_id(r, 2), 2, "rejected", "누락")
        with self.assertRaises(errors.RequestClosed):
            services.decide(self.slot_id(r, 3), 1, "approved")

    def test_tc018_not_found(self):
        with self.assertRaises(errors.ApprovalNotFound):
            services.decide(99999, 1, "approved")

    def test_tc020_requester_can_approve_own_slot(self):
        r = self.open()  # 상신자 3이 1번 칸 결재자
        self.assertEqual(
            services.decide(self.slot_id(r, 1), 3, "approved")["decided"]["state"], "approved"
        )

    def test_tc023_snapshot_never_changes(self):
        doc = make_document(self.tpl)
        snap = snapshot_for(doc)
        r = services.open_request(ref(doc, self.tpl), snap, 3, copy.deepcopy(SLOTS))
        services.decide(self.slot_id(r, 1), 3, "approved")
        services.decide(self.slot_id(r, 2), 2, "rejected", "누락")
        self.assertEqual(ApprovalRequest.objects.get(pk=r["request_id"]).snapshot_json, snap)


class QueryTests(AprTestCase):
    def test_tc030_get_request(self):
        r = self.open()
        data = services.get_request(r["request_id"])
        self.assertEqual([s["slot_no"] for s in data["slots"]], [1, 2, 3])
        self.assertIn("snapshot", data)
        with self.assertRaises(errors.RequestNotFound):
            services.get_request(99999)

    def test_tc031_list_requests(self):
        doc = make_document(self.tpl)
        for attempt in range(3):
            r = self.open(document_id=doc)
            if attempt < 2:
                services.decide(self.slot_id(r, 2), 2, "rejected", "다시")
        items = services.list_requests(doc)["items"]
        self.assertEqual([i["attempt"] for i in items], [3, 2, 1])
        self.assertTrue(all("snapshot" not in i and len(i["slots"]) == 3 for i in items))
        self.assertEqual(services.list_requests(99999)["items"], [])

    def make_inbox_data(self):
        other_tpl = make_template("HYGIENE_CHECK")
        a = self.open(work_date="2026-10-01")  # staff 2: 대기
        b = self.open(work_date="2026-10-05")  # staff 2: 승인함
        services.decide(self.slot_id(b, 2), 2, "approved", "좋음")
        c = self.open(work_date="2026-10-07")  # staff 1 반려 → staff 2 skipped
        services.decide(self.slot_id(c, 3), 1, "rejected", "누락")
        d = self.open(work_date="2026-10-09")  # staff 2: 반려함
        services.decide(self.slot_id(d, 2), 2, "rejected", "재측정 필요")
        doc = make_document(other_tpl)
        e = services.open_request(
            ref(doc, other_tpl, work_date="2026-10-08"), snapshot_for(doc), 3, SLOTS
        )
        return a, b, c, d, e, other_tpl

    def test_tc032_inbox(self):
        a, b, c, d, e, other_tpl = self.make_inbox_data()
        pending = services.list_inbox(2, "pending")
        self.assertEqual(
            [i["request"]["request_id"] for i in pending["items"]],
            [a["request_id"], e["request_id"]],
        )
        self.assertEqual(
            pending["items"][0]["request"]["progress"], {"total": 3, "approved": 0, "pending": 3}
        )
        done = services.list_inbox(2, "done")
        self.assertEqual(
            [i["request"]["request_id"] for i in done["items"]], [d["request_id"], b["request_id"]]
        )
        self.assertNotIn(
            c["request_id"], [i["request"]["request_id"] for i in done["items"]]
        )  # skipped 제외
        self.assertEqual(
            services.list_inbox(2, "pending", {"template_id": str(other_tpl)})["total"], 1
        )
        self.assertEqual(
            services.list_inbox(2, "pending", {"from": "2026-10-02", "to": "2026-10-10"})["total"],
            1,
        )

    def test_tc032_paging(self):
        for _ in range(23):
            self.open()
        page2 = services.list_inbox(1, "pending", {}, 2)
        self.assertEqual((page2["total"], len(page2["items"]), page2["page"]), (23, 3, 2))

    def test_tc033_query_count(self):
        self.make_inbox_data()
        with self.assertNumQueries(3):
            services.list_inbox(2, "pending")

    def test_tc034_invalid_filter(self):
        for kwargs in (
            {"box": "all"},
            {"filters": {"from": "2026-10-09", "to": "2026-10-01"}},
            {"page": 0},
            {"filters": {"from": "20261009"}},
            {"filters": {"template_id": "x"}},
        ):
            with self.subTest(kwargs), self.assertRaises(errors.InvalidFilter):
                services.list_inbox(2, **kwargs)


class OutsideTransactionTests(TransactionTestCase):
    def test_tc004_tc019_transaction_required(self):
        ensure_staff()
        tpl = make_template()
        doc = make_document(tpl)
        with self.assertRaises(errors.TransactionRequired):
            services.open_request(ref(doc, tpl), snapshot_for(doc), 3, SLOTS)
        self.assertFalse(ApprovalRequest.objects.exists())
        with transaction.atomic():
            r = services.open_request(ref(doc, tpl), snapshot_for(doc), 3, SLOTS)
        with self.assertRaises(errors.TransactionRequired):
            services.decide(r["slots"][0]["approval_id"], 3, "approved")
        self.assertEqual(Approval.objects.filter(state="pending").count(), 3)


class WriteFlowTraceTests(AprTestCase):
    """APR-TC-045 보강: 쓰기 함수는 P2에 API가 없으므로 메소드 단위로 trace 단계를 확인한다."""

    def traced(self, func):
        from apps.core import trace

        record, token = trace.start("TEST", "method")
        try:
            result = func()
        finally:
            trace.stop(token)
        return result, [s.step_id for s in record.steps]

    def test_open_and_decide_follow_flows(self):
        from apps.approvals import flows

        r, ids = self.traced(self.open)
        self.assertTrue(flows.matches("APR-OPN", ids), ids)  # 검증은 OPN-01 안에서 실행
        _, ids = self.traced(lambda: services.validate_slots(copy.deepcopy(SLOTS)))
        self.assertTrue(flows.matches("APR-VAL", ids), ids)
        _, ids = self.traced(lambda: services.decide(self.slot_id(r, 1), 3, "approved"))
        self.assertTrue(flows.matches("APR-DEC", ids), ids)
        _, ids = self.traced(lambda: services.decide(self.slot_id(r, 2), 2, "rejected", "누락"))
        self.assertTrue(flows.matches("APR-DEC", ids), ids)

    def test_failure_branch_is_recorded(self):
        r = self.open()
        services.decide(self.slot_id(r, 1), 3, "approved")
        with self.assertRaises(errors.AlreadyDecided):
            self.traced(lambda: services.decide(self.slot_id(r, 1), 3, "approved"))
