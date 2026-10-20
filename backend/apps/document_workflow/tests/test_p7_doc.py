"""P7 S4 DOC·APR 변경 (p7-s2-spec 7.4·7.5): 점검자 일괄 지정(F25), 문서 요약(F26), 목록 묶음 줄
(F04), 상세 대상 요약(F05), LOT 여러 개로 문서 찾기(N4), APR A9·A10·A11.

정정·반려 상태가 필요해 WF로 준비한다(DOC·APR 테스트 폴더는 WF를 import하지 않는다 — WF-TC-050).
"""

import json

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.approvals import errors as apr_errors
from apps.approvals import services as apr
from apps.core import trace
from apps.document_workflow import services as wf
from apps.document_workflow.tests.base import invariant_violations
from apps.document_workflow.tests.p7 import (
    DAY,
    ccp,
    d03,
    setup_p7,
    sql,
    status_of,
    version_of,
)
from apps.documents import errors
from apps.documents import flows as doc_flows
from apps.documents import services as doc
from apps.documents.tests.p4 import goc


class P7DocCase(TestCase):
    def setUp(self):
        self.t = setup_p7()

    def tearDown(self):
        self.assertEqual(invariant_violations(), [])

    def post(self, path, body, staff=3):
        headers = {} if staff is None else {"HTTP_X_STAFF_ID": str(staff)}
        return self.client.post(
            f"/api/v1/{path}", data=json.dumps(body), content_type="application/json", **headers
        )

    def assertError(self, response, status, code, detail=None):
        self.assertEqual(response.status_code, status, response.content)
        body = response.json()
        self.assertEqual(body["code"], code)
        if detail:
            self.assertIn(detail, [d["code"] for d in body["details"]])
        return body

    def info(self, document_id):
        return next(
            s["values"]
            for s in doc.get_document(document_id)["sections"]
            if s["section_def"] == "info"
        )

    def items(self, *made):
        return [
            {"document_id": m["document_id"], "expected_version": version_of(m["document_id"])}
            for m in made
        ]

    def inspector(self, items, inspector_id=4, staff=3):
        return self.post(
            "documents/batch-inspector", {"items": items, "inspector_id": inspector_id}, staff
        )


# ---------------------------------------------------------------- 7.4 점검자 일괄 지정


