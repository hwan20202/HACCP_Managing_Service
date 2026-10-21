"""P11 S4 DOC — N8 측정 요약·F30 확인 대기·F31 확인 (p11-s2-spec 6장 P11-TC-006~029).

이름의 tcNNN은 P11-TC ID. 오늘은 2026-10-13(화)로 고정(p11.fixed_today).
"""

import json

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.documents import errors, services
from apps.documents.models import DeviationAction
from apps.documents.tests.p8 import MON
from apps.documents.tests.p8 import periodic as per
from apps.staff.services import StaffHeaderMissing

from .p11 import (
    TODAY,
    add_rows,
    at,
    ccp_doc,
    d03_doc,
    delete_doc,
    deviation,
    fixed_today,
    r1p,
    r2b,
    r3p,
    set_status,
    setup_p11,
    summary,
    version_of,
)

CODES = ["CCP-1P", "CCP-2B", "CCP-3P"]


class P11TestCase(TestCase):
    def setUp(self):
        setup_p11()
        stack = fixed_today()
        stack.__enter__()
        self.addCleanup(stack.__exit__, None, None, None)

    def summary_of(self, document_id, day=TODAY, codes=CODES):
        out = services.measurement_summary(day, codes)
        return next(d for d in out["documents"] if d["document_id"] == document_id)

    def pending(self, actor=3, base=None, mine=False, summary=False):
        return services.pending_deviations(actor, base, mine, summary)


class MeasurementSummaryTests(P11TestCase):
    def test_tc006_latest_by_time_then_row_no(self):
        document_id = ccp_doc("CCP-1P", 12)
        add_rows(
            document_id,
            "rounds",
            [r1p("13:00", phase="작업시작 전"), r1p("09:00"), r1p("13:00"), {"phase": "작업 중"}],
        )
        latest = self.summary_of(document_id)["latest"]
        self.assertEqual((latest["at"], latest["section_def"]), (at("13:00"), "rounds"))
        self.assertEqual(latest["phase"], "작업 중")  # 같은 시각 → row_no 큰 것(3번째 행)
        self.assertEqual(latest["verdict"], "적합")
        self.assertEqual(self.summary_of(document_id)["rows_by_section"], {"rounds": 4})

    def test_tc006_no_rows(self):
        document_id = ccp_doc("CCP-3P", 12)
        own = self.summary_of(document_id)
        self.assertEqual((own["latest"], own["rows_by_section"]), (None, {"checks": 0}))
        self.assertEqual((own["label"], own["item_name"]), ("PB-12", "유자차"))

    def test_tc007_3p_summary_and_specimen(self):
        document_id = ccp_doc("CCP-3P", 12)
        add_rows(document_id, "checks", [r3p("09:00", fe_c="X")])
        add_rows(document_id, "summary", [summary(2)])
        bad = self.summary_of(document_id)["nonconforming"]
        by_section = {b["section_def"]: b for b in bad}
        self.assertEqual(
            by_section["checks"]["reasons"],
            [{"field": "fe_c", "label": "Fe 중", "value": "X", "expect": {"eq": "○"}}],
        )
        self.assertEqual(by_section["checks"]["at"], at("09:00"))
        self.assertEqual(
            by_section["summary"]["reasons"],
            [{"field": "detected_qty", "label": "검출량", "value": 2, "expect": {"gt": 0}}],
        )
        self.assertIsNone(by_section["summary"]["at"])

    def test_tc001_2b_reasons_min_max(self):
        document_id = ccp_doc("CCP-2B", 12)
        add_rows(document_id, "rounds", [r2b("10:00", temp=73.5)])
        (bad,) = self.summary_of(document_id)["nonconforming"]
        self.assertEqual(
            bad["reasons"],
            [
                {
                    "field": "temp_c",
                    "label": "건조온도(℃)",
                    "value": 73.5,
                    "expect": {"min": 68.0, "max": 72.0},
                }
            ],
        )

    def test_tc008_sql_count_and_validation(self):
        for batch_id in (12, 15):
            for code in CODES:
                ccp_doc(code, batch_id)
        with CaptureQueriesContext(connection) as queries:
            out = services.measurement_summary(TODAY, CODES)
        self.assertEqual(len(out["documents"]), 6)
        self.assertLessEqual(len(queries), 6)
        self.assertEqual(out["templates"]["CCP-2B"], "CCP-2B 모니터링일지(건조)")
        with self.assertRaises(errors.ValidationFailed):
            services.measurement_summary(TODAY, [])
        with self.assertRaises(errors.ValidationFailed):
            services.measurement_summary("2026-13-01", CODES)

    def test_period_days(self):
        from apps.documents.seed_forms import CCP_1P, D10, D11

        self.assertEqual([services.period_days(s) for s in (D11, D10, CCP_1P, None)], [6, 0, 0, 0])


