"""P12 출력 S4 — D03 입고일 묶음(receiving) (p12-d03-policy.md DP-10, p12-s2-spec 8장 TC 중 D03)."""

import datetime
from unittest import mock

from django.conf import settings
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.document_workflow import flows, printing
from apps.document_workflow.tests.p7 import d03, fill, setup_p7, version_of
from apps.documents import services as doc

DAY = "2026-10-13"


class D03PrintTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        setup_p7()

    def get(self, query):
        return self.client.get("/api/v1/print/sheet", query)

    def sheet(self, day=DAY):
        return printing.print_by_query({"kind": "receiving", "type": "D03", "date": day})


class ReceivingSheetTests(D03PrintTestCase):
    def test_tc001_d03_is_receiving(self):
        made = d03("completed", day="2026-10-14")
        self.assertEqual(printing.sheet_for_document(made["document_id"])["kind"], "receiving")

    def test_tc007_lines_by_lot_number(self):
        approved = d03("approved", supplier="A상사")
        completed = d03("completed", supplier="B물산")
        draft = d03("draft", supplier="C식품")
        data = self.sheet()
        self.assertEqual(
            (data["kind"], data["type_code"], data["key"]),
            ("receiving", "D03", {"type": "D03", "date": DAY}),
        )
        self.assertEqual(data["title"], "원료/부자재 육안검사일지")
        self.assertEqual([b["label"] for b in data["boxes"]], ["담당자", "팀장"])  # 종이 이름(U2)
        self.assertEqual(data["box_group"], "기록확인")
        self.assertEqual(
            [row[0] for row in data["guide"][0]["rows"]],
            ["성상", "외포장상태", "내포장상태", "표시사항", "파렛트", "시험성적서"],
        )  # 종이 문구(U4)
        self.assertNotIn("없어야 없어야", str(data["guide"]))
        self.assertEqual(data["printable_count"], 2)
        lines = data["lines"]
        self.assertEqual(
            [line["document_id"] for line in lines],
            [approved["document_id"], completed["document_id"], draft["document_id"]],
        )
        self.assertEqual(
            [line["lot"]["lot_number"] for line in lines],
            sorted(line["lot"]["lot_number"] for line in lines),
        )
        first, second, third = lines
        self.assertEqual((first["state"], first["printable"]), ("ok", True))
        self.assertEqual(first["values"]["verdict"], "PASS")
        self.assertEqual(first["lot"]["supplier_name"], "A상사")
        self.assertEqual([b["staff_id"] for b in first["approval"]], [3, 1])
        self.assertTrue(all(b["date"] for b in first["approval"]))
        self.assertEqual([b["staff_id"] for b in second["approval"]], [None, None])  # 작성완료(B6)
        self.assertEqual(
            (third["state"], third["printable"], third["values"]), ("draft", False, None)
        )
        self.assertEqual(
            {k: third["lot"][k] for k in ("supplier_name", "material_kind", "quantity")},
            {"supplier_name": "C식품", "material_kind": "원료", "quantity": "500kg"},
        )
        self.assertEqual([b["staff_id"] for b in third["approval"]], [None, None])
        self.assertEqual(data["deviations"], [])
        self.assertEqual(set(data["people"]), {"1", "3"})  # 점검자(staff 4)는 출력 안 함(DP-10 Q4)
        self.assertEqual(
            [f["key"] for f in data["fields"]][:4],
            ["appearance", "packaging", "labeling", "verdict"],
        )
        self.assertEqual(
            next(f for f in data["fields"] if f["key"] == "verdict")["option_labels"]["FAIL"],
            "부적합",
        )

    def test_tc008_empty_day_and_all_draft(self):
        empty = self.sheet("2026-10-01")
        self.assertEqual(
            (empty["printable_count"], empty["lines"], empty["template"]), (0, [], None)
        )
        day = "2026-10-02"
        d03("draft", day=day)
        d03("empty", day=day)
        data = self.sheet(day)
        self.assertEqual(data["printable_count"], 0)
        self.assertEqual([line["state"] for line in data["lines"]], ["draft", "draft"])

    def test_rejected_and_partial(self):
        day = "2026-10-03"
        rejected = d03("rejected", day=day)
        partial = d03("submitted_partial", day=day)
        lines = {line["document_id"]: line for line in self.sheet(day)["lines"]}
        self.assertEqual(
            (lines[rejected["document_id"]]["state"], lines[rejected["document_id"]]["printable"]),
            ("rejected", False),
        )
        self.assertEqual(
            [b["staff_id"] for b in lines[partial["document_id"]]["approval"]], [3, None]
        )

    def test_correcting_line_uses_approved_snapshot(self):
        day = "2026-10-05"
        made = d03("correcting", day=day)
        fill(made["document_id"], "FAIL")  # 정정 중 값 바꿈 + 개선조치(지금 값)
        line = self.sheet(day)["lines"][0]
        self.assertEqual(
            (line["state"], line["values"]["verdict"], line["values"]["packaging"]),
            ("ok", "PASS", "양호"),
        )
        self.assertEqual([b["staff_id"] for b in line["approval"]], [3, 1])
        deviations = self.sheet(day)["deviations"]
        self.assertEqual([d["description"] for d in deviations], ["포장 파손"])

    def test_deviations_of_printable_lines(self):
        day = "2026-10-06"
        bad = d03("completed", verdict="FAIL", day=day)
        d03("draft", verdict="FAIL", day=day)  # 출력 불가 줄의 개선조치는 빠짐
        data = self.sheet(day)
        self.assertEqual(len(data["deviations"]), 1)
        row = data["deviations"][0]
        self.assertEqual(
            (row["document_id"], row["work_date"], row["lot_number"]),
            (bad["document_id"], day, bad["lot_number"]),
        )
        self.assertEqual(
            (row["description"], row["action_result"], row["checked_by"]),
            ("포장 파손", "반품", None),
        )

    def test_tc016a_many_documents_split(self):
        day = "2026-10-07"
        for _ in range(101):
            d03("completed", day=day)
        calls = []
        real = doc.documents_for_print

        def spy(ids):
            calls.append(len(ids))
            return real(ids)

        with mock.patch.object(doc, "documents_for_print", spy):
            data = self.sheet(day)
        self.assertEqual(calls, [100, 1])
        self.assertEqual((len(data["lines"]), data["printable_count"]), (101, 101))

    def test_fixed_sql_count(self):
        def count(day, n):
            for _ in range(n):
                d03("approved", day=day)
            with CaptureQueriesContext(connection) as queries:
                self.sheet(day)
            return len(queries)

        self.assertEqual(count("2026-10-08", 2), count("2026-10-09", 5))

    def test_tc019_no_writes(self):
        made = d03("approved", day="2026-10-10")
        before = version_of(made["document_id"])
        self.sheet("2026-10-10")
        self.assertEqual(version_of(made["document_id"]), before)


