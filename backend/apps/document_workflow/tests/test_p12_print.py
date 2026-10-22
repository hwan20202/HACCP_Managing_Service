"""P12 출력 S4 — CCP 단건 (p12-s2-spec 8장 TC 중 single, p12-ccp-policy.md DP-01~03)."""

import json

from django.conf import settings
from django.db import connection
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from apps.approvals import services as apr
from apps.document_workflow import flows, print_forms, printing
from apps.document_workflow import services as wf
from apps.documents import services as doc
from apps.documents.models import Document, DocumentTemplate
from apps.documents.tests.p4 import (
    DAY,
    at,
    complete,
    filled_ccp1p,
    new_ccp,
    new_d01,
    patch,
    rows_of,
    set_info,
    setup_p4,
    version_of,
)

OWNER, LEADER = 3, 5  # roles.json: CCP 담당자 {1, 3}, HACCP팀장 {1, 5}


def sql(statement, params):
    with connection.cursor() as cursor:
        cursor.execute(statement, params)


def submitted(document_id):
    return wf.submit(OWNER, document_id, version_of(document_id))["request"]


def slot_id(request, role):
    return next(s["approval_id"] for s in request["slots"] if s["role"] == role)


def approved_ccp1p():
    document_id = filled_ccp1p()
    complete(document_id)
    request = submitted(document_id)
    wf.decide(OWNER, slot_id(request, "owner"), "approved")
    wf.decide(LEADER, slot_id(request, "leader"), "approved")
    return document_id


class PrintTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        setup_p4()

    def sheet(self, document_id):
        return printing.print_sheet(document_id)

    def get(self, query, **headers):
        return self.client.get("/api/v1/print/sheet", query, **headers)


class SheetKindTests(PrintTestCase):
    def test_tc001_ccp_single_and_d01_not_printable(self):
        for code, process in (("CCP-1P", "1P"), ("CCP-2B", "2B"), ("CCP-3P", "3P")):
            document_id = new_ccp(code, process)["document"]["document_id"]
            self.assertEqual(printing.sheet_for_document(document_id)["kind"], "single")
        d01 = new_d01()["document"]["document_id"]
        with self.assertRaises(printing.NotPrintableType):
            printing.sheet_for_document(d01)

    def test_tc002_draft_rejected_not_printable(self):
        draft = filled_ccp1p()
        with self.assertRaises(printing.NotPrintableStatus):
            self.sheet(draft)
        document_id = filled_ccp1p()
        complete(document_id)
        request = submitted(document_id)
        wf.decide(LEADER, slot_id(request, "leader"), "rejected", "측정 누락")
        self.assertEqual(doc.get_document(document_id)["status"], "rejected")
        with self.assertRaises(printing.NotPrintableStatus):
            self.sheet(document_id)


