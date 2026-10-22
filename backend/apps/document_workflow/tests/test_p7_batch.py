"""P7 S4 일괄 승인·일괄 상신·설정 조회·대상 요약 (p7-s2-spec 7.1~7.3, 7.5 일부).

이름의 tcNNN은 P7-TC ID. 수준 A = API, M = 메소드. 쓰기 테스트는 끝에 결합 상태 불변식을 확인한다.
"""

import json
import sys
import time
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from apps.core import trace
from apps.core.http import ApiError
from apps.document_workflow import flows
from apps.document_workflow import services as wf
from apps.document_workflow.tests.base import invariant_violations
from apps.document_workflow.tests.p7 import (
    ccp,
    d03,
    setup_p7,
    slot_state,
    sql,
    status_of,
    version_of,
)
from apps.documents import services as doc
from apps.documents.tests.test_api import TRACE_MIDDLEWARE


class P7Case(TestCase):
    def setUp(self):
        self.t = setup_p7()

    def tearDown(self):
        self.assertEqual(invariant_violations(), [])

    def post(self, path, body, staff=3):
        headers = {} if staff is None else {"HTTP_X_STAFF_ID": str(staff)}
        return self.client.post(
            f"/api/v1/{path}", data=json.dumps(body), content_type="application/json", **headers
        )

    def approve(self, ids, staff=1, **extra):
        return self.post("approvals/batch-decision", {"approval_ids": ids, **extra}, staff)

    def submit(self, docs, staff=3):
        items = [{"document_id": d, "expected_version": version_of(d)} for d in docs]
        return self.post("documents/batch-submit", {"items": items}, staff)

    def assertError(self, response, status, code, detail=None):
        self.assertEqual(response.status_code, status, response.content)
        body = response.json()
        self.assertEqual(body["code"], code)
        if detail:
            self.assertIn(detail, [d["code"] for d in body["details"]])
        return body

    def ok(self, response):
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()


# ---------------------------------------------------------------- 7.1 일괄 승인


