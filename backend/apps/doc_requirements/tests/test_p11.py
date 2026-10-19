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


class CcpBatchAreaTests(P11ReqTestCase):
    """P11 S5 r1(D-167): 배치 영역 — 개선조치 내용·다른 개선조치·특이사항(p11-s5-r1-lines 3장)."""

    def test_tc032_action_content(self):
        d = ccp_doc("CCP-2B", 12)
        (row,) = add_rows(d, "rounds", [r2b("10:00", temp=73.5)])
        made = doc.create_deviation(
            4,
            d,
            {
                "section_id": row,
                "description": "온도 초과",
                "action_result": "재건조",
                "actor_id": 2,
                "checker_ids": [3],
            },
        )
        (bad,) = ccp.ccp_dashboard(3, TODAY)["deviations"]
        dv = bad["deviation"]
        self.assertEqual(dv["state"], "pending")
        self.assertEqual(
            (
                dv["deviation_id"],
                dv["version"],
                dv["description"],
                dv["action_result"],
                dv["actor_id"],
            ),
            (made["deviation_id"], made["version"], "온도 초과", "재건조", 2),
        )

    def test_tc033_other_deviations(self):
        d = ccp_doc("CCP-1P", 12)
        ok_row, bad_row = add_rows(d, "rounds", [r1p("09:00"), r1p("10:00", gauss=9000)])
        on_bad = deviation(d, bad_row)
        whole = deviation(d, None, checkers=())
        on_ok = deviation(d, ok_row)
        out = ccp.ccp_dashboard(3, TODAY)
        self.assertEqual(
            [x["deviation"]["deviation_id"] for x in out["deviations"]], [on_bad["deviation_id"]]
        )
        others = out["other_deviations"]
        self.assertEqual(
            [
                (x["deviation"]["deviation_id"], x["section_id"], x["deviation"]["state"])
                for x in others
            ],
            [
                (whole["deviation_id"], None, "no_checker"),
                (on_ok["deviation_id"], ok_row, "pending"),
            ],
        )
        self.assertEqual({x["label"] for x in others}, {"PB-12"})
        self.assertEqual(others[0]["deviation"]["description"], "이탈")

    def test_tc034_notes(self):
        d1, d3 = ccp_doc("CCP-1P", 12), ccp_doc("CCP-3P", 12)
        add_rows(
            d1,
            "rounds",
            [
                {**r1p("10:00"), "note": " 자석봉 교체 "},
                r1p("09:00"),
                {**r1p("11:00"), "note": "  "},
            ],
        )
        add_rows(d3, "checks", [{**r3p("09:30"), "note": "제품 변경"}])
        add_rows(d3, "summary", [{**summary(0), "note": "재점검"}])
        notes = ccp.ccp_dashboard(3, TODAY)["notes"]
        self.assertEqual(
            [(n["type_code"], n["section_def"], n["at"], n["text"]) for n in notes],
            [
                ("CCP-3P", "checks", at("09:30"), "제품 변경"),
                ("CCP-1P", "rounds", at("10:00"), "자석봉 교체"),
                ("CCP-3P", "summary", None, "재점검"),
            ],
        )
        self.assertEqual((notes[0]["field_label"], notes[2]["field_label"]), ("비고", "특이사항"))
        self.assertEqual(notes[2]["section_label"], "제품 통과 요약")
        self.assertEqual(notes[1]["label"], "PB-12")


class CcpProcessOrderTests(P11ReqTestCase):
    """P11 S5 r1(D-168): 배치마다 적용 CCP 공정과 순서 — 규칙 상수(품목 예외 → 공정 유형 기본)."""

    def test_tc035_default_order(self):
        for code in ("CCP-3P", "CCP-1P", "CCP-2B"):
            ccp_doc(code, 12)
        (b,) = ccp.ccp_dashboard(3, TODAY)["batches"]
        self.assertEqual((b["label"], b["batch_id"], b["item_id"]), ("PB-12", 12, 2))
        self.assertEqual(b["processes"], ["CCP-1P", "CCP-2B", "CCP-3P"])

    def test_tc035_item_exception_order(self):
        from unittest import mock

        ccp_doc("CCP-1P", 15)
        ccp_doc("CCP-2B", 15)
        with mock.patch.dict(ccp.rules.CCP_BY_ITEM, {2: ["2B", "1P"]}):
            (b,) = ccp.ccp_dashboard(3, TODAY)["batches"]
        self.assertEqual(b["processes"], ["CCP-2B", "CCP-1P"])


class CcpBatchStatusTests(P11ReqTestCase):
    """D-171: 배치 생산 상태·시작/종료 일시(화면 정렬용)."""

    def test_tc036_batch_status(self):
        from django.db import connection

        with connection.cursor() as c:
            c.execute(
                "UPDATE production_batches SET status = 'COMPLETED', started_at = %s,"
                " completed_at = %s, manufactured_date = %s WHERE id = 15",
                ["2026-10-13 08:10:00", "2026-10-13 15:00:00", TODAY],
            )
        ccp_doc("CCP-1P", 12)
        ccp_doc("CCP-1P", 15)
        out = {b["batch_id"]: b for b in ccp.ccp_dashboard(3, TODAY)["batches"]}
        self.assertEqual((out[12]["status"], out[12]["started_at"]), ("IN_PROGRESS", None))
        self.assertEqual(out[15]["status"], "COMPLETED")
        self.assertTrue(str(out[15]["started_at"]).startswith("2026-10-13"))
        self.assertTrue(str(out[15]["completed_at"]).startswith("2026-10-13"))

    def test_tc037_batch_quantity(self):
        from django.db import connection

        with connection.cursor() as c:
            c.execute(
                "UPDATE production_batches SET planned_quantity_e6 = 1200000000 WHERE id = 12"
            )
        ccp_doc("CCP-1P", 12)
        (b,) = ccp.ccp_dashboard(3, TODAY)["batches"]
        self.assertEqual((b["planned_qty"], b["output_qty"]), (1200.0, 0))
        self.assertIn("unit", b)


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