class SingleSheetTests(PrintTestCase):
    def _assert_ccp1p_print_guide(self, version, expected, old_text):
        document_id = new_ccp(legacy=False)["document"]["document_id"]
        template = DocumentTemplate.objects.get(type_code="CCP-1P", version=version)
        Document.objects.filter(pk=document_id).update(template_id=template.pk)
        start, end = rows_of(document_id, "rounds")
        patch(
            document_id,
            {
                "update": [
                    {
                        "section_id": start["section_id"],
                        "values": {
                            "measured_at": at("08:50"),
                            "gauss": 10000,
                            "rod_cleaned": "O",
                        },
                    },
                    {
                        "section_id": end["section_id"],
                        "values": {
                            "measured_at": at("17:00"),
                            "gauss": 10000,
                            "rod_cleaned": "O",
                        },
                    },
                ]
            },
        )
        set_info(document_id, {"inspector": 4})
        complete(document_id)
        guide = self.sheet(document_id)["guide"][0]["rows"][0][1]
        self.assertIn(expected, guide)
        self.assertNotIn(old_text, guide)

    def test_ccp1p_v2_print_keeps_old_guide(self):
        self._assert_ccp1p_print_guide(2, "자력 10,000가우스 자석봉 8개 사용", "Φ42.7")

    def test_ccp1p_v3_print_has_new_guide(self):
        self._assert_ccp1p_print_guide(3, "자력 8,000가우스, Φ42.7", "자석봉 8개")

    def test_tc003_approved_values_boxes_and_people(self):
        document_id = approved_ccp1p()
        deviation = doc.create_deviation(
            4, document_id, {"description": "자력 9,800G", "actor_id": 2, "checker_ids": [5]}
        )
        sql(
            "UPDATE deviation_action SET checked_by = 5, checked_at = %s WHERE deviation_id = %s",
            ["2026-10-12 09:00:00", deviation["deviation_id"]],
        )
        data = self.sheet(document_id)
        self.assertEqual((data["kind"], data["type_code"]), ("single", "CCP-1P"))
        self.assertEqual(data["title"], "CCP-1P 모니터링일지")
        self.assertEqual(data["guide"], print_forms.GUIDES["CCP-1P"])  # 종이 문구(T1 a)
        self.assertEqual([b["label"] for b in data["boxes"]], ["담당자", "HACCP팀장"])
        self.assertEqual([b["staff_id"] for b in data["boxes"]], [OWNER, LEADER])
        self.assertTrue(all(b["date"] and len(b["date"]) == 10 for b in data["boxes"]))
        sheet = data["document"]
        phases = [r["values"]["phase"] for r in sheet["sections"]["rounds"]]
        self.assertEqual(phases, ["작업시작 전", "작업 중", "작업종료 후"])
        self.assertEqual(sheet["info"]["item_name"], "유자차")
        self.assertEqual(sheet["batch_label"], "PB-1011-01")
        self.assertIsNone(sheet["measured_until"])
        self.assertEqual(sheet["deviations"][0]["checked_by"], 5)
        self.assertEqual(sheet["deviations"][0]["checked_on"], "2026-10-12")
        self.assertEqual(data["people"]["5"], "개발직원5")
        self.assertIn("4", data["people"])  # 점검자
        self.assertIn("3", data["people"])  # 행 기록자(서명 칸 — T2 a)
        self.assertEqual(
            [f["key"] for f in sheet["fields"]["rounds"]][:3], ["phase", "measured_at", "gauss"]
        )

    def test_tc004_in_progress_and_completed_after_cancel(self):
        document_id = filled_ccp1p()
        complete(document_id)
        request = submitted(document_id)
        self.assertEqual([b["staff_id"] for b in self.sheet(document_id)["boxes"]], [None, None])
        wf.decide(OWNER, slot_id(request, "owner"), "approved")
        self.assertEqual([b["staff_id"] for b in self.sheet(document_id)["boxes"]], [OWNER, None])
        wf.cancel_submission(OWNER, request["request_id"])
        data = self.sheet(document_id)
        self.assertEqual(data["document"]["status"], "completed")
        self.assertEqual([b["staff_id"] for b in data["boxes"]], [None, None])  # 취소 회차 비움

    def test_tc005_correction_prints_approved_snapshot(self):
        document_id = approved_ccp1p()
        doc.start_correction(OWNER, document_id, version_of(document_id), "자력 값 오기")
        first = rows_of(document_id, "rounds")[0]
        patch(
            document_id,
            {"update": [{"section_id": first["section_id"], "values": {"gauss": 11111}}]},
        )
        doc.create_deviation(4, document_id, {"description": "정정 중 추가", "actor_id": 2})
        data = self.sheet(document_id)
        gauss = [r["values"]["gauss"] for r in data["document"]["sections"]["rounds"]]
        self.assertNotIn(11111, gauss)  # 승인본 값
        self.assertEqual([b["staff_id"] for b in data["boxes"]], [OWNER, LEADER])
        self.assertEqual(data["document"]["deviations"][-1]["description"], "정정 중 추가")
        self.assertNotIn("correction", json.dumps(data, ensure_ascii=False))  # 정정 표시 없음

    def test_tc006_correction_resubmitted_still_snapshot(self):
        document_id = approved_ccp1p()
        doc.start_correction(OWNER, document_id, version_of(document_id), "자력 값 오기")
        first = rows_of(document_id, "rounds")[0]
        patch(
            document_id,
            {"update": [{"section_id": first["section_id"], "values": {"gauss": 11111}}]},
        )
        complete(document_id)
        submitted(document_id)
        data = self.sheet(document_id)
        self.assertEqual(data["document"]["status"], "submitted")
        gauss = [r["values"]["gauss"] for r in data["document"]["sections"]["rounds"]]
        self.assertNotIn(11111, gauss)
        self.assertEqual([b["staff_id"] for b in data["boxes"]], [OWNER, LEADER])

    def test_ccp2b_measured_until(self):
        document_id = new_ccp("CCP-2B", "2B")["document"]["document_id"]
        rows = [
            {"phase": "건조시작 전", "measured_at": at("09:00"), "temp_c": 70, "dry_minutes": 120},
            {"phase": "건조종료 전", "measured_at": at("11:00", "2026-10-12"), "temp_c": 70,
             "dry_minutes": 120},
        ]  # fmt: skip
        patch(document_id, {"add": [{"section_def": "rounds", "values": v} for v in rows]})
        set_info(document_id, {"inspector": 4})
        complete(document_id)
        sheet = self.sheet(document_id)["document"]
        self.assertEqual((sheet["work_date"], sheet["measured_until"]), (DAY, "2026-10-12"))

    def test_ccp2b_v3_prints_end_only_elapsed(self):
        document_id = new_ccp("CCP-2B", "2B", legacy=False)["document"]["document_id"]
        start, end = rows_of(document_id, "rounds")
        patch(
            document_id,
            {
                "update": [
                    {
                        "section_id": start["section_id"],
                        "values": {"measured_at": at("23:00"), "temp_c": 70},
                    },
                    {
                        "section_id": end["section_id"],
                        "values": {"measured_at": at("01:00", "2026-10-12"), "temp_c": 70},
                    },
                ]
            },
        )
        set_info(document_id, {"inspector": 4})
        complete(document_id)
        data = self.sheet(document_id)
        rows = data["document"]["sections"]["rounds"]
        self.assertNotIn("dry_minutes", rows[0]["values"])
        self.assertEqual(rows[1]["values"]["dry_minutes"], 120)
        self.assertEqual(rows[1]["values"]["time_verdict"], "적합")
        self.assertEqual(data["template"]["version"], 3)
        self.assertIn("측정일시의 차이", data["guide"][0]["rows"][2][1])

    def test_ccp3p_v2_fields(self):
        document_id = new_ccp("CCP-3P", "3P")["document"]["document_id"]
        ok = {"fe_only": "○", "sts_only": "○", "product_only": "X"}
        ok.update(product_fe="○", product_sus="○")
        rows = [{"phase": "종료", "passed_at": at("17:00"), **ok},
                {"phase": "시작", "passed_at": at("08:40"), **ok}]  # fmt: skip
        patch(document_id, {"add": [{"section_def": "checks", "values": v} for v in rows]})
        summary = {"passed_qty": 10, "detected_qty": 0}
        patch(document_id, {"add": [{"section_def": "summary", "values": summary}]})
        set_info(document_id, {"inspector": 4})
        complete(document_id)
        data = self.sheet(document_id)
        self.assertEqual(data["title"], "중요관리점 CCP-3P 모니터링일지")
        self.assertEqual(data["guide"][1]["title"], "개선조치방법")  # 양식 v2 guide
        labels = [f["label"] for f in data["document"]["fields"]["checks"]]
        self.assertEqual(labels[2:4], ["Fe만 통과", "STS만 통과"])
        phases = [r["values"]["phase"] for r in data["document"]["sections"]["checks"]]
        self.assertEqual(phases, ["시작", "종료"])

    def test_tc019_no_writes(self):
        document_id = approved_ccp1p()
        before = doc.get_document(document_id)
        requests = apr.list_requests(document_id)
        self.sheet(document_id)
        after = doc.get_document(document_id)
        self.assertEqual(
            (before["version"], before["updated_at"]), (after["version"], after["updated_at"])
        )
        self.assertEqual(apr.list_requests(document_id), requests)