class BatchApproveTests(P7Case):
    def test_tc001_last_slots(self):
        made = [d03("submitted_partial") for _ in range(3)]
        body = self.ok(self.approve([m["slots"][2] for m in made]))
        self.assertEqual((body["action"], body["total"], body["succeeded"]), ("approve", 3, 3))
        for m, line in zip(made, body["results"]):
            self.assertEqual(line["document_id"], m["document_id"])
            self.assertEqual(line["result"]["request_status"], "approved")
            self.assertEqual(line["result"]["document"]["status"], "approved")
            self.assertEqual(status_of(m["document_id"])[0], "approved")

    def test_tc002_first_slots(self):
        made = [d03("submitted") for _ in range(2)]
        body = self.ok(self.approve([m["slots"][1] for m in made], staff=3))
        for m, line in zip(made, body["results"]):
            self.assertEqual(
                line["result"],
                {"request_status": "in_progress", "pending_count": 1, "document": None},
            )
            self.assertEqual(status_of(m["document_id"])[0], "submitted")

    def test_tc003_same_comment(self):
        made = [d03("submitted_partial") for _ in range(3)]
        ids = [m["slots"][2] for m in made]
        wf.batch_approve(1, ids, "  확인  ")
        self.assertEqual({slot_state(i) for i in ids}, {("approved", "확인")})

    def test_tc004_request_closed(self):
        made = [d03("submitted") for _ in range(3)]
        wf.decide(3, made[1]["slots"][1], "rejected", "다시")  # 다른 결재자가 먼저 반려
        before = status_of(made[1]["document_id"])
        body = self.ok(self.approve([m["slots"][2] for m in made]))
        self.assertEqual(body["succeeded"], 2)
        line = body["results"][1]
        self.assertFalse(line["ok"])
        self.assertEqual(line["error"]["code"], "REQUEST_CLOSED")
        self.assertEqual(status_of(made[1]["document_id"]), before)

    def test_tc005_not_your_slot(self):
        mine, other = d03("submitted"), d03("submitted")
        body = self.ok(self.approve([mine["slots"][2], other["slots"][1]]))
        self.assertEqual([r["ok"] for r in body["results"]], [True, False])
        self.assertEqual(body["results"][1]["error"]["code"], "NOT_YOUR_SLOT")
        self.assertEqual(slot_state(other["slots"][1])[0], "pending")

    def test_tc006_already_decided(self):
        done, waiting = d03("submitted_partial"), d03("submitted")
        body = self.ok(self.approve([done["slots"][1], waiting["slots"][1]], staff=3))
        self.assertEqual(body["results"][0]["error"]["code"], "ALREADY_DECIDED")
        self.assertTrue(body["results"][1]["ok"])

    def test_tc006b_closed_before_already(self):
        """마지막 칸을 이미 승인(회차 approved) — 회차 종료가 이미 처리보다 먼저(검토 B-1)."""
        closed, waiting = d03("approved"), d03("submitted_partial")
        body = self.ok(self.approve([closed["slots"][2], waiting["slots"][2]]))
        self.assertEqual(body["results"][0]["error"]["code"], "REQUEST_CLOSED")
        self.assertTrue(body["results"][1]["ok"])

    def test_tc007_missing_slot(self):
        m = d03("submitted_partial")
        body = self.ok(self.approve([m["slots"][2], 99999]))
        self.assertEqual(body["results"][1]["document_id"], None)
        self.assertEqual(body["results"][1]["error"]["code"], "APPROVAL_NOT_FOUND")
        self.assertEqual((body["succeeded"], body["failed"]), (1, 1))

    def test_tc008_not_batchable(self):
        m, other = d03("submitted_partial"), ccp(self.t, "submitted")
        body = self.assertError(
            self.approve([m["slots"][2], other["slots"][2]]),
            400,
            "INVALID_REQUEST",
            "not_batchable",
        )
        self.assertEqual(body["details"][0]["path"], "approval_ids[1]")
        self.assertEqual(slot_state(m["slots"][2])[0], "pending")
        self.assertEqual(slot_state(other["slots"][2])[0], "pending")

    def test_tc009_010_011_format(self):
        cases = [
            ({"approval_ids": []}, "required"),
            ({"approval_ids": list(range(1, 52))}, "max"),
            ({"approval_ids": [5, 5]}, "duplicate"),
            ({"approval_ids": ["a"]}, "invalid"),
            ({"approval_ids": [0]}, "invalid"),
            ({"approval_ids": [True]}, "invalid"),
            ({"approval_ids": 5}, "required"),
            ({}, "required"),
            ({"approval_ids": [1], "result": "rejected"}, "unknown_key"),  # 일괄 반려 없음
        ]
        for body, code in cases:
            with self.subTest(body=body):
                self.assertError(
                    self.post("approvals/batch-decision", body, 1), 400, "INVALID_REQUEST", code
                )

    def test_tc012_comment_checked_before_transaction(self):
        made = [d03("submitted_partial") for _ in range(2)]
        ids = [m["slots"][2] for m in made]
        self.assertError(self.approve(ids, comment="x" * 501), 400, "INVALID_DECISION")
        self.assertError(self.approve(ids, comment=3), 400, "INVALID_DECISION")
        self.assertEqual({slot_state(i)[0] for i in ids}, {"pending"})

    def test_tc013_staff(self):
        self.assertError(self.approve([1], staff=None), 400, "STAFF_HEADER_MISSING")
        self.assertError(self.approve([1], staff=99), 403, "INVALID_STAFF")

    def test_tc014_fifty(self):
        made = [d03("submitted_partial") for _ in range(50)]
        started = time.perf_counter()
        body = self.ok(self.approve([m["slots"][2] for m in made]))
        elapsed = time.perf_counter() - started
        self.assertEqual(body["succeeded"], 50)
        sys.stderr.write(f"\n[P7 NFR-02] 일괄 승인 50건(메모리 DB): {elapsed * 1000:.0f} ms\n")
        self.assertEqual(self.approve(list(range(1, 52)), staff=1).status_code, 400)

    def test_tc015_unexpected_error_rolls_back_all(self):
        made = [d03("submitted_partial") for _ in range(3)]
        ids = [m["slots"][2] for m in made]
        original, calls = doc.mark_approved, []

        def flaky(document_id):
            calls.append(document_id)
            if len(calls) == 2:
                raise RuntimeError("예상 밖 오류(시험)")
            return original(document_id)

        with mock.patch.object(doc, "mark_approved", flaky):
            with self.assertRaises(RuntimeError):
                wf.batch_approve(1, ids)
        self.assertEqual({slot_state(i)[0] for i in ids}, {"pending"})
        self.assertEqual({status_of(m["document_id"])[0] for m in made}, {"submitted"})

    def test_tc111_server_error_rolls_back_all(self):
        made = [d03("submitted_partial") for _ in range(2)]
        ids = [m["slots"][2] for m in made]
        original, calls = doc.mark_approved, []

        def fail_500(document_id):
            calls.append(document_id)
            if len(calls) == 2:
                raise ApiError("시험", code="TRANSACTION_REQUIRED", status=500)
            return original(document_id)

        with mock.patch.object(doc, "mark_approved", fail_500):
            with self.assertRaises(ApiError):
                wf.batch_approve(1, ids)
        self.assertEqual({slot_state(i)[0] for i in ids}, {"pending"})

    def test_tc016_domain_error_rolls_back_item(self):
        made = [d03("submitted_partial") for _ in range(3)]
        bad = made[1]["document_id"]
        sql("UPDATE document SET status = 'completed' WHERE document_id = %s", [bad])  # 어긋남
        body = wf.batch_approve(1, [m["slots"][2] for m in made])
        self.assertEqual([r["ok"] for r in body["results"]], [True, False, True])
        self.assertEqual(body["results"][1]["error"]["code"], "INVALID_TRANSITION")
        self.assertEqual(slot_state(made[1]["slots"][2])[0], "pending")  # 세이브포인트 롤백
        sql("UPDATE document SET status = 'submitted' WHERE document_id = %s", [bad])

    def test_tc019_correction_request(self):
        m = d03("correction_completed")
        ids = {}
        request = wf.submit(3, m["document_id"], version_of(m["document_id"]))["request"]
        ids = {s["slot_no"]: s["approval_id"] for s in request["slots"]}
        wf.decide(3, ids[1], "approved")
        body = wf.batch_approve(1, [ids[2]])
        self.assertEqual(body["results"][0]["result"]["document"]["status"], "approved")
        open_corrections = sql(
            "SELECT COUNT(*) FROM document_correction WHERE document_id = %s AND closed_at IS NULL",
            [m["document_id"]],
        )[0][0]
        self.assertEqual(open_corrections, 0)

    @override_settings(MIDDLEWARE=TRACE_MIDDLEWARE)
    def test_tc020_trace(self):
        made = [d03("submitted_partial") for _ in range(2)] + [d03("submitted")]
        ids = [made[0]["slots"][2], made[1]["slots"][2], made[2]["slots"][1]]
        api = ["WF-BAP-01", "WF-BAP-02"]  # API 단계 — 메소드 호출은 03부터
        steps = self.trace_of(lambda: wf.batch_approve(1, ids[:2]))
        self.assertEqual(flows.matches_batch("WF-BAP", api + steps), ["approved", "approved"])
        self.assertFalse([s for s in steps if s.startswith("EFF-")])  # approved 신호: EFF 없음
        steps = self.trace_of(lambda: wf.batch_approve(3, ids[2:]))
        self.assertEqual(flows.matches_batch("WF-BAP", api + steps), ["progress"])

    def trace_of(self, func):
        record, token = trace.start("TEST", "/")
        try:
            func()
        finally:
            trace.stop(token)
        return [s.step_id for s in record.steps]

    def test_tc103_input_check_sql(self):
        made = [d03("submitted_partial") for _ in range(3)]
        ids = [m["slots"][2] for m in made]
        with mock.patch.object(wf.batch, "run_each", return_value=[]):
            with CaptureQueriesContext(connection) as ctx:
                wf.batch_approve(1, ids)
        reads = [q["sql"] for q in ctx.captured_queries if q["sql"].startswith("SELECT")]
        self.assertEqual(len(reads), 2, reads)  # A9 1 + F02 1


