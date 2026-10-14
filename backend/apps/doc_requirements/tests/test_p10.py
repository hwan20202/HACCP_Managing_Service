"""P10 S4 작성 필요 목록 REQ-F10·A08·DOC-N7 (p10-s2-spec 6장 P10-TC-001~015).

이름의 tcNNN은 P10-TC ID. 오늘은 periodic._today를 바꿔 고정하고, 규칙 파일은 임시 파일.
상태는 문서 함수로 만들기 번거로운 것(결재중·반려·정정 중 등)을 SQL로 맞춘다 — 목록은 상태만 읽는다.
"""

import json

from django.db import connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.doc_requirements import errors, periodic, todo
from apps.documents import errors as doc_errors
from apps.documents import services as doc
from apps.documents.tests.p8 import FRI, MON, THU, TUE, WED, setup_p8
from apps.documents.tests.p8 import periodic as per

from .base import setup_req
from .test_p9 import RULES, RulesFileMixin, today

FIRST_MON = "2026-11-02"


def sql(statement, params=()):
    with connection.cursor() as cursor:
        cursor.execute(statement, params)


def set_status(document_id, status, **columns):
    done = status in ("completed", "submitted", "approved", "rejected")
    sets = {
        "status": status,
        "completed_at": "2026-10-13 00:00:00" if done else None,
        "completed_by": 3 if done else None,
        **columns,
    }
    sql(
        f"UPDATE document SET {', '.join(f'{k} = %s' for k in sets)} WHERE document_id = %s",
        [*sets.values(), document_id],
    )


def d03(lot_id, day, inspector=None):
    values = {"info": {"received_date": day}}
    if inspector:
        values["info"]["inspector"] = inspector
    with transaction.atomic():
        return doc.get_or_create_document(
            3,
            "D03",
            f"D03|lot:{lot_id}",
            day,
            [{"lot_id": lot_id, "label": f"L-{lot_id}"}],
            values=values,
        )["document"]["document_id"]


def ccp(batch_id, day, assignee=None):
    with transaction.atomic():
        return doc.get_or_create_document(
            3,
            "CCP-2B",
            f"CCP-2B|batch:{batch_id}",
            day,
            [{"production_batch_id": batch_id, "process_code": "2B", "label": f"PB-{batch_id}"}],
            assignee_id=assignee,
        )["document"]["document_id"]


def periodic_doc(code, day, inspector=None):
    values = {"info": {"inspector": inspector}} if inspector else None
    return per(code, day, values=values)["document_id"]


def group(out, key):
    return next(g for g in out["groups"] if g["key"] == key)


def brief(rows):
    return [(r["kind"], r["type_code"], r["work_date"]) for r in rows]


class TodoTestCase(RulesFileMixin, TestCase):
    def setUp(self):
        super().setUp()
        setup_req()
        setup_p8()

    def todo(self, base=None, mine=False, actor=3, now=None):
        with today(now or base or WED):
            return todo.todo_list(actor, base, mine)