class BoxRuleTests(TestCase):
    BOXES = [("owner", "담당자"), ("leader", "HACCP팀장")]

    def slot(self, n, state="approved", role=None, who=None):
        return {"slot_no": n, "role": role, "approver_id": who or n, "state": state,
                "decided_at": f"2026-10-1{n}T09:00:00+09:00"}  # fmt: skip

    def test_tc014_old_request_first_and_last(self):
        three = {"slots": [self.slot(1), self.slot(2), self.slot(3)]}
        filled = printing.fill_boxes(self.BOXES, three)
        self.assertEqual([b["staff_id"] for b in filled], [1, 3])
        self.assertEqual(filled[1]["date"], "2026-10-13")
        one = {"slots": [self.slot(1)]}
        self.assertEqual([b["staff_id"] for b in printing.fill_boxes(self.BOXES, one)], [1, None])

    def test_role_request_by_role_and_only_approved(self):
        slots = [self.slot(1, "pending", "owner"), self.slot(2, "approved", "leader", 9)]
        filled = printing.fill_boxes(self.BOXES, {"slots": slots})
        self.assertEqual([b["staff_id"] for b in filled], [None, 9])
        self.assertEqual(printing.fill_boxes(self.BOXES, None)[0]["staff_id"], None)


class QueryCountTests(PrintTestCase):
    def test_tc016_n9_six_queries(self):
        ids = [approved_ccp1p(), new_ccp("CCP-2B", "2B")["document"]["document_id"]]
        doc.create_deviation(4, ids[0], {"description": "자력 미달", "actor_id": 2})
        with CaptureQueriesContext(connection) as queries:
            result = doc.documents_for_print(ids)
        self.assertEqual(len(queries), 6)  # 개선조치가 없으면 확인자 SQL이 빠져 5
        self.assertEqual(set(result), set(ids))
        self.assertFalse(result[ids[0]]["open_correction"])

    def test_tc017_a12_two_queries_latest_and_approved(self):
        document_id = approved_ccp1p()
        doc.start_correction(OWNER, document_id, version_of(document_id), "값 오기")
        complete(document_id)
        submitted(document_id)
        with CaptureQueriesContext(connection) as queries:
            info = apr.print_slots([document_id])[document_id]
        self.assertEqual(len(queries), 2)
        self.assertEqual((info["latest"]["attempt"], info["latest"]["status"]), (2, "in_progress"))
        self.assertEqual(info["approved"]["attempt"], 1)
        self.assertIn("sections", info["approved"]["snapshot"])