class BatchInspectorTests(P7DocCase):
    def test_tc060_set(self):
        made = [d03("empty") for _ in range(2)]
        before = [self.info(m["document_id"]) for m in made]
        versions = [version_of(m["document_id"]) for m in made]
        res = self.inspector(self.items(*made))
        self.assertEqual(res.status_code, 200, res.content)
        body = res.json()
        self.assertEqual((body["action"], body["succeeded"]), ("inspector", 2))
        for m, line, old, v in zip(made, body["results"], before, versions):
            self.assertEqual(line["result"], {"changed": True, "version": v + 1})
            self.assertEqual(version_of(m["document_id"]), v + 1)
            self.assertEqual(self.info(m["document_id"]), {**old, "inspector": 4})
            stored = sql(
                "SELECT json_type(values_json, '$.inspector'), recorded_by FROM doc_section"
                " WHERE document_id = %s AND section_def = 'info'",
                [m["document_id"]],
            )[0]
            self.assertEqual(stored, ("integer", 3))  # 정수로 저장(P7 S3 J6), 기록자

    def test_tc061_same_value(self):
        same, empty = d03("draft"), d03("empty")  # draft는 점검자 4
        v = version_of(same["document_id"])
        body = self.inspector(self.items(same, empty)).json()
        self.assertEqual(body["results"][0]["result"], {"changed": False, "version": v})
        self.assertTrue(body["results"][1]["result"]["changed"])
        self.assertEqual(version_of(same["document_id"]), v)

    def test_tc062_locked(self):
        made = [d03("empty"), d03("empty"), d03("completed")]
        body = self.inspector(self.items(*made), inspector_id=2).json()
        self.assertEqual([r["ok"] for r in body["results"]], [True, True, False])
        error = body["results"][2]["error"]
        self.assertEqual(
            (error["code"], error["details"][0]["code"]), ("DOCUMENT_LOCKED", "completed")
        )

    def test_tc063_rejected_and_correcting(self):
        made = [d03("rejected"), d03("correcting")]
        self.assertEqual([status_of(m["document_id"])[0] for m in made], ["rejected", "correcting"])
        body = self.inspector(self.items(*made), inspector_id=2).json()
        self.assertEqual(body["succeeded"], 2)
        self.assertEqual({self.info(m["document_id"])["inspector"] for m in made}, {2})

    def test_tc064_version_conflict(self):
        m = d03("empty")
        items = [
            {"document_id": m["document_id"], "expected_version": version_of(m["document_id"]) + 5}
        ]
        error = self.inspector(items).json()["results"][0]["error"]
        self.assertEqual(error["code"], "VERSION_CONFLICT")

    def test_tc065_not_batchable(self):
        m, other = d03("empty"), ccp(self.t, "draft")
        body = self.assertError(
            self.inspector(self.items(m, other)), 400, "INVALID_REQUEST", "not_batchable"
        )
        self.assertEqual(body["details"][0]["path"], "items[1]")
        self.assertIsNone(self.info(m["document_id"]).get("inspector"))

    def test_tc066_unknown_staff(self):
        m = d03("empty")
        self.assertError(
            self.inspector(self.items(m), inspector_id=999),
            400,
            "VALIDATION_ERROR",
            "unknown_staff",
        )

    def test_tc067_format(self):
        m = d03("empty")
        item = self.items(m)[0]
        for body, code in (
            ({"items": [], "inspector_id": 4}, "required"),
            ({"items": [item] * 51, "inspector_id": 4}, "max"),
            ({"items": [item]}, "required"),
            ({"items": [item], "inspector_id": "4"}, "invalid"),
            ({"items": [item], "inspector_id": 4, "x": 1}, "unknown_key"),
        ):
            with self.subTest(body=body):
                self.assertError(
                    self.post("documents/batch-inspector", body), 400, "INVALID_REQUEST", code
                )
        self.assertError(self.inspector([item], staff=None), 400, "STAFF_HEADER_MISSING")

    def test_tc068_info_row_missing(self):
        m = d03("empty")
        v = version_of(m["document_id"])
        sql(
            "DELETE FROM doc_section WHERE document_id = %s AND section_def = 'info'",
            [m["document_id"]],
        )
        body = doc.batch_set_inspector(3, self.items(m), 4)
        self.assertEqual(body["results"][0]["error"]["code"], "SECTION_ROW_NOT_FOUND")
        self.assertEqual(version_of(m["document_id"]), v)

    def test_tc105_input_check_sql(self):
        made = [d03("empty") for _ in range(3)]
        items = self.items(*made)
        from unittest import mock

        with mock.patch.object(doc.batch, "run_each", return_value=[]):
            with CaptureQueriesContext(connection) as ctx:
                doc.batch_set_inspector(3, items, 4)
        reads = [q["sql"] for q in ctx.captured_queries if q["sql"].startswith("SELECT")]
        self.assertEqual(len(reads), 2, reads)  # staff 1 + 유형 1

    def test_tc106_trace(self):
        changed, same = d03("empty"), d03("draft")
        items = self.items(changed, same)
        record, token = trace.start("TEST", "/")
        try:
            doc.batch_set_inspector(3, items, 4)
        finally:
            trace.stop(token)
        steps = [s.step_id for s in record.steps]
        self.assertEqual(
            steps,
            ["DOC-BIN-02", "DOC-BIN-03"]
            + ["DOC-BIN-04", "DOC-BIN-05", "DOC-BIN-06"]
            + ["DOC-BIN-04", "DOC-BIN-05", "DOC-BIN-05a", "DOC-BIN-07"],
        )
        same_step = [s for s in record.steps if s.step_id == "DOC-BIN-05a"][0]
        self.assertEqual(same_step.result, "pass")  # 같은 값 = 성공
        self.assertTrue(doc_flows.matches("DOC-BIN", ["DOC-BIN-01", *steps[:5], "DOC-BIN-07"]))


# ---------------------------------------------------------------- 7.5 조회


