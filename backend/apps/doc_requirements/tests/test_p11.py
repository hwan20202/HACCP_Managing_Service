"""P11 S4 REQ — CCP 현황 F11·A09, 개발 API fixtures/ccp (p11-s2-spec 6장 P11-TC-001~005c·031).

이름의 tcNNN은 P11-TC ID. 오늘은 2026-10-13(화)로 고정(documents.tests.p11.fixed_today).
"""

import json

from django.test import TestCase, override_settings

from apps.doc_requirements import ccp, errors, flows, periodic
from apps.documents import services as doc
from apps.documents.tests.p11 import (
    TODAY,
    add_rows,
    at,
    ccp_doc,
    deviation,
    fixed_today,
    r1p,
    r2b,
    r3p,
    set_status,
    setup_p11,
    summary,
)


class P11ReqTestCase(TestCase):
    def setUp(self):
        setup_p11()
        stack = fixed_today(TODAY, periodic)
        stack.__enter__()
        self.addCleanup(stack.__exit__, None, None, None)

    def card(self, out, code):
        return next(c for c in out["cards"] if c["type_code"] == code)


class CcpDashboardTests(P11ReqTestCase):
    def test_tc001_cards(self):
        ids = {(code, b): ccp_doc(code, b) for b in (12, 15) for code in ccp.ccp_types()}
        add_rows(ids[("CCP-1P", 12)], "rounds", [r1p("08:50", phase="작업시작 전"), r1p("09:50")])
        add_rows(ids[("CCP-2B", 12)], "rounds", [r2b("10:00", temp=73.5)])
        add_rows(ids[("CCP-1P", 15)], "rounds", [r1p("08:40"), r1p("09:40")])
        set_status(ids[("CCP-1P", 15)], "completed")
        out = ccp.ccp_dashboard(3, None)
        self.assertEqual(out["base_date"], TODAY)
        self.assertEqual([c["type_code"] for c in out["cards"]], ["CCP-1P", "CCP-2B", "CCP-3P"])
        c1, c2, c3 = out["cards"]
        self.assertEqual(c1["counts"], {"batches": 2, "todo": 1, "no_rows": 0, "deviation_rows": 0})
        self.assertEqual(c2["counts"], {"batches": 2, "todo": 2, "no_rows": 1, "deviation_rows": 1})
        self.assertEqual(c3["counts"], {"batches": 2, "todo": 2, "no_rows": 2, "deviation_rows": 0})
        self.assertEqual(c1["template_name"], "CCP-1P 모니터링일지(쇳가루 제거)")
        (bad,) = out["deviations"]
        self.assertEqual(
            (bad["type_code"], bad["at"], bad["label"]), ("CCP-2B", at("10:00"), "PB-12")
        )
        self.assertEqual(bad["reasons"][0]["expect"], {"min": 68.0, "max": 72.0})
        self.assertEqual((bad["deviation"], bad["doc_deviation_count"]), ({"state": "none"}, 0))
        latest = next(r for r in c1["rows"] if r["document_id"] == ids[("CCP-1P", 12)])["latest"]
        self.assertEqual((latest["at"], latest["verdict"]), (at("09:50"), "적합"))
        self.assertIn("generated_at", out)

    def test_tc002_row_order(self):
        deviating, empty, drafting, done = (ccp_doc("CCP-2B", b) for b in (17, 16, 15, 12))
        add_rows(deviating, "rounds", [r2b("10:00", temp=60.0)])
        add_rows(drafting, "rounds", [r2b("10:00")])
        add_rows(done, "rounds", [r2b("10:00")])
        set_status(done, "completed")
        rows = self.card(ccp.ccp_dashboard(3, TODAY), "CCP-2B")["rows"]
        self.assertEqual([r["document_id"] for r in rows], [deviating, empty, drafting, done])
        self.assertEqual([r["label"] for r in rows], ["PB-17", "PB-16", "PB-15", "PB-12"])

    def test_tc002_same_rank_by_label(self):
        b, a = ccp_doc("CCP-1P", 16), ccp_doc("CCP-1P", 12)
        rows = self.card(ccp.ccp_dashboard(3, TODAY), "CCP-1P")["rows"]
        self.assertEqual([r["document_id"] for r in rows], [a, b])

    def test_tc003_no_documents(self):
        out = ccp.ccp_dashboard(3, TODAY)
        self.assertEqual([len(c["rows"]) for c in out["cards"]], [0, 0, 0])
        self.assertEqual(out["deviations"], [])
        self.assertEqual(out["cards"][2]["template_name"], "CCP-3P 모니터링일지(금속검출)")

    def test_tc004_bad_date(self):
        for value in ("2026-10-14", "2026-13-01", "20261013"):
            with self.subTest(value=value), self.assertRaises(errors.InvalidFilter):
                ccp.ccp_dashboard(3, value)

    def test_tc005_deviation_states(self):
        document_id = ccp_doc("CCP-2B", 12)
        rows = add_rows(
            document_id,
            "rounds",
            [r2b(f"{h:02d}:00", temp=75.0) for h in range(8, 14)],
        )
        a, b, c, d, e, f = rows
        deviation(document_id, b)
        checked = deviation(document_id, c)
        doc.check_deviation(3, checked["deviation_id"], 1)
        deviation(document_id, d, checkers=())
        done = deviation(document_id, e)
        doc.check_deviation(3, done["deviation_id"], 1)
        deviation(document_id, e)
        done = deviation(document_id, f)
        doc.check_deviation(3, done["deviation_id"], 1)
        deviation(document_id, f, checkers=())
        out = ccp.ccp_dashboard(None, TODAY)
        states = [x["deviation"]["state"] for x in out["deviations"]]
        self.assertEqual(
            states, ["none", "pending", "checked", "no_checker", "pending", "no_checker"]
        )
        self.assertEqual(out["deviations"][2]["deviation"]["checked_by"], 3)
        self.assertEqual(out["deviations"][0]["doc_deviation_count"], 7)

    def test_tc005a_deviation_order(self):
        three = ccp_doc("CCP-3P", 12)
        two = ccp_doc("CCP-2B", 12)
        add_rows(two, "rounds", [r2b("13:50", temp=60.0), {"phase": "작업 중", "temp_c": 60.0}])
        add_rows(three, "summary", [summary(1)])
        add_rows(three, "checks", [r3p("10:00", fe_l="X")])
        out = ccp.ccp_dashboard(None, TODAY)
        order = [(x["type_code"], x["at"]) for x in out["deviations"]]
        self.assertEqual(
            order,
            [("CCP-3P", at("10:00")), ("CCP-2B", at("13:50")), ("CCP-3P", None), ("CCP-2B", None)],
        )

    def test_tc005c_detected_qty(self):
        three = ccp_doc("CCP-3P", 12)
        add_rows(three, "summary", [summary(2), summary(1)])
        (row,) = self.card(ccp.ccp_dashboard(3, TODAY), "CCP-3P")["rows"]
        self.assertEqual((row["detected_qty"], row["row_count"], row["no_rows"]), (3, 0, True))
        one = ccp_doc("CCP-1P", 12)
        (row,) = self.card(ccp.ccp_dashboard(3, TODAY), "CCP-1P")["rows"]
        self.assertEqual(row["document_id"], one)
        self.assertNotIn("detected_qty", row)

    def test_flow_trace(self):
        ccp_doc("CCP-1P", 12)
        from apps.documents.tests.p8 import captured

        with captured() as steps:
            ccp.ccp_dashboard(3, TODAY)
        self.assertTrue(flows.matches("REQ-CCP", ["REQ-CCP-01", *steps]), steps)
        self.assertIn("DOC-MSM-04", steps)