# ---------------------------------------------------------------- 7.2 일괄 상신


class BatchSubmitTests(P7Case):
    def test_tc030_submit(self):
        made = [d03("completed") for _ in range(2)]
        body = self.ok(self.submit([m["document_id"] for m in made]))
        self.assertEqual((body["action"], body["succeeded"]), ("submit", 2))
        for m, line in zip(made, body["results"]):
            request = line["result"]["request"]
            self.assertEqual((request["attempt"], request["status"]), (1, "in_progress"))
            self.assertEqual(request["subject"], f"LOT {m['lot_number']} · 유자 · 고흥농협")
            self.assertEqual(line["result"]["document"]["status"], "submitted")

    def test_tc031_correction_and_plain(self):
        corrected, plain = d03("correction_completed"), d03("completed")
        body = self.ok(self.submit([corrected["document_id"], plain["document_id"]]))
        self.assertEqual(body["succeeded"], 2)
        self.assertEqual(body["results"][0]["result"]["request"]["attempt"], 2)
        history = self.client.get(f"/api/v1/documents/{corrected['document_id']}/approval-requests")
        self.assertTrue(history.json()["items"][0]["is_correction"])

    def test_tc032_version_conflict(self):
        a, b = d03("completed"), d03("completed")
        items = [
            {"document_id": d, "expected_version": version_of(d)}
            for d in (a["document_id"], b["document_id"])
        ]
        doc.reopen_document(3, b["document_id"], version_of(b["document_id"]))
        doc.complete_document(3, b["document_id"], version_of(b["document_id"]))
        body = self.ok(self.post("documents/batch-submit", {"items": items}))
        self.assertEqual(body["results"][1]["error"]["code"], "VERSION_CONFLICT")
        self.assertEqual(body["succeeded"], 1)

    def test_tc033_034_locked(self):
        for state, code in (("draft", "draft"), ("submitted", "submitted")):
            with self.subTest(state=state):
                good, bad = d03("completed"), d03(state)
                body = self.ok(self.submit([good["document_id"], bad["document_id"]]))
                self.assertTrue(body["results"][0]["ok"])
                error = body["results"][1]["error"]
                self.assertEqual(
                    (error["code"], error["details"][0]["code"]), ("DOCUMENT_LOCKED", code)
                )

    def test_tc035_not_batchable(self):
        good, other = d03("completed"), ccp(self.t, "completed")
        body = self.assertError(
            self.submit([good["document_id"], other["document_id"]]),
            400,
            "INVALID_REQUEST",
            "not_batchable",
        )
        self.assertEqual(body["details"][0]["path"], "items[1]")
        self.assertEqual(status_of(good["document_id"])[0], "completed")

    def test_tc036_format(self):
        m = d03("completed")
        item = {"document_id": m["document_id"], "expected_version": version_of(m["document_id"])}
        cases = [
            ({"items": []}, "required"),
            ({"items": [item] * 51}, "max"),
            ({"items": [item, item]}, "duplicate"),
            ({"items": [{**item, "expected_version": 0}]}, "invalid"),
            ({"items": [{**item, "x": 1}]}, "unknown_key"),
            ({}, "required"),
            ({"items": [item], "comment": "x"}, "unknown_key"),
            ({"items": [item], "slots": []}, "unknown_key"),  # ROLE-TC-14: 결재선은 받지 않음
        ]
        for body, code in cases:
            with self.subTest(body=body):
                self.assertError(
                    self.post("documents/batch-submit", body), 400, "INVALID_REQUEST", code
                )
        self.assertEqual(status_of(m["document_id"])[0], "completed")

    def test_tc037_role_per_item(self):
        """ROLE-TC-15: 권한 없는 사람의 일괄 상신은 항목마다 ROLE_REQUIRED(응답 200, 변화 없음)."""
        made = [d03("completed") for _ in range(2)]
        ids = [m["document_id"] for m in made]
        body = self.ok(self.submit(ids, staff=4))  # staff 4 = D03 역할 없음
        self.assertEqual(body["succeeded"], 0)
        self.assertEqual({r["error"]["code"] for r in body["results"]}, {"ROLE_REQUIRED"})
        self.assertEqual({status_of(d)[0] for d in ids}, {"completed"})
        body = self.ok(self.submit(ids, staff=1))  # 팀장은 상신 가능
        self.assertEqual(body["succeeded"], 2)

    def test_tc038_missing_document(self):
        m = d03("completed")
        items = [
            {"document_id": m["document_id"], "expected_version": version_of(m["document_id"])},
            {"document_id": 99999, "expected_version": 1},
        ]
        body = self.ok(self.post("documents/batch-submit", {"items": items}))
        self.assertEqual(body["results"][1]["error"]["code"], "DOCUMENT_NOT_FOUND")
        self.assertEqual(body["succeeded"], 1)

    def test_tc039_fifty(self):
        made = [d03("completed") for _ in range(50)]
        ids = [m["document_id"] for m in made]
        started = time.perf_counter()
        body = self.ok(self.submit(ids))
        elapsed = time.perf_counter() - started
        self.assertEqual(body["succeeded"], 50)
        count = sql(
            "SELECT COUNT(*) FROM approval_request WHERE document_id IN (%s)"
            % ",".join(map(str, ids))
        )[0][0]
        self.assertEqual(count, 50)
        sys.stderr.write(f"\n[P7 NFR-02] 일괄 상신 50건(메모리 DB): {elapsed * 1000:.0f} ms\n")

    def test_tc041_open_request_rolls_back_lock(self):
        a, b = d03("completed"), d03("completed")
        version = version_of(b["document_id"])
        # 진행 중 회차를 SQL로 만들어 둔다(방어선)
        sql(
            "INSERT INTO approval_request (document_id, attempt, status, document_version,"
            " template_id, subject, work_date, snapshot_json, requested_by, requested_at)"
            " SELECT document_id, 9, 'in_progress', version, template_id, NULL, work_date, '{}',"
            " 3, CURRENT_TIMESTAMP FROM document WHERE document_id = %s",
            [b["document_id"]],
        )
        body = wf.batch_submit(
            3,
            [
                {"document_id": a["document_id"], "expected_version": version_of(a["document_id"])},
                {"document_id": b["document_id"], "expected_version": version},
            ],
        )
        self.assertEqual(body["results"][1]["error"]["code"], "OPEN_REQUEST_EXISTS")
        self.assertEqual(status_of(b["document_id"]), ("completed", version))  # 잠금도 되돌림
        self.assertEqual(status_of(a["document_id"])[0], "submitted")
        sql("DELETE FROM approval_request WHERE attempt = 9")

    @override_settings(MIDDLEWARE=TRACE_MIDDLEWARE)
    def test_tc042_trace(self):
        made = [d03("completed") for _ in range(2)]
        items = [
            {"document_id": m["document_id"], "expected_version": version_of(m["document_id"])}
            for m in made
        ]
        record, token = trace.start("TEST", "/")
        try:
            wf.batch_submit(3, items)
        finally:
            trace.stop(token)
        steps = [s.step_id for s in record.steps]
        # API 단계(01·02)는 API에서 — 메소드 호출은 03부터
        self.assertEqual(
            flows.matches_batch("WF-BSB", ["WF-BSB-01", "WF-BSB-02", *steps]),
            ["submitted", "submitted"],
        )

    def test_tc104_input_check_sql(self):
        made = [d03("completed") for _ in range(3)]
        items = [
            {"document_id": m["document_id"], "expected_version": version_of(m["document_id"])}
            for m in made
        ]
        with mock.patch.object(wf.batch, "run_each", return_value=[]):
            with CaptureQueriesContext(connection) as ctx:
                wf.batch_submit(3, items)
        reads = [
            q["sql"]
            for q in ctx.captured_queries
            if q["sql"].startswith("SELECT") and '"staff"' not in q["sql"]
        ]  # 역할 설정 읽기(staff)는 운영에서 서버 시작 뒤 한 번 — 테스트는 매번이라 뺀다
        # F26 3 + 성적서 유무 계산 1(D-234) + 문서마다 양식 유형 1(P14 WF-SUB-02b)
        self.assertEqual(len(reads), 7, reads)


