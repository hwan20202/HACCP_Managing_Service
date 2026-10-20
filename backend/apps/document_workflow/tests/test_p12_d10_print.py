"""P12 출력 — D10 주 묶음(weekly) (p12-d10-policy.md DP-12).

주 2026-10-12(월) ~ 10-18(일). 칸 = 월~금 + 문서 있는 토·일, 점검자 = 가장 늦은 요일 문서의 점검자,
결재 칸 = 칸마다 그 주에서 그 역할로 가장 최근에 승인한 사람, 출력 불가 칸은 값 없음.
"""

import datetime
from unittest import mock

from django.conf import settings
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.approvals.models import Approval
from apps.document_workflow import flows, printing
from apps.document_workflow import services as wf
from apps.documents import services as doc
from apps.documents.tests.p8 import FRI, MON, THU, TUE, WED, fill, periodic, setup_p8

SAT, SUN = "2026-10-17", "2026-10-18"
OWNER_A, OWNER_B, LEADER_A, LEADER_B = 3, 2, 1, 5  # roles.json: D10 작성자 {2, 3}, HACCP팀장 {1, 5}


def version_of(document_id):
    return doc.get_document(document_id)["version"]


def make(day, state="approved", value="O", inspector=4, owner=OWNER_A, leader=LEADER_A, at=None,
         extra=None):  # fmt: skip
    """D10 하루 문서를 state까지. at = (작성자 승인 시각, 팀장 승인 시각) 문자열."""
    made = periodic("D10", day)
    document_id = made["document_id"]
    if state == "empty":
        return document_id
    if state == "skipped":
        doc.skip_documents(
            3, [{"document_id": document_id, "expected_version": made["version"]}], "휴무"
        )
        return document_id
    fill(document_id, value, inspector, extra)
    if value == "X":
        doc.create_deviation(
            4,
            document_id,
            {"description": "작업장 바닥 오염", "action_result": "재청소", "actor_id": 4},
        )
    if state == "draft":
        return document_id
    doc.complete_document(3, document_id, version_of(document_id))
    if state == "completed":
        return document_id
    request = wf.submit(3, document_id, version_of(document_id))["request"]
    slots = {s["role"]: s["approval_id"] for s in request["slots"]}
    if state == "rejected":
        wf.decide(leader, slots["leader"], "rejected", "다시 확인")
        return document_id
    wf.decide(owner, slots["owner"], "approved")
    if at:
        Approval.objects.filter(pk=slots["owner"]).update(decided_at=at[0])
    if state == "partial":
        return document_id
    wf.decide(leader, slots["leader"], "approved")
    if at:
        Approval.objects.filter(pk=slots["leader"]).update(decided_at=at[1])
    if state == "correcting":
        doc.start_correction(3, document_id, version_of(document_id), "재확인")
        fill(document_id, "X", inspector)  # 지금 값은 X, 승인본은 O
    return document_id


def at(text):
    return datetime.datetime.fromisoformat(f"{text}+09:00")


class D10PrintTestCase(TestCase):
    def setUp(self):
        setup_p8()

    def sheet(self, day=MON):
        return printing.print_by_query({"kind": "weekly", "type": "D10", "date": day})