class BriefTests(P7DocCase):
    def test_tc070_brief(self):
        good, bad, other = d03("completed"), d03("completed", "FAIL"), ccp(self.t, "draft")
        gone = ccp(self.t, "draft")
        doc.delete_document(3, gone["document_id"])
        ids = [good["document_id"], bad["document_id"], other["document_id"], gone["document_id"]]
        with CaptureQueriesContext(connection) as ctx:
            res = self.client.get(f"/api/v1/documents/brief?ids={','.join(map(str, ids))}")
        self.assertLessEqual(len(ctx.captured_queries), 3)
        body = res.json()
        self.assertEqual(body["missing"], [gone["document_id"]])
        items = {i["document_id"]: i for i in body["items"]}
        self.assertEqual(
            items[good["document_id"]],
            {
                "document_id": good["document_id"],
                "type_code": "D03",
                "status": "completed",
                "version": version_of(good["document_id"]),
                "correcting": False,
                "target_summary": f"LOT {good['lot_number']} · 유자 · 고흥농협",
                "inspector_id": 4,
                "verdict": "PASS",
                "nonconforming": False,
                "check_counts": None,  # P8 F26: 점검표 양식만
            },
        )
        self.assertEqual(
            (items[bad["document_id"]]["verdict"], items[bad["document_id"]]["nonconforming"]),
            ("FAIL", True),
        )
        self.assertIsNone(items[other["document_id"]]["verdict"])
        self.assertEqual(items[other["document_id"]]["target_summary"], "CCP-2B/라인A")
        self.assertEqual([i["document_id"] for i in body["items"]], ids[:3])  # 입력 순서

    def test_tc071_invalid(self):
        for query in ("", "ids=", "ids=a,b", "ids=1,,2", "ids=0", "ids=" + ",".join(["1"] * 51)):
            with self.subTest(query=query):
                self.assertError(
                    self.client.get(f"/api/v1/documents/brief?{query}"), 400, "INVALID_FILTER"
                )
        self.assertEqual(doc.brief_documents([]), {"items": [], "missing": []})