class DocumentEntryTests(D03PrintTestCase):
    def test_document_opens_its_receiving_day(self):
        made = d03("approved", day="2026-10-11")
        d03("completed", day="2026-10-11")
        data = printing.print_sheet(made["document_id"])
        self.assertEqual(
            (data["kind"], data["date"], len(data["lines"])), ("receiving", "2026-10-11", 2)
        )

    def test_tc002_draft_document_not_printable(self):
        made = d03("draft", day="2026-10-11")
        with self.assertRaises(printing.NotPrintableStatus):
            printing.print_sheet(made["document_id"])


class ReceivingApiTests(D03PrintTestCase):
    def test_ok(self):
        made = d03("approved")
        response = self.get({"kind": "receiving", "type": "D03", "date": DAY})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["lines"][0]["document_id"], made["document_id"])
        by_document = self.get({"document_id": made["document_id"]})
        self.assertEqual(by_document.json()["key"], {"type": "D03", "date": DAY})

    def test_tc015_errors(self):
        draft = d03("draft")["document_id"]
        approved = d03("approved")["document_id"]
        future = (timezone.localdate() + datetime.timedelta(days=1)).isoformat()
        cases = [
            ({"kind": "receiving", "type": "D01", "date": DAY}, 400, "NOT_PRINTABLE_TYPE"),
            ({"kind": "receiving", "type": "D02", "date": DAY}, 400, "NOT_PRINTABLE_TYPE"),
            ({"kind": "receiving", "type": "D11", "date": DAY}, 400, "INVALID_FILTER"),
            ({"kind": "receiving", "type": "D10", "date": DAY}, 400, "INVALID_FILTER"),
            ({"kind": "weekly", "type": "D03", "date": DAY}, 400, "INVALID_FILTER"),
            ({"kind": "receiving", "type": "CCP-1P", "date": DAY}, 400, "INVALID_FILTER"),
            ({"kind": "receiving", "type": "D03"}, 400, "INVALID_FILTER"),
            ({"kind": "receiving", "type": "D03", "date": "2026-13-01"}, 400, "INVALID_FILTER"),
            ({"kind": "receiving", "type": "D03", "date": "2026-1-1"}, 400, "INVALID_FILTER"),
            ({"kind": "receiving", "type": "D03", "date": future}, 400, "INVALID_FILTER"),
            ({"type": "D03", "date": DAY}, 400, "INVALID_FILTER"),
            ({"kind": "receiving", "date": DAY}, 400, "INVALID_FILTER"),
            (
                {"kind": "receiving", "type": "D03", "date": DAY, "month": "2026-10"},
                400,
                "INVALID_FILTER",
            ),
            ({"document_id": approved, "type": "D03"}, 400, "INVALID_FILTER"),
            ({"document_id": approved, "kind": "receiving"}, 400, "INVALID_FILTER"),
            ({"document_id": approved, "kind": "single"}, 400, "INVALID_FILTER"),
            ({"document_id": draft}, 409, "NOT_PRINTABLE_STATUS"),
        ]
        for query, status, code in cases:
            with self.subTest(query=query):
                response = self.get(query)
                self.assertEqual(response.status_code, status, response.json())
                self.assertEqual(response.json()["code"], code)


@override_settings(
    ROOT_URLCONF="apps.devtools.test_urls",
    MIDDLEWARE=[*settings.MIDDLEWARE, "apps.devtools.middleware.TraceMiddleware"],
)
class ReceivingTraceTests(D03PrintTestCase):
    def ids(self, response):
        return [s["step_id"] for s in response.json()["trace"]["steps"]]

    def test_flows(self):
        made = d03("approved")
        ok = self.get({"kind": "receiving", "type": "D03", "date": DAY})
        self.assertTrue(flows.matches("WF-PRT-RCV", self.ids(ok)), self.ids(ok))
        by_document = self.get({"document_id": made["document_id"]})
        self.assertTrue(
            flows.matches("WF-PRT-RCV-DOC", self.ids(by_document)), self.ids(by_document)
        )
        empty = self.get({"kind": "receiving", "type": "D03", "date": "2026-10-01"})
        self.assertTrue(flows.matches("WF-PRT-RCV-EMPTY", self.ids(empty)), self.ids(empty))