class PendingTests(P11TestCase):
    def test_tc010_visibility_immediate_vs_after_complete(self):
        ccp = ccp_doc("CCP-1P", 12)
        d03 = d03_doc()
        a, b = deviation(ccp), deviation(d03)
        ids = [r["deviation_id"] for r in self.pending()["rows"]]
        self.assertIn(a["deviation_id"], ids)
        self.assertNotIn(b["deviation_id"], ids)

    def test_tc011_d03_states(self):
        d03 = d03_doc()
        x = deviation(d03)["deviation_id"]
        for status, shown in (
            ("completed", True),
            ("submitted", True),
            ("approved", True),
            ("rejected", True),
            ("correcting", True),
            ("draft", False),
        ):
            with self.subTest(status=status):
                set_status(d03, status)
                ids = [r["deviation_id"] for r in self.pending()["rows"]]
                self.assertEqual(x in ids, shown)

    def test_skipped_hidden_even_when_immediate(self):
        ccp = ccp_doc("CCP-1P", 12)
        x = deviation(ccp)["deviation_id"]
        set_status(ccp, "skipped")
        self.assertNotIn(x, [r["deviation_id"] for r in self.pending()["rows"]])

    def test_tc012_no_checker(self):
        ccp = ccp_doc("CCP-1P", 12)
        x = deviation(ccp, checkers=())["deviation_id"]
        out = self.pending()
        self.assertEqual(out["rows"], [])
        self.assertEqual(out["no_checker"]["count"], 1)
        self.assertEqual(out["no_checker"]["rows"][0]["deviation_id"], x)
        self.assertEqual(out["my_total"], 0)

    def test_tc013_base_date_and_period_document(self):
        today_doc = ccp_doc("CCP-1P", 12)
        d1010 = ccp_doc("CCP-1P", 15, day="2026-10-10")
        d1007 = ccp_doc("CCP-1P", 16, day="2026-10-07")
        d11 = per("D11", MON)["document_id"]
        set_status(d11, "completed")  # D11은 노출 = 작성완료 이후(양식 키 없음)
        mine = [deviation(d)["deviation_id"] for d in (today_doc, d1010, d1007, d11)]
        out = self.pending(base="2026-10-13")
        self.assertEqual([r["deviation_id"] for r in out["rows"]], [mine[0], mine[3]])
        self.assertEqual(
            [(g["work_date"], g["count"], g["future"]) for g in out["other_days_mine"]],
            [("2026-10-10", 1, False), ("2026-10-07", 1, False)],
        )
        self.assertEqual((out["other_days_mine_total"], out["my_total"]), (2, 4))
        self.assertEqual(out["counts"], {"total": 2, "mine": 2})
        # D11 주의 일요일(10-18)까지 기준일 문서, 다음 월요일(10-19)부터는 다른 날
        with fixed_today("2026-10-19"):
            for base, inside in (("2026-10-18", True), ("2026-10-19", False)):
                with self.subTest(base=base):
                    rows = [r["deviation_id"] for r in self.pending(base=base)["rows"]]
                    self.assertEqual(mine[3] in rows, inside)

    def test_tc014_mine_and_summary(self):
        ccp = ccp_doc("CCP-1P", 12)
        a = deviation(ccp, checkers=(3,))["deviation_id"]
        deviation(ccp, checkers=(4,))
        out = self.pending(mine=True)
        self.assertEqual([r["deviation_id"] for r in out["rows"]], [a])
        self.assertEqual(out["counts"], {"total": 2, "mine": 1})
        with CaptureQueriesContext(connection) as queries:
            self.assertEqual(self.pending(summary=True), {"my_total": 1})
        self.assertEqual(len(queries), 2)  # P14 R05: 역할(직원 코드 → id) 1 + 합계 1

    def test_tc015_deleted_and_checked_not_counted(self):
        ccp = ccp_doc("CCP-1P", 12)
        gone = deviation(ccp)
        services.delete_deviation(3, gone["deviation_id"], gone["version"])
        done = deviation(ccp)
        services.check_deviation(3, done["deviation_id"], done["version"])
        other = ccp_doc("CCP-2B", 12)
        deviation(other)
        delete_doc(other)
        out = self.pending()
        self.assertEqual((out["rows"], out["no_checker"]["count"], out["my_total"]), ([], 0, 0))

    def test_tc016_sql_count_and_target_summary(self):
        ccp = ccp_doc("CCP-1P", 12)
        d03 = d03_doc()
        set_status(d03, "completed")
        deviation(ccp)
        deviation(d03)
        deviation(ccp, checkers=())
        with CaptureQueriesContext(connection) as queries:
            out = self.pending()
        self.assertLessEqual(len(queries), 6)  # P14 R05: + 역할 1
        targets = {r["type_code"]: r["target_summary"] for r in out["rows"]}
        self.assertEqual(targets["CCP-1P"], "배치 PB-12 · 1P")
        self.assertTrue(targets["D03"].startswith("LOT RM-1013-01"), targets)

    def test_tc018_without_header(self):
        ccp = ccp_doc("CCP-1P", 12)
        deviation(ccp)
        out = self.pending(actor=None)
        self.assertEqual(out["counts"], {"total": 1})
        self.assertFalse(out["rows"][0]["can_check"])
        for key in ("other_days_mine", "other_days_mine_total", "my_total"):
            self.assertNotIn(key, out)
        for kwargs in ({"mine": True}, {"summary": True}):
            with self.subTest(**kwargs), self.assertRaises(StaffHeaderMissing):
                self.pending(actor=None, **kwargs)

    def test_tc019_other_days_limit_and_future(self):
        from datetime import date, timedelta

        start = date(2026, 9, 30)
        for i in range(12):
            day = (start + timedelta(days=i)).isoformat()
            document_id = per("D10", day)["document_id"]
            set_status(document_id, "completed")
            deviation(document_id)
            if i == 0:
                deviation(document_id)  # 같은 날 2건 → 13건
        future = ccp_doc("CCP-1P", 12, day="2026-10-20")
        deviation(future)
        out = self.pending(base="2026-10-13")
        days = out["other_days_mine"]
        self.assertEqual(len(days), 10)
        self.assertEqual(days[0], {"work_date": "2026-10-20", "count": 1, "future": True,
                                   "document_ids": [future]})  # fmt: skip
        self.assertEqual(out["other_days_mine_total"], 14)
        self.assertEqual(out["my_total"], out["counts"]["mine"] + 14)

    def test_tc017_filters(self):
        for kwargs in (
            {"base": "2026-10-14"},
            {"base": "2026/10/13"},
            {"mine": "2"},
            {"summary": "x"},
        ):
            with self.subTest(**kwargs), self.assertRaises(errors.InvalidFilter):
                self.pending(**kwargs)