class ListBundleTests(P7DocCase):
    def list(self, query=""):
        res = self.client.get(f"/api/v1/documents?{query}")
        self.assertEqual(res.status_code, 200, res.content)
        return res.json()

    def test_tc080_bundle_first(self):
        made = [d03("draft"), d03("completed"), d03("submitted")]
        other = ccp(self.t, "draft")
        sql(
            "UPDATE document SET work_date = %s WHERE document_id = %s", [DAY, other["document_id"]]
        )
        with CaptureQueriesContext(connection) as ctx:
            body = self.list()
        self.assertLessEqual(len(ctx.captured_queries), 6)
        self.assertEqual(body["total"], 2)
        bundle, row = body["items"]
        self.assertEqual(
            {
                k: bundle[k]
                for k in ("kind", "type_code", "work_date", "count", "total", "requirement")
            },
            {
                "kind": "bundle",
                "type_code": "D03",
                "work_date": DAY,
                "count": 3,
                "total": 3,
                "requirement": "lot",
            },
        )
        self.assertEqual(bundle["status_counts"], {"draft": 1, "completed": 1, "submitted": 1})
        self.assertEqual(bundle["correcting_count"], 0)
        self.assertEqual(bundle["template_name"], "원료/부자재 육안검사일지")
        self.assertEqual((row["kind"], row["document_id"]), ("document", other["document_id"]))
        # 문서 줄은 지금 목록과 같은 값(페이지 쿼리에서 바로 — 상세와 비교)
        detail = doc.get_document(other["document_id"])
        for key in ("template", "subject", "work_date", "status", "created_by", "assignee_id",
                    "due_at", "created_at", "updated_at", "submitted_at", "version", "record_key",
                    "completed_at", "completed_by"):  # fmt: skip
            self.assertEqual(row[key], detail[key], key)
        self.assertEqual((row["correcting"], row["requirement"]), (False, None))
        self.assertEqual(row["target_summary"], "CCP-2B/라인A")
        del made

    def test_tc081_two_days(self):
        for day in ("2026-10-12", "2026-10-13"):
            d03("draft", day=day)
            d03("draft", day=day)
            c = ccp(self.t, "draft")
            sql(
                "UPDATE document SET work_date = %s WHERE document_id = %s", [day, c["document_id"]]
            )
        kinds = [(i["kind"], i["work_date"]) for i in self.list()["items"]]
        self.assertEqual(
            kinds,
            [
                ("bundle", "2026-10-13"),
                ("document", "2026-10-13"),
                ("bundle", "2026-10-12"),
                ("document", "2026-10-12"),
            ],
        )

    def test_tc082_083_status_filter(self):
        d03("draft"), d03("completed"), d03("submitted")
        c = ccp(self.t, "completed")
        sql("UPDATE document SET work_date = %s WHERE document_id = %s", [DAY, c["document_id"]])
        body = self.list("status=completed")
        bundle = body["items"][0]
        self.assertEqual((bundle["count"], bundle["total"]), (1, 3))
        self.assertEqual(bundle["status_counts"], {"completed": 1})
        self.assertEqual([i["kind"] for i in body["items"]], ["bundle", "document"])
        self.assertEqual(self.list("status=approved")["items"], [])  # 083: 그날 묶음 줄 없음

    def test_tc084_target(self):
        made = [d03("draft"), d03("draft"), d03("draft")]
        body = self.list(f"target={made[1]['lot_number']}")
        self.assertEqual(body["total"], 1)
        self.assertEqual((body["items"][0]["count"], body["items"][0]["total"]), (1, 3))
        self.assertEqual(self.list("target=50%25")["total"], 0)  # LIKE 특수 문자는 문자 그대로

    def test_tc085_correcting(self):
        d03("correcting"), d03("draft")
        bundle = self.list()["items"][0]
        self.assertEqual(bundle["correcting_count"], 1)
        self.assertEqual(bundle["status_counts"], {"correcting": 1, "draft": 1})
        filtered = self.list("correcting=true")["items"][0]
        self.assertEqual(
            (filtered["count"], filtered["total"], filtered["correcting_count"]), (1, 2, 1)
        )

    def test_tc086_pages(self):
        for n in range(21):
            d03("empty", day=f"2026-09-{n + 1:02d}")
        body = self.list("page=2")
        self.assertEqual((body["total"], len(body["items"])), (21, 1))
        self.assertEqual(body["items"][0]["work_date"], "2026-09-01")

    def test_lst_trace(self):
        d03("draft")
        c = ccp(self.t, "draft")
        sql("UPDATE document SET work_date = %s WHERE document_id = %s", [DAY, c["document_id"]])
        record, token = trace.start("TEST", "/")
        try:
            doc.list_documents({"status": "draft"})
        finally:
            trace.stop(token)
        steps = [s.step_id for s in record.steps]
        self.assertTrue(doc_flows.matches("DOC-LST", steps), steps)


class DetailAndLotsTests(P7DocCase):
    def test_tc052_053_target_summary(self):
        with_supplier = d03("empty")
        self.assertEqual(
            doc.get_document(with_supplier["document_id"])["target_summary"],
            f"LOT {with_supplier['lot_number']} · 유자 · 고흥농협",
        )
        # 053: info에 매입처 없음
        row = sql(
            "SELECT section_id FROM doc_section WHERE document_id = %s AND section_def = 'info'",
            [with_supplier["document_id"]],
        )[0][0]
        sql(
            "UPDATE doc_section SET values_json = json_remove(values_json, '$.supplier_name')"
            " WHERE section_id = %s",
            [row],
        )
        self.assertEqual(
            doc.get_document(with_supplier["document_id"])["target_summary"],
            f"LOT {with_supplier['lot_number']} · 유자",
        )
        # 052: 배치 문서
        from apps.documents.tests.p4 import new_ccp, stub

        stub("items", id=2, name="유자차")
        stub("production_batches", id=12, batch_number="PB-1011-01", process_type="MANUFACTURE",
             item_id=2, status="IN_PROGRESS")  # fmt: skip
        batch_doc = new_ccp("CCP-3P", "3P")["document"]["document_id"]
        self.assertEqual(doc.get_document(batch_doc)["target_summary"], "배치 PB-1011-01 · 3P")

    def test_tc107_deleted(self):
        c = ccp(self.t, "draft")
        doc.delete_document(3, c["document_id"])
        with self.assertRaises(errors.DocumentNotFound):
            doc.get_document(c["document_id"])

    def test_tc098_108_find_by_lots(self):
        a, b = d03("draft"), d03("draft")
        for lot in (a["lot_id"], b["lot_id"]):
            goc(
                "D01",
                f"D01|lot:{lot}",
                [{"lot_id": lot, "label": "x"}],
                {"info": {"item_name": "유자"}},
            )
        found = doc.find_documents_by_lots([a["lot_id"], b["lot_id"], 99999], ["D03"])
        self.assertEqual(
            found,
            [
                {"lot_id": a["lot_id"], "document_id": a["document_id"], "type_code": "D03"},
                {"lot_id": b["lot_id"], "document_id": b["document_id"], "type_code": "D03"},
            ],
        )
        with CaptureQueriesContext(connection) as ctx:
            self.assertEqual(doc.find_documents_by_lots([], ["D03"]), [])
        self.assertEqual(len(ctx.captured_queries), 0)


