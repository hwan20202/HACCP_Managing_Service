"""P15 S6 r3(D-253) — R25: CCP 공정 행 ↔ 그 배치 CCP 일지(작성완료 이후 상태 + 같은 값).

R1 a 작성완료·결재 중·승인이면 통과(작성중·반려·정정 중·작성 안 함은 막음) · R2 a 상태 + 값
(1P·3P 판정, 2B 온도·시간) · R4 a 생산일지 작성완료 뒤 CCP 일지가 바뀌면 A01 `ccp_changed` ·
R5 a 작성완료 빠짐 목록(COMPLETION_INCOMPLETE details)에 함께.
"""

import json

from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.documents import services as doc
from apps.production_log import logbook

from .prodlog_base import TODAY, ProdLogTestCase, full_step, sql


class CcpMatchTests(ProdLogTestCase):
    def ccp_rows(self, kind, rows, status="completed"):
        """CCP 일지에 측정 행을 넣고 상태를 바꾼다(테스트 준비 — 양식 검사는 P4 테스트 몫)."""
        document_id = self.ccp_id(kind)
        section = logbook.CCP_SECTION[kind]
        sql(
            "DELETE FROM doc_section WHERE document_id=%s AND section_def=%s",
            [document_id, section],
        )
        for n, values in enumerate(rows, 1):
            sql(
                "INSERT INTO doc_section (document_id, section_def, row_no, values_json)"
                " VALUES (%s, %s, %s, %s)",
                [document_id, section, n, json.dumps(values, ensure_ascii=False)],
            )
        self.set_status(kind, status)
        return document_id

    def set_status(self, kind, status):
        done = status not in ("draft", "correcting", "skipped")
        sql(
            "UPDATE document SET status=%s, completed_at=%s, completed_by=%s WHERE document_id=%s",
            [status, TODAY if done else None, 1 if done else None, self.ccp_id(kind)],
        )

    def ready_all(self):
        self.ccp_rows("CCP-1P", [{"verdict": "적합"}, {"verdict": "적합"}])
        self.ccp_rows(
            "CCP-2B",
            [
                {"phase": "건조시작 전", "temp_c": 70.1},
                {"phase": "건조종료 전", "temp_c": 69.8, "dry_minutes": 120},
            ],
        )
        self.ccp_rows("CCP-3P", [{"verdict": "적합"}])

    def ccp_steps(self, **override):
        return [
            full_step("CCP-1P", self.builtin("CCP-1P"), **override.get("CCP-1P", {})),
            full_step(
                "CCP-2B",
                self.builtin("CCP-2B"),
                **{"temp": 69.8, "time_min": 120, **override.get("CCP-2B", {})},
            ),
            full_step("CCP-3P", self.builtin("CCP-3P"), **override.get("CCP-3P", {})),
        ]

    def codes(self, error):
        return {(e["path"].split(".")[-1], e["code"]) for e in error.details}

    def test_ccp_doc_draft_blocks_completion(self):
        self.ready_all()
        self.set_status("CCP-1P", "draft")
        self.add_steps(*self.ccp_steps())
        self.fill_info()
        error = self.assertDocError("COMPLETION_INCOMPLETE", self.complete)
        self.assertEqual(self.codes(error), {("kind", "ccp_not_completed")})
        self.assertIn("작성중", error.details[0]["message"])
        self.assertEqual(self.detail()["status"], "draft")

    def test_rejected_and_correcting_block_submitted_approved_pass(self):
        self.ready_all()
        self.add_steps(*self.ccp_steps())
        self.fill_info()
        for status in ("rejected", "correcting"):
            self.set_status("CCP-3P", status)
            error = self.assertDocError("COMPLETION_INCOMPLETE", self.complete)
            self.assertEqual(self.codes(error), {("kind", "ccp_not_completed")}, status)
        self.set_status("CCP-3P", "submitted")
        self.set_status("CCP-1P", "approved")
        self.complete()
        self.assertEqual(self.detail()["status"], "completed")

    def test_value_mismatch_blocks(self):
        self.ready_all()
        self.ccp_rows("CCP-1P", [{"verdict": "적합"}, {"verdict": "부적합"}])
        self.add_steps(*self.ccp_steps(**{"CCP-2B": {"time_min": 118}}))
        self.fill_info()
        error = self.assertDocError("COMPLETION_INCOMPLETE", self.complete)
        self.assertEqual(
            self.codes(error), {("verdict", "ccp_mismatch"), ("time_min", "ccp_mismatch")}
        )
        paths = {e["path"] for e in error.details}
        self.assertTrue(all(p.startswith("sections[steps#") for p in paths), paths)

    def test_ccp_without_value(self):
        self.ccp_rows("CCP-1P", [])
        self.add_steps(full_step("CCP-1P", self.builtin("CCP-1P")))
        self.fill_info()
        error = self.assertDocError("COMPLETION_INCOMPLETE", self.complete)
        self.assertEqual(self.codes(error), {("verdict", "ccp_no_value")})

    def test_match_passes_numbers_compare_as_numbers(self):
        self.ready_all()
        self.add_steps(*self.ccp_steps(**{"CCP-2B": {"time_min": 120.0}}))
        self.fill_info()
        self.complete()
        self.assertEqual(self.detail()["status"], "completed")

    def test_a01_ccp_check_and_changed_after_completion(self):
        self.ready_all()
        self.add_steps(*self.ccp_steps())
        self.fill_info()
        self.complete()
        out = logbook.linked_data(self.log_id)
        self.assertFalse(out["ccp_changed"])
        self.assertEqual(
            out["ccp_check"]["CCP-1P"],
            {"status": "completed", "ready": True, "values": {"verdict": "적합"}, "problems": []},
        )
        # 생산일지 작성완료 뒤 CCP 일지가 다시 작성중으로(정정·재개) → 바뀜(R4)
        self.set_status("CCP-2B", "draft")
        out = logbook.linked_data(self.log_id)
        self.assertTrue(out["ccp_changed"])
        self.assertEqual(out["ccp_check"]["CCP-2B"]["problems"], ["ccp_not_completed"])
        # 값이 바뀌어도
        self.ccp_rows("CCP-2B", [{"phase": "건조종료 전", "temp_c": 71, "dry_minutes": 120}])
        out = logbook.linked_data(self.log_id)
        self.assertEqual(out["ccp_check"]["CCP-2B"]["problems"], ["ccp_mismatch"])

    def test_a01_draft_log_reports_but_not_changed(self):
        self.add_steps(*self.ccp_steps())
        out = logbook.linked_data(self.log_id)
        self.assertFalse(out["ccp_changed"])
        self.assertEqual(out["ccp_check"]["CCP-1P"]["problems"], ["ccp_not_completed"])
        self.assertFalse(out["ccp_check"]["CCP-1P"]["ready"])

    def test_a01_sql_count_unchanged(self):
        """D-247 A01 ≤ 7 — CCP 일지 상태·값은 N19 대신 N20 한 SQL."""
        self.ready_all()
        self.add_steps(*self.ccp_steps())
        with CaptureQueriesContext(connection) as q:
            logbook.linked_data(self.log_id)
        self.assertLessEqual(len(q), 6, [x["sql"][:80] for x in q])

    def test_a04_source_status(self):
        self.ccp_rows("CCP-1P", [{"verdict": "적합"}], status="draft")
        out = logbook.ccp_values(self.log_id, "CCP-1P")
        self.assertEqual(
            (out["verdict"], out["source_status"], out["source_ready"]), ("적합", "draft", False)
        )

    def test_n20_one_sql_smallest_document(self):
        self.ready_all()
        with CaptureQueriesContext(connection) as q:
            out = doc.documents_by_batch_ref_with_sections(
                self.inv.batch_id, {"CCP-1P": "rounds", "CCP-3P": "checks"}
            )
        self.assertEqual(len(q), 1)
        self.assertEqual(set(out), {"CCP-1P", "CCP-3P"})
        self.assertEqual(out["CCP-1P"]["rows"], [{"verdict": "적합"}, {"verdict": "적합"}])
        self.assertEqual(out["CCP-1P"]["document_id"], self.ccp_id("CCP-1P"))
        with CaptureQueriesContext(connection) as q:
            self.assertEqual(doc.documents_by_batch_ref_with_sections(self.inv.batch_id, {}), {})
        self.assertEqual(len(q), 0)