class TodoTests(TodoTestCase):
    def test_tc001_groups(self):
        d10 = periodic_doc("D10", TUE)
        d03(88, TUE)
        set_status(d03(89, TUE), "completed")
        set_status(ccp(12, TUE), "rejected")
        d11 = periodic_doc("D11", MON)
        out = self.todo(TUE)
        keys = [g["key"] for g in out["groups"]]
        self.assertEqual(keys, ["today", "week", "month", "year", "adhoc"])
        rows = group(out, "today")["rows"]
        self.assertEqual(
            brief(rows),
            [
                ("document", "D10", TUE),
                ("missing", "D12", TUE),
                ("document", "D03", TUE),
                ("document", "CCP-2B", TUE),
            ],
        )
        self.assertEqual(rows[0]["document_id"], d10)
        self.assertEqual(rows[1]["record_key"], f"D12|day:{TUE}")
        self.assertEqual(rows[2]["bundle"], {"received_date": TUE, "count": 1})
        self.assertEqual(rows[2]["status"], "draft")
        self.assertEqual(rows[3]["status"], "rejected")
        self.assertEqual(rows[3]["requirement"], "batch")
        week = group(out, "week")
        self.assertEqual([r["document_id"] for r in week["rows"]], [d11])
        self.assertEqual(week["rows"][0]["week_start"], MON)
        for key in ("month", "year", "adhoc"):
            self.assertFalse(group(out, key)["has_forms"])
            self.assertEqual(group(out, key)["count"], 0)
        self.assertTrue(group(out, "today")["has_forms"])
        self.assertEqual(brief(out["awaiting_submit"]["rows"]), [("document", "D03", TUE)])
        # 어제(월) D10·D12 문서 없음은 지난 미완료
        self.assertEqual(
            sorted(brief(group(out, "today")["past"]["rows"])),
            [("missing", "D10", MON), ("missing", "D12", MON)],
        )
        self.assertEqual(out["counts"]["today"], 6)
        self.assertEqual(out["warnings"], [])

    def test_flow_steps(self):
        from apps.doc_requirements import flows
        from apps.documents.tests.p8 import captured

        with captured() as steps:
            self.todo(WED)
        self.assertTrue(flows.matches("REQ-TDO", ["REQ-TDO-01", *steps]), steps)
        self.assertIn("DOC-RQD-02", steps)

    def test_tc002_done_statuses(self):
        for day, status in ((MON, "completed"), (TUE, "submitted"), (WED, "approved")):
            set_status(periodic_doc("D10", day), status)
        skip = periodic_doc("D10", THU)
        doc.skip_documents(3, [{"document_id": skip, "expected_version": 1}], "휴무")
        out = self.todo(THU)
        d10 = [
            r
            for g in out["groups"]
            for r in g["rows"] + g["past"]["rows"]
            if r["type_code"] == "D10"
        ]
        self.assertEqual(d10, [])
        self.assertEqual(brief(out["awaiting_submit"]["rows"]), [("document", "D10", MON)])
        self.assertEqual(out["counts"]["today"], 4)  # D12 문서 없음 4개만(D10은 모두 빠짐)

    def test_tc003_past_and_older(self):
        self.write_rules(self.rule("D10", start_date="2026-09-01"))
        ten = periodic_doc("D10", "2026-11-01")
        periodic_doc("D10", "2026-10-11")  # 31일 전
        out = self.todo("2026-11-11")
        past = group(out, "today")["past"]
        self.assertIn(ten, [r.get("document_id") for r in past["rows"]])
        self.assertNotIn("2026-10-11", [r["work_date"] for r in past["rows"]])
        self.assertEqual(out["older"], {"count": 1, "before": "2026-10-12"})
        self.assertEqual((past["from"], past["to"]), ("2026-10-12", "2026-11-10"))

    def test_tc004_start_and_weekend(self):
        rules = [dict(r, start_date="2026-10-09") for r in RULES if r["type_code"] == "D10"]
        self.write_rules(rules)
        out = self.todo(WED)
        today_group = group(out, "today")
        self.assertEqual(brief(today_group["rows"]), [("missing", "D10", WED)])
        self.assertEqual(
            [r["work_date"] for r in today_group["past"]["rows"]],
            [TUE, MON, "2026-10-09"],
        )

    def test_tc005_mine(self):
        periodic_doc("D12", WED, inspector=3)
        mine_ccp = ccp(12, WED, assignee=3)
        d03(88, WED)  # 작성자만 staff 3
        periodic_doc("D10", WED, inspector=4)
        out = self.todo(WED, mine="1")
        rows = group(out, "today")["rows"]
        self.assertEqual(brief(rows), [("document", "D12", WED), ("document", "CCP-2B", WED)])
        self.assertEqual(rows[1]["document_id"], mine_ccp)
        self.assertTrue(out["mine"])
        all_rows = [r for g in out["groups"] for r in g["rows"] + g["past"]["rows"]]
        self.assertFalse([r for r in all_rows if r["kind"] == "missing"])

    def test_tc006_rules_invalid(self):
        periodic_doc("D10", WED)
        periodic_doc("D12", WED)
        periodic_doc("D11", MON)
        self.write_rules([], raw="{broken")
        out = self.todo(WED)
        self.assertEqual(out["warnings"], ["RULES_INVALID"])
        self.assertEqual(
            brief(group(out, "today")["rows"]),
            [("document", "D10", WED), ("document", "D12", WED)],
        )
        self.assertEqual(brief(group(out, "week")["rows"]), [("document", "D11", MON)])
        all_rows = [r for g in out["groups"] for r in g["rows"] + g["past"]["rows"]]
        self.assertFalse([r for r in all_rows if r["kind"] == "missing"])

    def test_tc007_invalid(self):
        for base in ("2026-10-15", "2026-10-1", "2026/10/14", "2026-W42-3"):
            with self.subTest(base=base), self.assertRaises(errors.InvalidFilter):
                self.todo(base, now=WED)
        with self.assertRaises(errors.InvalidFilter):
            self.todo(WED, mine="2")

    def test_tc008_tags(self):
        fri = periodic_doc("D10", FRI)
        out = self.todo(FRI)
        row = next(r for r in group(out, "today")["rows"] if r.get("document_id") == fri)
        self.assertEqual(row["tags"], ["주 항목"])
        tue = next(r for r in group(out, "today")["past"]["rows"] if r["work_date"] == TUE)
        self.assertEqual(tue["tags"], [])
        out = self.todo(FIRST_MON)
        first = next(r for r in group(out, "today")["rows"] if r["type_code"] == "D10")
        self.assertEqual((first["kind"], first["tags"]), ("missing", ["월 항목"]))
        d12 = next(r for r in group(out, "today")["rows"] if r["type_code"] == "D12")
        self.assertEqual(d12["tags"], [])

    def test_tc009_past_base(self):
        out = self.todo(WED, now="2026-10-21")
        self.assertEqual(out["base_date"], WED)
        self.assertEqual({r["work_date"] for r in group(out, "today")["rows"]}, {WED})
        self.assertEqual({r["week_start"] for r in group(out, "week")["rows"]}, {MON})

    def test_tc011_d03_bundle(self):
        draft = d03(88, WED)
        rejected = d03(89, WED, inspector=3)
        corr = d03(91, WED)
        set_status(rejected, "rejected")
        set_status(corr, "correcting")
        row = next(r for r in group(self.todo(WED), "today")["rows"] if r["type_code"] == "D03")
        self.assertEqual((row["status"], row["bundle"]["count"]), ("rejected", 3))
        self.assertEqual(row["document_id"], min(draft, rejected, corr))
        mine = group(self.todo(WED, mine=True), "today")["rows"]
        self.assertEqual([(r["type_code"], r["bundle"]["count"]) for r in mine], [("D03", 1)])
        self.assertEqual(mine[0]["status"], "rejected")

    def test_tc012_week_past(self):
        self.write_rules(self.rule("D11", start_date="2026-10-05"))
        last = periodic_doc("D11", MON)
        out = self.todo("2026-10-21")
        week = group(out, "week")
        self.assertEqual(brief(week["rows"]), [("missing", "D11", "2026-10-19")])
        self.assertEqual(
            brief(week["past"]["rows"]),
            [("document", "D11", MON), ("missing", "D11", "2026-10-05")],
        )
        self.assertEqual(week["past"]["rows"][0]["document_id"], last)
        self.assertEqual((week["past"]["from"], week["past"]["to"]), ("2026-09-21", MON))

    def test_g2_g14_window_not_monday(self):
        """검토 A5: 기준일 −30일이 월요일이 아닌 날.

        N7 앞쪽 며칠(그 주 월요일 ~ −31일)도 30일 넘음에 들어간다.

        기준일 10-16(금) → −30일 = 09-16(수), 그 주 월요일 09-14.
        """
        self.write_rules([dict(r, start_date="2026-09-01") for r in RULES])
        gap = periodic_doc("D10", "2026-09-15")  # N7 범위 안, 지난 미완료 범위 밖
        periodic_doc("D10", "2026-09-10")  # N7 범위 앞(older_count)
        edge = periodic_doc("D10", "2026-09-16")  # 지난 미완료 첫날
        periodic_doc("D11", "2026-09-14")  # 월요일이 −30일 앞인 주
        out = self.todo(FRI)
        self.assertEqual(out["older"], {"count": 3, "before": "2026-09-16"})
        past = group(out, "today")["past"]
        ids = [r.get("document_id") for r in past["rows"]]
        self.assertIn(edge, ids)
        self.assertNotIn(gap, ids)
        self.assertEqual((past["from"], past["to"]), ("2026-09-16", THU))
        week = group(out, "week")["past"]
        self.assertEqual((week["from"], week["to"]), ("2026-09-21", "2026-10-05"))
        self.assertNotIn("2026-09-14", [r["work_date"] for r in week["rows"]])
        self.assertEqual(week["rows"][-1]["work_date"], "2026-09-21")  # 문서 없음 첫 주

    def test_sunday_base(self):
        """검토 A5: 일요일 기준일.

        오늘 칸은 그날(규칙 대상 아님 → 문서 없음 없음), 주간은 그 주 월요일.
        """
        d11 = periodic_doc("D11", MON)
        out = self.todo("2026-10-18", now="2026-10-18")
        self.assertEqual(group(out, "today")["rows"], [])
        self.assertEqual([r["document_id"] for r in group(out, "week")["rows"]], [d11])
        past = group(out, "today")["past"]["rows"]
        self.assertEqual(
            sorted({r["work_date"] for r in past}), [MON, TUE, WED, THU, FRI]
        )  # 토·일은 문서 없음 안 생김

    def test_tc013_make_from_missing(self):
        out = self.todo(WED)
        line = next(r for r in group(out, "today")["past"]["rows"] if r["type_code"] == "D12")
        with today(WED):
            made = periodic.open_periodic_document(3, "D12", line["work_date"])
        self.assertEqual(made["result"], "created")
        again = self.todo(WED)
        row = next(
            r
            for r in group(again, "today")["past"]["rows"]
            if r["type_code"] == "D12" and r["work_date"] == line["work_date"]
        )
        self.assertEqual((row["kind"], row["status"]), ("document", "draft"))

    def test_tc015_badge_counts(self):
        self.write_rules([dict(r, enabled=False) for r in RULES])
        for day in (MON, TUE, WED):
            periodic_doc("D10", day)
        periodic_doc("D12", WED)
        periodic_doc("D11", MON)
        set_status(periodic_doc("D12", MON), "completed")
        set_status(periodic_doc("D12", TUE), "completed")
        periodic_doc("D10", "2026-09-01")  # 30일 넘음
        out = self.todo(WED)
        self.assertEqual(sum(out["counts"].values()), 5)
        self.assertEqual(out["awaiting_submit"]["count"], 2)
        self.assertEqual(out["older"]["count"], 1)