# ---------------------------------------------------------------- 7.3 대상 요약(ISS-018)


class SubjectTests(P7Case):
    def test_tc050_single_submit_fills_subject(self):
        m = d03("completed")
        res = self.post(
            f"documents/{m['document_id']}/submit",
            {"expected_version": version_of(m["document_id"])},
        )
        self.assertEqual(res.status_code, 201, res.content)
        expected = f"LOT {m['lot_number']} · 유자 · 고흥농협"
        self.assertEqual(res.json()["request"]["subject"], expected)
        inbox = self.client.get("/api/v1/approval-inbox", HTTP_X_STAFF_ID="3").json()["items"]
        self.assertIn(expected, [i["request"]["subject"] for i in inbox])

    def test_tc051_054_direct_document(self):
        m = ccp(self.t, "completed")  # subject "CCP-2B/라인A"
        request = wf.submit(3, m["document_id"], version_of(m["document_id"]))["request"]
        self.assertEqual(request["subject"], "CCP-2B/라인A")
        n = ccp(self.t, "draft")
        doc.update_document(
            3, n["document_id"], {"expected_version": 1, "document": {"subject": None}}
        )
        doc.complete_document(3, n["document_id"], version_of(n["document_id"]))
        request = wf.submit(3, n["document_id"], version_of(n["document_id"]))["request"]
        self.assertIsNone(request["subject"])