class WeeklySheetTests(D10PrintTestCase):
    def test_days_states_and_header(self):
        mon = make(
            MON, at=(at("2026-10-12 18:00"), at("2026-10-19 09:00"))
        )  # 팀장 승인이 가장 늦음
        tue = make(TUE, owner=OWNER_B, leader=LEADER_B, inspector=2,
                   at=(at("2026-10-13 18:00"), at("2026-10-14 09:00")))  # fmt: skip
        wed = make(WED, "partial", inspector=5, at=(at("2026-10-15 08:00"), None))
        make(THU, "draft", inspector=1)  # 출력 불가 — 점검자 후보 아님
        make(FRI, "skipped")
        data = self.sheet(WED)  # 그 주 아무 날 → 월요일
        self.assertEqual((data["kind"], data["type_code"]), ("weekly", "D10"))
        self.assertEqual(data["key"], {"type": "D10", "date": MON})
        self.assertEqual(data["title"], "일반위생관리 및 공정점검표")
        self.assertEqual(data["period"], {"from": MON, "to": FRI})
        days = data["days"]
        self.assertEqual([d["weekday"] for d in days], list("월화수목금"))
        self.assertEqual([d["state"] for d in days], ["ok", "ok", "ok", "draft", "skipped"])
        self.assertEqual(days[4]["skip_reason"], "휴무")
        self.assertEqual([d["document_id"] for d in days[:3]], [mon, tue, wed])
        self.assertIsNone(days[3]["values"])
        self.assertEqual(days[0]["values"]["d_hyg_clothes"], "O")
        self.assertEqual(data["printable_count"], 3)
        self.assertEqual(data["inspector_id"], 5)  # 가장 늦은 출력 가능 요일(수)의 점검자
        self.assertEqual(
            [(b["label"], b["staff_id"]) for b in data["boxes"]],
            [
                ("작성자", OWNER_A),
                ("HACCP팀장", LEADER_A),
            ],  # 작성자 최근 = 수(3), 팀장 최근 = 월 승인
        )
        self.assertEqual(set(data["people"]), {"1", "3", "5"})
        fields = {f["key"]: f for f in data["fields"]}
        self.assertEqual(fields["d_hyg_clothes"]["cadence"], "매일 작업 전후")
        self.assertEqual(fields["d_hyg_clothes"]["group"], "개인위생")
        self.assertEqual(fields["y_water_test_date"]["type"], "date")

    def test_weekend_columns_only_with_documents(self):
        make(MON)
        sat = make(SAT, "completed")
        data = self.sheet()
        self.assertEqual([d["weekday"] for d in data["days"]], list("월화수목금토"))
        self.assertEqual(data["days"][5]["document_id"], sat)
        self.assertEqual(data["period"], {"from": MON, "to": SAT})
        sun = make(SUN, "draft")  # 출력 불가 주말 문서는 칸 없음(W3 a)
        self.assertEqual([d["weekday"] for d in self.sheet()["days"]], list("월화수목금토"))
        self.assertNotIn(sun, [d["document_id"] for d in self.sheet()["days"]])
        make("2026-10-11", "skipped")  # 지난주 일요일 작성 안 함 → 그 주도 월~금
        self.assertEqual(len(self.sheet("2026-10-05")["days"]), 5)
        make("2026-10-04", "approved")  # 10-04(일)는 9-28 주
        self.assertEqual(self.sheet("2026-09-28")["days"][-1]["weekday"], "일")
        self.assertEqual(self.sheet("2026-09-28")["period"]["to"], "2026-10-04")
        # 주말 문서로 열어도 그 주 종이(W2 a)
        self.assertEqual(printing.print_sheet(sat)["key"], {"type": "D10", "date": MON})

    def test_missing_and_future(self):
        make(MON)
        with mock.patch.object(timezone, "localdate", return_value=datetime.date(2026, 10, 14)):
            data = self.sheet()
        self.assertEqual(
            [d["state"] for d in data["days"]], ["ok", "missing", "missing", "future", "future"]
        )

    def test_latest_dates_and_na(self):
        make(MON, extra={"checks": {"y_water_test_date": "2026-03-02"}})
        make(TUE, extra={"checks": {"y_water_test_date": "2026-10-13"}})
        make(WED, "draft", extra={"checks": {"y_water_test_date": "2026-12-01"}})  # 출력 불가 제외
        data = self.sheet()
        self.assertEqual(
            data["latest_dates"], {"y_water_test_date": "2026-10-13", "y_calibration_date": None}
        )
        self.assertEqual(data["days"][0]["values"]["w_laundry"], "NA")  # 금요일 아닌 날 기본 NA

    def test_correcting_uses_approved_snapshot_and_deviations(self):
        made = make(TUE, "correcting")
        bad = make(WED, "completed", value="X")
        data = self.sheet()
        self.assertEqual(data["days"][1]["values"]["d_hyg_clothes"], "O")  # 승인본
        self.assertEqual(
            [(d["document_id"], d["work_date"]) for d in data["deviations"]], [(bad, WED)]
        )
        self.assertEqual(data["deviations"][0]["description"], "작업장 바닥 오염")
        self.assertNotEqual(made, bad)

    def test_empty_week(self):
        data = self.sheet("2026-10-05")
        self.assertEqual((data["printable_count"], data["template"]), (0, None))
        self.assertEqual([d["state"] for d in data["days"]], ["missing"] * 5)
        self.assertEqual(data["boxes"][0]["staff_id"], None)

    def test_all_draft_week(self):
        make(MON, "draft")
        data = self.sheet()
        self.assertEqual(data["printable_count"], 0)
        self.assertEqual(data["days"][0]["state"], "draft")

    def test_sql_count_independent_of_documents(self):
        make(MON)
        with CaptureQueriesContext(connection) as one:
            self.sheet()
        for day in (TUE, WED, THU, FRI, SAT):
            make(day)
        with CaptureQueriesContext(connection) as many:
            self.sheet()
        self.assertEqual(len(one), len(many))

    def test_no_writes(self):
        make(MON)
        before = doc.get_document(self.sheet()["days"][0]["document_id"])["version"]
        self.sheet()
        self.assertEqual(
            doc.get_document(self.sheet()["days"][0]["document_id"])["version"], before
        )


