"""P8 S4 REQ-F06 주 묶음 조회 (p8-s2-spec 4.2, 7장 P8-TC-060·061).

주기 문서는 DOC 테스트 준비물(N1)로, 결재는 WF 공개 함수로 만든다(P7 REQ 테스트와 같음).
"""

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.doc_requirements import flows
from apps.document_workflow import services as wf
from apps.document_workflow.tests.base import invariant_violations
from apps.documents import services as doc
from apps.documents.tests.p8 import FRI, MON, TUE, WED, captured, fill, periodic, setup_p8


class PeriodicBundleTests(TestCase):
    def setUp(self):
        setup_p8()

    def tearDown(self):
        self.assertEqual(invariant_violations(), [])

    def get(self, type_code="D10", week_start=MON, staff=1):
        headers = {} if staff is None else {"HTTP_X_STAFF_ID": str(staff)}
        return self.client.get(
            f"/api/v1/periodic-bundles?type_code={type_code}&week_start={week_start}", **headers
        )

    def test_tc060_week(self):
        made = {day: periodic("D10", day) for day in (MON, TUE, WED, FRI)}  # 목요일 없음
        done = fill(made[MON]["document_id"], extra={"checks": {"d_proc_zone": "X"}})
        doc.create_deviation(3, done["document_id"], {"description": "구역 작업 겹침"})
        done = doc.complete_document(3, done["document_id"], done["version"])
        wf.submit(3, done["document_id"], done["version"])  # 1번 담당 staff 3
        doc.skip_documents(
            3, [{"document_id": made[WED]["document_id"], "expected_version": 1}], "휴무"
        )
        periodic("D12", TUE)  # 다른 양식은 안 나옴
        periodic("D10", "2026-10-17")  # 토요일 → weekend
        with captured() as steps, CaptureQueriesContext(connection) as ctx:
            response = self.get(staff=3)
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertLessEqual(len(ctx.captured_queries), 8)  # 사용자 1 + N10 1 + F26 3 + A10 2
        self.assertTrue(flows.matches("REQ-PWB", steps), steps)
        self.assertEqual((body["week_start"], body["week_end"]), (MON, FRI))
        days = body["days"]
        self.assertEqual([d["work_date"] for d in days], [MON, TUE, WED, "2026-10-15", FRI])
        self.assertIsNone(days[3]["document"])
        self.assertEqual(
            [d["document"]["status"] if d["document"] else None for d in days],
            ["submitted", "draft", "skipped", None, "draft"],
        )
        mon = days[0]["document"]
        self.assertEqual(mon["check_counts"], {"O": 13, "X": 1, "NA": 7, "blank": 0})
        self.assertTrue(mon["nonconforming"])  # 검토 A5: 점검표도 계산(X 있음)
        self.assertEqual(mon["progress"]["status"], "in_progress")
        self.assertTrue(mon["my_slots"])  # staff 3 = 1번 칸 후보
        self.assertEqual(days[1]["document"]["check_counts"]["blank"], 13)
        self.assertEqual([w["work_date"] for w in body["weekend"]], ["2026-10-17"])
        self.assertEqual(
            body["summary"],
            {
                "documents": 5,
                "status_counts": {"submitted": 1, "draft": 3, "skipped": 1},
                "correcting_count": 0,
                "my_pending": 1,
            },
        )
        # P14: 묶음 결재선 요약 — D10 담당자 칸 이름 "작성자"(DR-09)
        self.assertEqual(
            [(s["role"], s["label"], s["candidate_ids"]) for s in body["approval_line"]["slots"]],
            [("owner", "작성자", [2, 3]), ("leader", "HACCP팀장", [1, 5])],
        )
        # 다른 사람(역할 없음)에게는 내 칸 없음
        other = self.get(staff=4).json()
        self.assertEqual(other["days"][0]["document"]["my_slots"], [])

    def test_empty_week(self):
        body = self.get(week_start="2026-10-19").json()
        self.assertEqual([d["document"] for d in body["days"]], [None] * 5)
        self.assertEqual(body["summary"]["documents"], 0)

    def test_tc061_input(self):
        for type_code, week_start, path in (
            ("D10", TUE, "week_start"),
            ("D10", "2026-1-12", "week_start"),
            ("D10", "2026-02-30", "week_start"),
            ("D11", MON, "type_code"),
            ("D03", MON, "type_code"),
        ):
            response = self.get(type_code, week_start)
            self.assertEqual(response.status_code, 400, (type_code, week_start))
            body = response.json()
            self.assertEqual(body["code"], "VALIDATION_ERROR")
            self.assertEqual(body["details"][0]["path"], path)
        self.assertEqual(self.get(staff=None).status_code, 200)  # P14 r14: 헤더 선택(DR-24 Q7 b)