# ---------------------------------------------------------------- APR A9·A10·A11


class AprP7Tests(P7DocCase):
    def test_tc096_slot_refs(self):
        made = [d03("submitted") for _ in range(2)]
        ids = [made[0]["slots"][1], made[0]["slots"][2], made[1]["slots"][1]]
        with CaptureQueriesContext(connection) as ctx:
            refs = apr.slot_refs([*ids, 99999])
        self.assertEqual(len(ctx.captured_queries), 1)
        self.assertEqual(set(refs), set(ids))
        self.assertEqual(refs[ids[2]]["document_id"], made[1]["document_id"])
        d03_v2 = sql(
            "SELECT template_id FROM document_template WHERE type_code='D03' AND version=2"
        )[0][0]
        self.assertEqual(refs[ids[0]]["template_id"], d03_v2)

    def test_tc097_094_document_progress(self):
        partial = d03("submitted_partial")  # 1/2, 내(staff 1 = 팀장) 칸 대기
        two = d03("rejected")  # 1회차 반려 → 작성완료 → 2회차
        doc.complete_document(3, two["document_id"], version_of(two["document_id"]))
        wf.submit(3, two["document_id"], version_of(two["document_id"]))
        nothing = d03("completed")
        ids = [partial["document_id"], two["document_id"], nothing["document_id"]]
        with CaptureQueriesContext(connection) as ctx:
            out = apr.document_progress(ids, 1)
        self.assertEqual(len(ctx.captured_queries), 1)  # P14: 최근 결재선(02) 없앰
        docs = out["documents"]
        self.assertNotIn(nothing["document_id"], docs)
        self.assertEqual(
            docs[partial["document_id"]],
            {
                "request_id": docs[partial["document_id"]]["request_id"],
                "attempt": 1,
                "status": "in_progress",
                "total": 2,
                "approved": 1,
                "pending": 1,
                "my_slots": [
                    {"approval_id": partial["slots"][2], "slot_no": 2, "label": "HACCP팀장"}
                ],
            },
        )
        self.assertEqual(docs[two["document_id"]]["attempt"], 2)
        self.assertNotIn("latest_slots", out)  # P14: 일괄 상신 결재선 기본값 없앰(D-109)
        # 094: 내 칸은 이미 승인(다른 칸 대기) → my_slots 없음
        self.assertEqual(
            apr.document_progress([partial["document_id"]], 3)["documents"][partial["document_id"]][
                "my_slots"
            ],
            [],
        )

    def test_tc109_empty(self):
        with CaptureQueriesContext(connection) as ctx:
            self.assertEqual(apr.slot_refs([]), {})
            self.assertEqual(apr.document_progress([], 1), {"documents": {}})
        self.assertEqual(len(ctx.captured_queries), 0)

    def test_tc110_check_decision_input(self):
        for comment in ("x" * 501, 3):
            with self.subTest(comment=comment), self.assertRaises(apr_errors.InvalidDecision):
                apr.check_decision_input("approved", comment)
        self.assertEqual(apr.check_decision_input("approved", "  ok "), "ok")
        self.assertIsNone(apr.check_decision_input("approved", "  "))
        with self.assertRaises(apr_errors.CommentRequired):
            apr.check_decision_input("rejected", None)