class WeeklyApiTests(D10PrintTestCase):
    def get(self, query):
        return self.client.get("/api/v1/print/sheet", query)

    def test_api_and_document_entry(self):
        mon = make(MON)
        draft = make(TUE, "draft")
        response = self.get({"kind": "weekly", "type": "D10", "date": THU})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["week_start"], MON)
        self.assertEqual(self.get({"document_id": mon}).json()["kind"], "weekly")
        self.assertEqual(self.get({"document_id": draft}).status_code, 409)
        bad = self.get({"kind": "receiving", "type": "D10", "date": MON})
        self.assertEqual((bad.status_code, bad.json()["code"]), (400, "INVALID_FILTER"))
        future = (timezone.localdate() + datetime.timedelta(days=1)).isoformat()
        self.assertEqual(
            self.get({"kind": "weekly", "type": "D10", "date": future}).status_code, 400
        )
        self.assertEqual(
            self.get({"kind": "weekly", "type": "D02", "date": MON}).json()["code"],
            "NOT_PRINTABLE_TYPE",
        )


@override_settings(
    ROOT_URLCONF="apps.devtools.test_urls",
    MIDDLEWARE=[*settings.MIDDLEWARE, "apps.devtools.middleware.TraceMiddleware"],
)
class WeeklyTraceTests(D10PrintTestCase):
    def ids(self, response):
        return [s["step_id"] for s in response.json()["trace"]["steps"]]

    def test_flows(self):
        mon = make(MON)
        ok = self.client.get("/api/v1/print/sheet", {"kind": "weekly", "type": "D10", "date": MON})
        self.assertTrue(flows.matches("WF-PRT-WK", self.ids(ok)), self.ids(ok))
        by_document = self.client.get("/api/v1/print/sheet", {"document_id": mon})
        self.assertTrue(
            flows.matches("WF-PRT-WK-DOC", self.ids(by_document)), self.ids(by_document)
        )
        empty = self.client.get(
            "/api/v1/print/sheet", {"kind": "weekly", "type": "D10", "date": "2026-10-05"}
        )
        self.assertTrue(flows.matches("WF-PRT-WK-EMPTY", self.ids(empty)), self.ids(empty))