class ApiTests(PrintTestCase):
    def test_tc015_errors(self):
        draft = filled_ccp1p()
        d01 = new_d01()["document"]["document_id"]
        cases = [
            ({}, 400, "INVALID_FILTER"),
            ({"document_id": "x"}, 400, "INVALID_FILTER"),
            ({"document_id": 1, "kind": "weekly"}, 400, "INVALID_FILTER"),
            ({"document_id": 1, "date": DAY}, 400, "INVALID_FILTER"),
            ({"document_id": 99999}, 404, "DOCUMENT_NOT_FOUND"),
            ({"document_id": d01}, 400, "NOT_PRINTABLE_TYPE"),
            ({"document_id": draft}, 409, "NOT_PRINTABLE_STATUS"),
        ]
        for query, status, code in cases:
            with self.subTest(query=query):
                response = self.get(query)
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.json()["code"], code)

    def test_ok_without_staff_header(self):
        document_id = approved_ccp1p()
        response = self.get({"document_id": document_id, "kind": "single"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["key"], {"document_id": document_id})
        self.assertEqual(self.client.post("/api/v1/print/sheet").status_code, 405)


@override_settings(
    ROOT_URLCONF="apps.devtools.test_urls",
    MIDDLEWARE=[*settings.MIDDLEWARE, "apps.devtools.middleware.TraceMiddleware"],
)
class PrintTraceTests(PrintTestCase):
    """개발 콘솔 trace 단계가 흐름 WF-PRT(성공)·WF-PRT-NOT-PRINTABLE(409)과 같다."""

    def ids(self, response):
        return [s["step_id"] for s in response.json()["trace"]["steps"]]

    def test_flows(self):
        ok = self.get({"document_id": approved_ccp1p()})
        self.assertTrue(flows.matches("WF-PRT", self.ids(ok)), self.ids(ok))
        draft = self.get({"document_id": new_ccp("CCP-2B", "2B")["document"]["document_id"]})
        self.assertEqual(draft.status_code, 409)
        self.assertTrue(flows.matches("WF-PRT-NOT-PRINTABLE", self.ids(draft)), self.ids(draft))


class PrintPageTests(SimpleTestCase):
    def test_page_without_login_or_dev_settings(self):
        response = self.client.get("/print/", {"document_id": 1})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "print/print.js")
        self.assertContains(response, 'id="prtPrint"')
        self.assertEqual(self.client.post("/print/").status_code, 405)
