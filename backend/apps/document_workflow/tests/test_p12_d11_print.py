"""P12 출력 — D11 월 묶음(monthly) (p12-d11-policy.md DP-17).

2026-08 = 월요일 5개(3·10·17·24·31), 2026-09 = 4개(7·14·21·28 — 5주 칸 없음, Q5 c).
"""

import datetime
from unittest import mock

from django.conf import settings
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.approvals.models import Approval
from apps.document_workflow import flows, printing
from apps.document_workflow import services as wf
from apps.documents import services as doc
from apps.documents.tests.p8 import fill, periodic, setup_p8


def version_of(document_id):
    return doc.get_document(document_id)["version"]


def make(monday, state="approved", value="O", remark=None, owner=3, leader=1, at=None):
    made = periodic("D11", monday)
    document_id = made["document_id"]
    if state == "skipped":
        doc.skip_documents(
            3, [{"document_id": document_id, "expected_version": made["version"]}], "휴무"
        )
        return document_id
    checked = (datetime.date.fromisoformat(monday) + datetime.timedelta(days=2)).isoformat()
    extra = {"info": {"checked_on": checked, **({"remark": remark} if remark else {})}}
    fill(document_id, value, 4, extra)
    if value == "X":
        doc.create_deviation(
            4, document_id, {"description": "포충등 고장", "action_result": "교체"}
        )
    if state == "draft":
        return document_id
    doc.complete_document(3, document_id, version_of(document_id))
    if state == "completed":
        return document_id
    request = wf.submit(3, document_id, version_of(document_id))["request"]
    slots = {s["role"]: s["approval_id"] for s in request["slots"]}
    wf.decide(owner, slots["owner"], "approved")
    if at:
        Approval.objects.filter(pk=slots["owner"]).update(decided_at=at)
    if state == "partial":
        return document_id
    wf.decide(leader, slots["leader"], "approved")
    if at:
        Approval.objects.filter(pk=slots["leader"]).update(decided_at=at)
    if state == "correcting":
        doc.start_correction(3, document_id, version_of(document_id), "재확인")
        fill(document_id, "X", 4, extra)
    return document_id


def at(text):
    return datetime.datetime.fromisoformat(f"{text}+09:00")