class CcpApiTests(P11ReqTestCase):
    def test_tc005b_header_optional(self):
        self.assertEqual(self.client.get("/api/v1/ccp-dashboard").status_code, 200)
        response = self.client.get("/api/v1/ccp-dashboard", HTTP_X_STAFF_ID="99")
        self.assertEqual((response.status_code, response.json()["code"]), (403, "INVALID_STAFF"))
        response = self.client.get("/api/v1/ccp-dashboard?date=2026-10-14", HTTP_X_STAFF_ID="3")
        self.assertEqual((response.status_code, response.json()["code"]), (400, "INVALID_FILTER"))
        body = self.client.get(f"/api/v1/ccp-dashboard?date={TODAY}", HTTP_X_STAFF_ID="3").json()
        self.assertEqual(len(body["cards"]), 3)


@override_settings(ROOT_URLCONF="apps.devtools.test_urls")
class CcpFixtureTests(P11ReqTestCase):
    url = "/api/dev/fixtures/ccp"

    def post(self, body):
        return self.client.post(self.url, json.dumps(body), content_type="application/json")

    def test_tc031_fixture(self):
        response = self.post(
            {
                "work_date": TODAY,
                "batches": 2,
                "rows": [
                    {"process": "2B", "batch": 1, "values": {"temp_c": 73.5}},
                    *({"process": "1P", "batch": n} for n in (1, 1, 2, 2)),
                ],
                "deviations": [{"process": "2B", "batch": 1, "row": 1, "checker_ids": [3]}],
                "status": {"CCP-1P": "completed"},
            }
        )
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(len(body["batches"]), 2)
        self.assertEqual(len(body["deviations"]), 1)
        out = ccp.ccp_dashboard(3, TODAY)
        (bad,) = out["deviations"]
        self.assertEqual(bad["deviation"]["state"], "pending")
        statuses = {r["status"] for r in self.card(out, "CCP-1P")["rows"]}
        self.assertEqual(statuses, {"completed"})
        pending = doc.pending_deviations(3, TODAY)
        self.assertEqual(pending["counts"], {"total": 1, "mine": 1})

    def test_fixture_bad_input(self):
        for body in (
            {"batches": 6},
            {"rows": [{"process": "9X"}]},
            {"work_date": "2099-01-01"},
            {"rows": [{"process": "2B", "values": "bad"}]},
            {"deviations": [{"process": "2B", "row": "1"}]},
            {"deviations": [{"process": "2B", "checker_ids": "3"}]},
            {"deviations": [{"process": "2B", "checked_by": "3"}]},
        ):
            with self.subTest(body=body):
                self.assertEqual(self.post(body).status_code, 400)