class RequirementDocumentsTests(TodoTestCase):
    def test_tc010_n7(self):
        with self.assertRaises(doc_errors.ValidationFailed):
            doc.requirement_documents("2026-09-01", "2026-11-02")  # 63일
        with self.assertRaises(doc_errors.ValidationFailed):
            doc.requirement_documents(WED, MON)
        periodic_doc("D10", FRI, inspector=4)
        lot = d03(88, WED)
        set_status(ccp(12, MON), "approved")
        periodic_doc("D10", "2026-09-30")  # 앞선 미완료
        with CaptureQueriesContext(connection) as queries:
            out = doc.requirement_documents(MON, FRI, ["D10", "D12"], count_older=True)
        self.assertLessEqual(len(queries), 5)
        rows = {r["type_code"]: r for r in out["rows"]}
        self.assertEqual(rows["CCP-2B"]["status"], "approved")
        self.assertEqual(rows["CCP-2B"]["target_summary"], "배치 PB-12 · 2B")
        self.assertEqual(rows["D10"]["inspector_id"], 4)
        self.assertEqual(rows["D10"]["tags"], ["주 항목"])
        self.assertEqual(rows["D10"]["requirement"], "periodic")
        self.assertEqual(rows["D03"]["document_id"], lot)
        self.assertEqual(rows["D03"]["received_date"], WED)
        self.assertEqual(rows["D03"]["requirement"], "lot")
        self.assertEqual(set(out["templates"]), {"D10", "D12"})
        month = {"label": "월 항목", "first_weekday_of_month": 1}
        self.assertIn(month, out["templates"]["D10"]["tag_rules"])
        self.assertEqual(out["templates"]["D12"]["tag_rules"], [])
        self.assertEqual(out["older_count"], 1)


class TodoApiTests(TodoTestCase):
    def get(self, query="", staff=3):
        headers = {} if staff is None else {"HTTP_X_STAFF_ID": str(staff)}
        with today(WED):
            return self.client.get(f"/api/v1/todo{query}", **headers)

    def test_tc014_api(self):
        ok = self.get("?date=" + WED + "&mine=0")
        self.assertEqual(ok.status_code, 200, ok.content)
        self.assertEqual(ok.json()["base_date"], WED)
        self.assertEqual(self.get().json()["base_date"], WED)  # date 없으면 오늘
        for query, staff, status, code in (
            ("", None, 400, "STAFF_HEADER_MISSING"),
            ("", 99, 403, "INVALID_STAFF"),
            ("?mine=2", 3, 400, "INVALID_FILTER"),
            ("?date=2026-10-15", 3, 400, "INVALID_FILTER"),
            ("?date=bad", 3, 400, "INVALID_FILTER"),
        ):
            with self.subTest(query=query, staff=staff):
                response = self.get(query, staff)
                self.assertEqual(response.status_code, status, response.content)
                self.assertEqual(json.loads(response.content)["code"], code)
