"""P12 출력 — D12 주 묶음(weekly) (p12-d12-policy.md DP-13).

D10과 같은 주 종이 + 요일 칸마다 그날 회차의 결재 칸과 공정명, 점검자 없음.
"""

from django.test import TestCase

from apps.document_workflow import printing
from apps.document_workflow import services as wf
from apps.documents import services as doc
from apps.documents.tests.p8 import MON, THU, TUE, WED, fill, periodic, setup_p8

SAT = "2026-10-17"


def version_of(document_id):
    return doc.get_document(document_id)["version"]


def make(day, state="approved", process="내포장", value="O", owner=3, leader=1):
    document_id = periodic("D12", day)["document_id"]
    if state == "empty":
        return document_id
    fill(document_id, value, 4, {"info": {"process_name": process}})
    if value == "X":
        doc.create_deviation(4, document_id, {"description": "비닐 조각", "action_result": "제거"})
    if state == "draft":
        return document_id
    doc.complete_document(3, document_id, version_of(document_id))
    if state == "completed":
        return document_id
    request = wf.submit(3, document_id, version_of(document_id))["request"]
    slots = {s["role"]: s["approval_id"] for s in request["slots"]}
    wf.decide(owner, slots["owner"], "approved")
    if state == "partial":
        return document_id
    wf.decide(leader, slots["leader"], "approved")
    return document_id


class D12SheetTests(TestCase):
    def setUp(self):
        setup_p8()

    def sheet(self, day=MON):
        return printing.print_by_query({"kind": "weekly", "type": "D12", "date": day})

    def test_day_approval_and_process(self):
        make(MON, process="내포장")
        make(TUE, "partial", process="외포장", owner=2)
        make(WED, "draft", process="세척")
        make(SAT, "completed", process="내포장")
        data = self.sheet(THU)
        self.assertEqual((data["kind"], data["type_code"]), ("weekly", "D12"))
        self.assertEqual(data["title"], "공정별 이물관리 점검표")
        self.assertEqual([d["weekday"] for d in data["days"]], list("월화수목금토"))
        self.assertEqual([b["label"] for b in data["boxes"]], ["담당자", "HACCP팀장"])
        mon, tue, wed, thu, _fri, sat = data["days"]
        self.assertEqual([b["staff_id"] for b in mon["approval"]], [3, 1])
        self.assertEqual([b["staff_id"] for b in tue["approval"]], [2, None])
        self.assertEqual([b["staff_id"] for b in sat["approval"]], [None, None])  # 작성완료
        self.assertEqual(
            [d.get("process_name") for d in data["days"]],
            ["내포장", "외포장", None, None, None, "내포장"],  # 출력 불가·없음 칸은 없음
        )
        self.assertNotIn("approval", wed)
        self.assertEqual(thu["state"], "missing")
        self.assertIsNone(data["inspector_id"])  # 점검자 출력 안 함(Q2 a)
        self.assertNotIn("4", data["people"])
        self.assertEqual(set(data["people"]), {"1", "2", "3"})
        self.assertEqual(data["latest_dates"], {})
        self.assertEqual(data["fields"][0]["group"], "원료 중의 이물혼입방지")

    def test_deviation_and_document_entry(self):
        bad = make(TUE, value="X")
        data = printing.print_sheet(bad)
        self.assertEqual(data["key"], {"type": "D12", "date": MON})
        self.assertEqual(
            [(d["document_id"], d["work_date"]) for d in data["deviations"]], [(bad, TUE)]
        )
        self.assertEqual(data["days"][1]["values"]["raw_vacuum"], "X")
