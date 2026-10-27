"""P15 S7(D-255) — 생산일지 출력(WF `print_sheet` kind `prodlog`, p15-s7-print.md).

작성완료만 · 기본정보·원료는 작성완료 때 고정한 값 · 원료 작업자·비고는 원료 입력 행에서 ·
공정은 일지 순서, CCP 줄은 CCP 공정만 · 결재 칸 없음 · 출력은 쓰기 없음.
"""

import json

from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext

from apps.core import trace
from apps.document_workflow import flows as wf_flows
from apps.document_workflow import printing

from .prodlog_base import ProdLogTestCase, full_step
from .test_prodlog_r25 import CcpFixtures


class ProdLogPrintTests(CcpFixtures, ProdLogTestCase):
    def completed_log(self):
        self.ready_all()
        line = self.inv.lines[102]  # 정제수(재고 비관리) — 사용량 직접 입력
        self.patch(
            {
                "add": [
                    {
                        "section_def": "materials",
                        "values": {
                            "bom_line_id": line,
                            "worker": 2,
                            "note": "직접 계량",
                            "used": 88,
                        },
                    }
                ]
            }
        )
        self.inv.use(103, 9_000_000, line=self.inv.lines[103])
        gen = self.gen("분쇄", description="곱게 분쇄한다.")
        self.add_steps(
            full_step("GEN", gen, name="분쇄", desc="곱게 분쇄한다."),
            *self.ccp_steps(),
            full_step("OUTER", self.builtin("OUTER"), remark="특이 없음", fg_unit="box"),
        )
        self.fill_info()
        self.complete()

    def test_draft_not_printable(self):
        from apps.core.http import ApiError

        with self.assertRaises(ApiError) as caught:
            printing.print_sheet(self.log_id)
        self.assertEqual(caught.exception.code, "NOT_PRINTABLE_STATUS")

    def test_sheet_values(self):
        self.completed_log()
        version = self.detail()["version"]
        data = printing.print_sheet(self.log_id)
        self.assertEqual((data["kind"], data["boxes"], data["printable_count"]), ("prodlog", [], 1))
        self.assertEqual(data["title"], "[ 한동 효력환 ] 생산일지")
        d = data["document"]
        self.assertEqual(d["batch"]["product"], "[기타가공품] 한동 효력환")
        self.assertEqual(d["batch"]["planned"], "100 kg")
        self.assertEqual([m["line_no"] for m in d["materials"]], [1, 2, 3, 4])
        water = next(m for m in d["materials"] if m["bom_line_id"] == self.inv.lines[102])
        self.assertEqual((water["worker"], water["note"]), (2, "직접 계량"))
        self.assertEqual(d["materials"][0]["used_e6"], 9_000_000)
        self.assertEqual(
            [s["kind"] for s in d["steps"]], ["GEN", "CCP-1P", "CCP-2B", "CCP-3P", "OUTER"]
        )
        self.assertNotIn("done", d["steps"][0])
        self.assertEqual(d["ccp_line"], ["CCP-1P", "CCP-2B", "CCP-3P"])  # full_step 이름 = kind
        self.assertEqual(d["info"]["inspector"], 1)
        self.assertEqual(data["prechecks"][0], ["pre_label", "1. 원료의 적합라벨 확인"])
        self.assertTrue({"1", "2"} <= set(data["people"]))
        self.assertEqual(self.detail()["version"], version)  # 출력은 쓰기 없음

    def test_frozen_values_not_live(self):
        """Q3 a: 작성완료 뒤 투입이 늘어도 출력은 고정 값."""
        self.completed_log()
        self.inv.use(103, 1_000_000, line=self.inv.lines[103])
        data = printing.print_sheet(self.log_id)
        self.assertEqual(data["document"]["materials"][0]["used_e6"], 9_000_000)

    def test_no_ccp_line_empty(self):
        gen = self.gen("분쇄")
        self.add_steps(full_step("GEN", gen), full_step("OUTER", self.builtin("OUTER")))
        self.fill_info()
        self.complete()
        self.assertEqual(printing.print_sheet(self.log_id)["document"]["ccp_line"], [])

    def test_product_name(self):
        self.assertEqual(printing._product_name("[기타가공품] 효력환"), "효력환")
        self.assertEqual(printing._product_name("효력환"), "효력환")
        self.assertEqual(printing._product_name(None), "")

    def test_flow_and_queries(self):
        self.completed_log()
        record, token = trace.start("TEST", "print")
        try:
            with CaptureQueriesContext(connection) as q:
                printing.print_sheet(self.log_id)
        finally:
            trace.stop(token)
        ids = [s.step_id for s in record.steps if not s.step_id.startswith("ROLE-CFG")]
        self.assertEqual(ids, wf_flows.FLOWS["WF-PRT-PLG"][1:])  # API 단계(00) 빼고
        self.assertLessEqual(len(q), 9, [x["sql"][:80] for x in q])

    @override_settings(ROOT_URLCONF="config.urls")
    def test_api(self):
        self.completed_log()
        r = self.client.get(f"/api/v1/print/sheet?document_id={self.log_id}")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(json.loads(r.content)["kind"], "prodlog")
