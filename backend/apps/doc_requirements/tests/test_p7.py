"""P7 S4 REQ-F05 입고일 묶음 조회 (p7-s2-spec 3.4, 7.5 P7-TC-090~095).

D03은 WF 테스트 준비물(실제 공개 함수)로 만든다. REQ 계층 경계(REQ-TC-030)는 REQ 소스만 본다.
"""

from unittest import mock

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.core import trace
from apps.doc_requirements import flows, sources
from apps.doc_requirements import services as req
from apps.document_workflow import services as wf
from apps.document_workflow.tests.base import invariant_violations
from apps.document_workflow.tests.p7 import CHECK, d03, fill, new_lot, setup_p7
from apps.document_workflow.tests.p7 import DAY as P7_DAY
from apps.staff import roles
from apps.staff.tests.base import RolesFileMixin, default_roles

DAY = "2026-10-20"


class IncomingBundleTests(TestCase):
    def setUp(self):
        setup_p7()

    def tearDown(self):
        self.assertEqual(invariant_violations(), [])

    def get(self, day=DAY, staff=1):
        headers = {} if staff is None else {"HTTP_X_STAFF_ID": str(staff)}
        return self.client.get(f"/api/v1/incoming-inspections?received_date={day}", **headers)

    def test_tc090_bundle(self):
        made = {
            "draft": d03("draft", day=DAY),
            "completed": d03("completed", day=DAY),
            "submitted": d03("submitted_partial", day=DAY),
            "approved": d03("approved", "FAIL", day=DAY),
        }
        no_doc, _ = new_lot(DAY)
        with CaptureQueriesContext(connection) as ctx:
            res = self.get()
        self.assertEqual(res.status_code, 200, res.content)
        # 사용자 확인(API) 제외. D-234: + 성적서 유무 계산 1(F26)
        self.assertLessEqual(len(ctx.captured_queries) - 1, 9)
        body = res.json()
        lots = body["lots"]
        self.assertEqual(
            [lot["lot_number"] for lot in lots], sorted(lot["lot_number"] for lot in lots)
        )
        self.assertEqual(len(lots), 5)
        by_lot = {lot["lot_id"]: lot for lot in lots}
        self.assertIsNone(by_lot[no_doc]["document"])
        first = by_lot[made["draft"]["lot_id"]]
        self.assertEqual(
            {k: first[k] for k in ("item_name", "supplier_name", "quantity")},
            {"item_name": "유자", "supplier_name": "고흥농협", "quantity": "500kg"},
        )
        sub = by_lot[made["submitted"]["lot_id"]]["document"]
        self.assertEqual(
            sub["my_slots"],
            [{"approval_id": made["submitted"]["slots"][2], "slot_no": 2, "label": "HACCP팀장"}],
        )
        self.assertEqual(
            {k: sub["progress"][k] for k in ("attempt", "status", "total", "approved", "pending")},
            {"attempt": 1, "status": "in_progress", "total": 2, "approved": 1, "pending": 1},
        )
        done = by_lot[made["approved"]["lot_id"]]["document"]
        self.assertEqual(
            (done["approved_verdict"], done["verdict"], done["nonconforming"]),
            ("FAIL", "FAIL", True),
        )
        self.assertEqual(done["approved"]["attempt"], 1)
        draft = by_lot[made["draft"]["lot_id"]]["document"]
        self.assertEqual(
            (draft["progress"], draft["my_slots"], draft["approved"]), (None, [], None)
        )
        # ROLE-TC-33: 묶음 문서별 상신 가능 여부(팀장 staff 1 기준)
        self.assertEqual((draft["can_submit"], draft["submit_block"]), (False, "status"))
        completed = by_lot[made["completed"]["lot_id"]]["document"]
        self.assertEqual((completed["can_submit"], completed["submit_block"]), (True, None))
        self.assertEqual(draft["inspector_id"], 4)
        self.assertEqual(
            body["summary"],
            {
                "documents": 4,
                "status_counts": {"draft": 1, "completed": 1, "submitted": 1, "approved": 1},
                "correcting_count": 0,
                "my_pending": 1,
            },
        )
        # P14: 묶음 결재선 요약(일괄 상신 모달) — 예전 default_slots(최근 결재선) 대신
        self.assertEqual(
            [(s["role"], s["candidate_ids"]) for s in body["approval_line"]["slots"]],
            [("owner", [2, 3]), ("leader", [1, 5])],
        )

    def test_tc091_empty_day(self):
        body = self.get("2026-01-02").json()
        self.assertEqual(
            body,
            {
                "received_date": "2026-01-02",
                "lots": [],
                "summary": {
                    "documents": 0,
                    "status_counts": {},
                    "correcting_count": 0,
                    "my_pending": 0,
                },
                "approval_line": roles.approval_line("D03"),
                "permissions": {"assign_inspector": True},  # P14 r13: 직원 1 = 팀장(R08)
            },
        )

    def test_tc092_093_input(self):
        for day in ("2026-13-01", "2026-1-01", "", "20261020"):
            with self.subTest(day=day):
                res = self.get(day)
                self.assertEqual((res.status_code, res.json()["code"]), (400, "VALIDATION_ERROR"))
        res = self.client.get("/api/v1/incoming-inspections")
        self.assertEqual(res.status_code, 400)
        res = self.get(staff=None)  # P14 r14(D-202 Q7 b): 헤더 선택 — 사용자 없음으로 200
        self.assertEqual(res.status_code, 200, res.content)

    def test_tc094_my_slot_done(self):
        m = d03("submitted_partial", day=DAY)
        lot = req.incoming_bundle(3, DAY)["lots"][0]
        self.assertEqual(lot["document"]["my_slots"], [])  # staff 3 칸은 이미 승인
        self.assertEqual(
            (lot["document"]["progress"]["approved"], lot["document"]["progress"]["total"]), (1, 2)
        )
        del m

    def test_tc095_correcting(self):
        m = d03("correcting", day=DAY)
        fill(m["document_id"], "FAIL", actor=3)
        document = req.incoming_bundle(1, DAY)["lots"][0]["document"]
        self.assertEqual((document["approved_verdict"], document["verdict"]), ("PASS", "FAIL"))
        self.assertTrue(document["correcting"])
        self.assertEqual(req.incoming_bundle(1, DAY)["summary"]["correcting_count"], 1)

    def test_inspection_values_in_bundle(self):
        """D-232: 묶음 문서 줄에 검사 항목 값(작성 전은 성적서 유무 계산 값만 — D-234)."""
        empty = d03("empty", day=DAY)  # 검사·점검자 없음(작성중)
        filled = d03("empty", day=DAY)
        fill(filled["document_id"], "FAIL", actor=3)
        docs = {
            x["document"]["document_id"]: x["document"]
            for x in req.incoming_bundle(1, DAY)["lots"]
            if x["document"]
        }
        # D-234: 성적서 유무만 계산 값(저장 값 없음, D01 파일 없음 → 무)
        self.assertEqual(docs[empty["document_id"]]["inspection"], {"has_coa": "무"})
        self.assertEqual(docs[empty["document_id"]]["inspection_derived"], ["has_coa"])
        got = docs[filled["document_id"]]["inspection"]
        self.assertEqual({k: got.get(k) for k in CHECK["FAIL"]}, CHECK["FAIL"])

    def test_source_missing_and_trace(self):
        d03("draft", day=DAY)
        record, token = trace.start("TEST", "/")
        try:
            req.incoming_bundle(1, DAY)
        finally:
            trace.stop(token)
        steps = [s.step_id for s in record.steps]
        self.assertTrue(flows.matches("REQ-BDL", ["REQ-BDL-01", *steps]), steps)
        with mock.patch.object(sources, "LOT_VIEW", "v_doc_incoming_lot_missing"):  # 뷰 없음
            res = self.get()
        self.assertEqual((res.status_code, res.json()["code"]), (503, "REQ_SOURCE_MISSING"))