class D11SheetTests(TestCase):
    def setUp(self):
        setup_p8()

    def sheet(self, month="2026-08"):
        return printing.print_by_query({"kind": "monthly", "type": "D11", "month": month})

    def test_weeks_states_header_and_remarks(self):
        first = make("2026-08-03", remark="포충등 1대 램프 교체 예정", at=at("2026-08-06 10:00"))
        make("2026-08-10", owner=2, leader=5, at=at("2026-08-13 10:00"))  # 가장 최근 승인
        make("2026-08-17", "partial", remark="결재중 주 특이사항")
        make("2026-08-24", "draft", remark="작성중(출력 안 됨)")
        make("2026-08-31", "skipped")
        data = self.sheet()
        self.assertEqual(
            (data["kind"], data["type_code"], data["month"]), ("monthly", "D11", "2026-08")
        )
        self.assertEqual(data["title"], "방충방서점검표")
        weeks = data["weeks"]
        self.assertEqual([w["week_no"] for w in weeks], [1, 2, 3, 4, 5])
        self.assertEqual([w["week_start"] for w in weeks][0], "2026-08-03")
        self.assertEqual([w["state"] for w in weeks], ["ok", "ok", "ok", "draft", "skipped"])
        self.assertEqual(weeks[0]["checked_on"], "2026-08-05")
        self.assertEqual(weeks[0]["values"]["fly_trap_lamp"], "O")
        self.assertIsNone(weeks[3]["values"])
        self.assertEqual(data["printable_count"], 3)
        self.assertEqual(
            [b["staff_id"] for b in data["boxes"]], [3, 5]
        )  # 작성자 = 3주(3), 팀장 = 2주(5)
        self.assertEqual(
            [(r["week_no"], r["remark"]) for r in data["remarks"]],
            [(1, "포충등 1대 램프 교체 예정"), (3, "결재중 주 특이사항")],
        )
        self.assertNotIn("4", data["people"])  # 점검자 출력 안 함(Q8 a)
        self.assertEqual(first, weeks[0]["document_id"])

    def test_four_mondays_and_future(self):
        make("2026-09-07")
        self.assertEqual(len(self.sheet("2026-09")["weeks"]), 4)  # 5주 칸 없음(Q5 c)
        with mock.patch.object(timezone, "localdate", return_value=datetime.date(2026, 9, 15)):
            data = self.sheet("2026-09")
        self.assertEqual([w["state"] for w in data["weeks"]], ["ok", "missing", "future", "future"])

    def test_correcting_and_document_entry(self):
        made = make("2026-08-10", "correcting")
        data = printing.print_sheet(made)
        self.assertEqual(data["key"], {"type": "D11", "month": "2026-08"})
        self.assertEqual(data["weeks"][1]["values"]["fly_trap_lamp"], "O")  # 승인본

    def test_empty_month(self):
        data = self.sheet("2026-07")
        self.assertEqual(
            (data["printable_count"], data["template"], len(data["weeks"])), (0, None, 4)
        )

    def test_api_errors(self):
        draft = make("2026-08-03", "draft")
        future = (timezone.localdate().replace(day=1) + datetime.timedelta(days=40)).strftime(
            "%Y-%m"
        )
        cases = [
            ({"kind": "monthly", "type": "D11", "month": "2026-8"}, "INVALID_FILTER"),
            ({"kind": "monthly", "type": "D11", "month": "2026-13"}, "INVALID_FILTER"),
            ({"kind": "monthly", "type": "D11", "month": future}, "INVALID_FILTER"),
            ({"kind": "monthly", "type": "D11", "date": "2026-08-03"}, "INVALID_FILTER"),
            ({"kind": "weekly", "type": "D11", "date": "2026-08-03"}, "INVALID_FILTER"),
            (
                {"kind": "weekly", "type": "D10", "date": "2026-08-03", "month": "2026-08"},
                "INVALID_FILTER",
            ),
            ({"kind": "monthly", "type": "D10", "month": "2026-08"}, "INVALID_FILTER"),
            ({"document_id": draft, "month": "2026-08"}, "INVALID_FILTER"),
            ({"document_id": draft}, "NOT_PRINTABLE_STATUS"),
        ]
        for query, code in cases:
            with self.subTest(query=query):
                response = self.client.get("/api/v1/print/sheet", query)
                self.assertEqual(response.json()["code"], code)
        ok = self.client.get(
            "/api/v1/print/sheet", {"kind": "monthly", "type": "D11", "month": "2026-08"}
        )
        self.assertEqual(ok.status_code, 200)


@override_settings(
    ROOT_URLCONF="apps.devtools.test_urls",
    MIDDLEWARE=[*settings.MIDDLEWARE, "apps.devtools.middleware.TraceMiddleware"],
)
class MonthlyTraceTests(TestCase):
    def setUp(self):
        setup_p8()

    def ids(self, response):
        return [s["step_id"] for s in response.json()["trace"]["steps"]]

    def test_flows(self):
        made = make("2026-08-03")
        get = lambda q: self.client.get("/api/v1/print/sheet", q)  # noqa: E731
        ok = get({"kind": "monthly", "type": "D11", "month": "2026-08"})
        self.assertTrue(flows.matches("WF-PRT-MON", self.ids(ok)), self.ids(ok))
        by_document = get({"document_id": made})
        self.assertTrue(
            flows.matches("WF-PRT-MON-DOC", self.ids(by_document)), self.ids(by_document)
        )
        empty = get({"kind": "monthly", "type": "D11", "month": "2026-07"})
        self.assertTrue(flows.matches("WF-PRT-MON-EMPTY", self.ids(empty)), self.ids(empty))