class CheckTests(P11TestCase):
    def setUp(self):
        super().setUp()
        self.document_id = ccp_doc("CCP-1P", 12)
        self.x = deviation(self.document_id, checkers=(3, 5))

    def test_tc020_check(self):
        doc_version = version_of(self.document_id)
        out = services.check_deviation(3, self.x["deviation_id"], self.x["version"])
        self.assertEqual((out["checked_by"], out["version"]), (3, 2))
        self.assertIsNotNone(out["checked_at"])
        self.assertEqual(
            (out["updated_by"], out["updated_at"]), (self.x["updated_by"], self.x["updated_at"])
        )
        self.assertEqual(version_of(self.document_id), doc_version)

    def test_tc021_not_found(self):
        with self.assertRaises(errors.DeviationNotFound):
            services.check_deviation(3, 9999, 1)
        services.delete_deviation(3, self.x["deviation_id"], 1)
        with self.assertRaises(errors.DeviationNotFound):
            services.check_deviation(3, self.x["deviation_id"], 2)
        y = deviation(self.document_id)
        delete_doc(self.document_id)
        with self.assertRaises(errors.DeviationNotFound):
            services.check_deviation(3, y["deviation_id"], 1)

    def test_tc022_already_checked(self):
        services.check_deviation(5, self.x["deviation_id"], 1)
        for version in (1, 2):
            with self.subTest(version=version), self.assertRaises(errors.AlreadyChecked) as ctx:
                services.check_deviation(3, self.x["deviation_id"], version)
            self.assertEqual(ctx.exception.details[0]["checked_by"], 5)
        self.assertEqual(DeviationAction.objects.get(pk=self.x["deviation_id"]).version, 2)

    def test_tc023_not_checker(self):
        with self.assertRaises(errors.NotChecker):
            services.check_deviation(4, self.x["deviation_id"], 1)
        self.assertIsNone(DeviationAction.objects.get(pk=self.x["deviation_id"]).checked_at)

    def test_tc024_version_conflict(self):
        services.update_deviation(3, self.x["deviation_id"], 1, {"action_result": "재측정"})
        with self.assertRaises(errors.VersionConflict):
            services.check_deviation(3, self.x["deviation_id"], 1)

    def test_tc025_expected_version_format(self):
        for value in (None, "1", 0, True):
            with self.subTest(value=value), self.assertRaises(errors.ValidationFailed):
                services.check_deviation(3, self.x["deviation_id"], value)

    def test_tc026_edit_after_check_keeps_record(self):
        out = services.check_deviation(3, self.x["deviation_id"], 1)
        after = services.update_deviation(
            3, self.x["deviation_id"], out["version"], {"action_result": "고침", "checker_ids": [5]}
        )
        self.assertEqual((after["checked_by"], after["checked_at"]), (3, out["checked_at"]))

    def test_tc027_draft_general_form_can_check(self):
        d03 = d03_doc()
        y = deviation(d03)
        self.assertEqual(services.check_deviation(3, y["deviation_id"], 1)["checked_by"], 3)

    def test_tc029_patch_cannot_set_checked(self):
        with self.assertRaises(errors.ValidationFailed) as ctx:
            services.update_deviation(3, self.x["deviation_id"], 1, {"checked_by": 3})
        self.assertEqual(ctx.exception.details[0]["code"], "unknown_field")