class WriterBundleTests(RolesFileMixin, TestCase):
    """ROLE-TC-41(r11, D-198): D03 작성 권한자 — 묶음 can_submit, 일괄 상신 성공(후보 아님)."""

    def setUp(self):
        data = default_roles()
        data["forms"]["D03"]["writers"] = ["DEV-004"]
        self.use_roles(data)
        setup_p7()

    def tearDown(self):
        self.assertEqual(invariant_violations(), [])

    def test_writer_batch_submit(self):
        made = [d03("completed") for _ in range(2)]
        ids = [m["document_id"] for m in made]
        lots = req.incoming_bundle(4, P7_DAY)["lots"]
        docs = [
            x["document"] for x in lots if x["document"] and x["document"]["document_id"] in ids
        ]
        self.assertEqual({(d["can_submit"], d["submit_block"]) for d in docs}, {(True, None)})
        items = [{"document_id": d["document_id"], "expected_version": d["version"]} for d in docs]
        body = wf.batch_submit(4, items)
        self.assertEqual(body["succeeded"], 2, body)
        request_id = body["results"][0]["result"]["request"]["request_id"]
        slots = self.client.get(f"/api/v1/approval-requests/{request_id}").json()["slots"]
        self.assertEqual([s["candidate_ids"] for s in slots], [[2, 3], [1, 5]])  # 4는 후보 아님