# ---------------------------------------------------------------- 7.5 설정 조회


class ConfigTests(P7Case):
    def test_tc099_config(self):
        body = self.ok(self.client.get("/api/v1/workflow/batch-config"))
        d03_ids = [
            t[0]
            for t in sql(
                "SELECT template_id FROM document_template WHERE type_code = 'D03' ORDER BY version"
            )
        ]
        self.assertEqual(len(d03_ids), 2)  # v1(비활성)·v2
        self.assertEqual(
            body,
            {
                # P8 4.3: 기본 대상 D03·D10·D11·D12(이 시험 DB에는 P8 양식이 없어 id는 D03만)
                "batch_types": ["D03", "D10", "D11", "D12"],
                "template_ids": d03_ids,
                "max_items": 50,
                "inspector_types": ["D03", "D10", "D11", "D12"],
            },
        )

    def test_tc100_check(self):
        for value, warns in (
            ([], True),
            ([1], True),
            ("D03", True),
            (["D99"], False),
            (["D03"], False),
        ):
            with self.subTest(value=value), override_settings(HACCP_BATCH_TYPES=value):
                out = StringIO()
                with CaptureQueriesContext(connection) as ctx:
                    from apps.document_workflow.checks import check_batch_types

                    problems = check_batch_types(None)
                self.assertEqual(len(ctx.captured_queries), 0)  # DB를 읽지 않는다
                self.assertEqual(
                    [p.id for p in problems], ["document_workflow.W001"] if warns else []
                )
                del out
        with override_settings(HACCP_BATCH_TYPES=["D99"]):
            self.assertEqual(wf.batch_config()["template_ids"], [])
            m = d03("completed")
            body = self.assertError(
                self.submit([m["document_id"]]), 400, "INVALID_REQUEST", "not_batchable"
            )
            self.assertEqual(body["details"][0]["path"], "items[0]")
        with override_settings(HACCP_BATCH_TYPES=[]):
            call_command("check", stdout=StringIO(), stderr=StringIO())  # 경고는 실패가 아님