class ApiTests(P11TestCase):
    def get(self, path, staff=3):
        headers = {"HTTP_X_STAFF_ID": str(staff)} if staff is not None else {}
        return self.client.get(path, **headers)

    def post(self, path, body, staff=3):
        headers = {"HTTP_X_STAFF_ID": str(staff)} if staff is not None else {}
        return self.client.post(path, json.dumps(body), content_type="application/json", **headers)

    def test_tc017_pending_api_errors(self):
        for query, status, code in (
            ("date=2026-10-14", 400, "INVALID_FILTER"),
            ("date=x", 400, "INVALID_FILTER"),
            ("mine=2", 400, "INVALID_FILTER"),
            ("summary=x", 400, "INVALID_FILTER"),
        ):
            with self.subTest(query=query):
                response = self.get(f"/api/v1/deviations/pending?{query}")
                self.assertEqual((response.status_code, response.json()["code"]), (status, code))
        response = self.get("/api/v1/deviations/pending?mine=1", staff=None)
        self.assertEqual(response.json()["code"], "STAFF_HEADER_MISSING")
        response = self.get("/api/v1/deviations/pending", staff=99)
        self.assertEqual((response.status_code, response.json()["code"]), (403, "INVALID_STAFF"))

    def test_pending_api_ok(self):
        document_id = ccp_doc("CCP-1P", 12)
        deviation(document_id)
        body = self.get("/api/v1/deviations/pending").json()
        self.assertEqual((body["counts"], body["my_total"]), ({"total": 1, "mine": 1}, 1))
        self.assertEqual(self.get("/api/v1/deviations/pending", staff=None).status_code, 200)
        self.assertEqual(self.get("/api/v1/deviations/pending?summary=1").json(), {"my_total": 1})

    def test_check_api(self):
        document_id = ccp_doc("CCP-1P", 12)
        x = deviation(document_id, checkers=(3,))
        url = f"/api/v1/deviations/{x['deviation_id']}/check"
        self.assertEqual(self.post(url, {"expected_version": 1}, staff=4).status_code, 403)
        response = self.post(url, {"expected_version": "1"})
        self.assertEqual((response.status_code, response.json()["code"]), (400, "VALIDATION_ERROR"))
        response = self.post(url, {"expected_version": 1, "x": 1})
        self.assertEqual(response.status_code, 400)
        response = self.post(url, {"expected_version": 1})
        self.assertEqual((response.status_code, response.json()["checked_by"]), (200, 3))
        response = self.post(url, {"expected_version": 2})
        self.assertEqual((response.status_code, response.json()["code"]), (409, "ALREADY_CHECKED"))
        self.assertEqual(self.post("/api/v1/deviations/9999/check", {"expected_version": 1})
                         .status_code, 404)  # fmt: skip


class FlowTests(P11TestCase):
    def steps_of(self, call):
        from apps.documents.tests.p8 import captured

        with captured() as steps:
            call()
        return steps

    def test_flows(self):
        from apps.documents import flows

        document_id = ccp_doc("CCP-1P", 12)
        x = deviation(document_id)
        cases = (
            ("DOC-PND", "DOC-PND-00", lambda: self.pending()),
            ("DOC-PND-ANON", "DOC-PND-00", lambda: self.pending(actor=None)),
            ("DOC-PND-SUM", "DOC-PND-00", lambda: self.pending(summary=True)),
            ("DOC-DVK", "DOC-DVK-00", lambda: services.check_deviation(3, x["deviation_id"], 1)),
            ("DOC-MSM", None, lambda: services.measurement_summary(TODAY, CODES)),
        )
        for flow_id, api_step, call in cases:
            with self.subTest(flow=flow_id):
                steps = self.steps_of(call)
                head = [api_step] if api_step else []
                self.assertTrue(flows.matches(flow_id, [*head, *steps]), steps)
