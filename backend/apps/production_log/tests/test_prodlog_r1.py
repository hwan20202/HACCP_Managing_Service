"""S4b r1·r2 — 외부 리뷰 B1·A1(ISS-063)·A8·C3, 재검토 B1·B2·A2·C2 보강 테스트."""

from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.db import connection, transaction
from django.test import override_settings
from django.test.utils import CaptureQueriesContext

from apps.core.http import ApiError
from apps.doc_requirements import errors as req_errors
from apps.doc_requirements import services as req
from apps.document_workflow import services as wf
from apps.documents import services as doc
from apps.documents.models import DocumentTemplate
from apps.production_log import logbook, services

from .prodlog_base import TODAY, ProdLogTestCase, full_step, lines_unavailable, sql


def run(fn, *args):
    with transaction.atomic():
        return fn(*args)


def unavailable(name):
    return mock.patch.object(req, name, side_effect=req_errors.SourceUnavailable())


class CancelledWhileUnlinkedTests(ProdLogTestCase):
    """B1: 0009 연동이 실패해도 취소 배치는 막는다(상태는 v_doc_batch에서 따로)."""

    def template(self):
        return run(
            services.create_template,
            1,
            {"name": "효력환", "steps": [{"process_id": self.builtin("OUTER")}]},
        )["process_template_id"]

    def test_save_template_rows_complete_blocked(self):
        tid = self.template()
        self.inv.cancel()
        with unavailable("production_log_source"), lines_unavailable():
            self.assertDocError("PLG_BATCH_CANCELLED", self.add_steps, full_step("GEN", self.gen()))
            self.assertDocError(
                "PLG_BATCH_CANCELLED", run, logbook.template_rows, 1, self.log_id, tid, "replace"
            )
            self.assertDocError("PLG_BATCH_CANCELLED", self.complete)

    def test_reopen_blocked(self):
        self.add_steps(full_step("GEN", self.gen()))
        self.fill_info()
        self.complete()
        self.inv.cancel()
        with unavailable("production_log_source"), lines_unavailable():
            self.assertDocError("PLG_BATCH_CANCELLED", self.reopen)
        self.assertEqual(self.detail()["status"], "completed")

    def test_state_unreadable_blocks_writes(self):
        tid = self.template()
        self.add_steps(full_step("GEN", self.gen()))
        self.fill_info()
        with unavailable("production_batch_state"):
            self.assertDocError(
                "PLG_LINKED_UNAVAILABLE", self.add_steps, full_step("GEN", self.gen("건조2"))
            )
            self.assertDocError(
                "PLG_LINKED_UNAVAILABLE",
                run,
                logbook.template_rows,
                1,
                self.log_id,
                tid,
                "replace",
            )
            self.assertDocError("PLG_LINKED_UNAVAILABLE", self.complete)
        self.complete()
        with unavailable("production_batch_state"):
            self.assertDocError("PLG_LINKED_UNAVAILABLE", self.reopen)
        self.assertEqual(self.detail()["status"], "completed")

    def test_complete_lines_unavailable(self):
        self.add_steps(full_step("GEN", self.gen()))
        self.fill_info()
        with lines_unavailable():
            self.assertDocError("PLG_LINKED_UNAVAILABLE", self.complete)
        self.assertEqual(self.detail()["status"], "draft")


class UntouchedRowsTests(ProdLogTestCase):
    """N12 touched: 손대지 않은 행은 다시 읽지 않고, 작성완료 때 전부 다시 본다."""

    def spy(self):
        """check_rows를 감싸 행 touched와 확장 SQL 수를 모은다."""
        seen = {"rows": [], "sql": []}
        ext = doc._EXTENSIONS["PROD-LOG"]

        def check(document, rows_after):
            seen["rows"] = [(r["section_def"], r["touched"]) for r in rows_after]
            with CaptureQueriesContext(connection) as q:
                out = ext.check_rows(document, rows_after)
            seen["sql"].append(len(q))
            return out

        patched = doc.FormExtension(check, ext.completion_problems, ext.on_transition)
        return seen, mock.patch.dict(doc._EXTENSIONS, {"PROD-LOG": patched})

    def test_rows_after_touched_flag(self):
        self.add_steps(full_step("GEN", self.gen()))
        seen, patch = self.spy()
        with patch:
            self.fill_info()
        self.assertEqual(sorted(seen["rows"]), [("info", True), ("steps", False)])

    def test_untouched_ccp_row_rechecked_at_completion(self):
        self.add_steps(full_step("CCP-1P", self.builtin("CCP-1P")))
        sql(
            "UPDATE document SET deleted_at=%s, deleted_by=1 WHERE document_id=%s",
            [TODAY, self.ccp_id("CCP-1P")],
        )
        self.fill_info()  # 손대지 않은 CCP 행 — 저장은 통과
        error = self.assertDocError("COMPLETION_INCOMPLETE", self.complete)
        self.assertIn("ccp_doc_missing", {e["code"] for e in error.details})

    def test_save_sql_counts(self):
        """ISS-063(PLG-NFR-04): 저장 확장 SQL — 정보만 1, 원료 1(상태와 같은 SQL), CCP 공정 3,
        CCP 공정 + 원료 한 번에 3(r2 A2 — 스펙 +3 이하)."""
        line = self.inv.lines[102]
        self.patch({"add": [{"section_def": "materials", "values": {"bom_line_id": line}}]})
        self.add_steps(full_step("GEN", self.gen()))
        seen, patch = self.spy()
        with patch:
            self.fill_info()
            material = next(
                r["section_id"]
                for r in self.detail()["sections"]
                if r["section_def"] == "materials"
            )
            self.patch({"update": [{"section_id": material, "values": {"used": 1}}]})
            self.add_steps(full_step("CCP-1P", self.builtin("CCP-1P")))
            self.patch(
                {
                    "update": [{"section_id": material, "values": {"used": 2}}],
                    "add": [
                        {
                            "section_def": "steps",
                            "values": full_step("CCP-3P", self.builtin("CCP-3P")),
                        }
                    ],
                }
            )
        self.assertEqual(seen["sql"], [1, 1, 3, 3])


class TemplateOverwriteTests(ProdLogTestCase):
    def test_name_taken_has_version(self):
        run(
            services.create_template,
            1,
            {"name": "효력환", "steps": [{"process_id": self.builtin("OUTER")}]},
        )
        error = self.assertDocError(
            "PLG_NAME_TAKEN",
            run,
            logbook.save_template_from_rows,
            1,
            self.log_id,
            {"name": "효력환", "steps": []},
        )
        self.assertEqual(error.details[0]["version"], 1)


class ProdLogNotBatchSubmittableTests(ProdLogTestCase):
    def items(self):
        return [{"document_id": self.log_id, "expected_version": self.detail()["version"]}]

    def test_batch_submit_rejects_prod_log(self):
        """기본 설정: 생산일지는 일괄 처리 양식이 아님 → 요청 전체 400(WF-BSB-04)."""
        try:
            run(wf.batch_submit, 1, self.items())
        except ApiError as error:
            self.assertEqual((error.status, error.code), (400, "INVALID_REQUEST"))
            self.assertEqual(error.details[0]["code"], "not_batchable")
        else:
            self.fail("일괄 상신이 거부돼야 합니다")
        self.assertEqual(self.detail()["status"], "draft")

    @override_settings(HACCP_BATCH_TYPES=["D03", "PROD-LOG"])
    def test_batch_submit_item_fails_when_batchable(self):
        """일괄 양식에 넣어도 그 항목만 409 NO_APPROVAL_FORM(WF-SUB-02b)."""
        out = run(wf.batch_submit, 1, self.items())
        self.assertEqual((out["succeeded"], out["failed"]), (0, 1))
        self.assertEqual(out["results"][0]["error"]["code"], "NO_APPROVAL_FORM")
        self.assertEqual(self.detail()["status"], "draft")


class InstallCommandTests(ProdLogTestCase):
    install_prod_log = False

    def test_production_log_option(self):
        out = StringIO()
        call_command("install_document_templates", stdout=out)
        self.assertFalse(DocumentTemplate.objects.filter(type_code="PROD-LOG").exists())
        call_command("install_document_templates", "--production-log", stdout=out)
        self.assertTrue(DocumentTemplate.objects.filter(type_code="PROD-LOG").exists())
        self.assertIn("PROD-LOG", out.getvalue())


class ReviewR2Tests(ProdLogTestCase):
    def test_a01_sql_with_last_template(self):
        """재검토 B1: 같은 품목 최근 템플릿이 있어도 A01 ≤ 7(D-247)."""
        tid = run(
            services.create_template,
            1,
            {"name": "효력환", "steps": [{"process_id": self.builtin("OUTER")}]},
        )["process_template_id"]
        self.patch(
            {"update": [{"section_id": self.section_id("info"), "values": {"template_id": tid}}]}
        )
        with CaptureQueriesContext(connection) as q:
            out = logbook.linked_data(self.log_id)
        self.assertEqual(out["last_template"]["process_template_id"], tid)
        self.assertLessEqual(len(q), 7, [x["sql"][:80] for x in q])

    def test_ccp_doc_found_by_batch_ref(self):
        """재검토 B2: 키 모양과 상관없이 배치 참조로 연결된 CCP 일지를 찾는다."""
        sql(
            "UPDATE document SET deleted_at=%s, deleted_by=1 WHERE document_id=%s",
            [TODAY, self.ccp_id("CCP-1P")],
        )
        with transaction.atomic():
            legacy = doc.get_or_create_document(
                1,
                "CCP-1P",
                f"CCP-1P|legacy:{self.inv.batch_id}",
                TODAY,
                [{"production_batch_id": self.inv.batch_id, "process_code": "1P"}],
            )["document"]["document_id"]
        self.assertEqual(logbook.linked_data(self.log_id)["ccp_documents"]["CCP-1P"], legacy)
        self.assertEqual(logbook.ccp_values(self.log_id, "CCP-1P")["source_document_id"], legacy)
        self.add_steps(full_step("CCP-1P", self.builtin("CCP-1P")))  # 저장 통과(R04)

    def test_n18_one_sql_and_values(self):
        with CaptureQueriesContext(connection) as q:
            out = doc.document_sections(self.log_id, ("info", "steps"))
        self.assertEqual(len(q), 1)
        self.assertEqual(out["type_code"], "PROD-LOG")
        self.assertEqual(out["work_date"], TODAY)
        self.assertEqual(len(out["sections"]["info"]), 1)
        self.assertEqual(out["sections"]["steps"], [])
        self.assertIsNone(out["refs"])
        with CaptureQueriesContext(connection) as q:
            head = doc.document_sections(self.log_id, ())
        self.assertEqual((len(q), head["sections"]), (1, {}))
        self.assertIsNotNone(doc.document_sections(self.log_id, (), with_refs=True)["refs"])

    def test_n18_rows_order_and_deleted(self):
        """재검토 r2 C1: 여러 행·섹션 안 순서·고른 섹션만, 삭제 문서 404."""
        gen = self.gen()
        self.add_steps(full_step("GEN", gen, name="a"), full_step("GEN", gen, name="b"))
        out = doc.document_sections(self.log_id, ("steps", "steps", "materials"))
        self.assertEqual([r["values"]["name"] for r in out["sections"]["steps"]], ["a", "b"])
        self.assertEqual([r["row_no"] for r in out["sections"]["steps"]], [1, 2])
        self.assertEqual(set(out["sections"]), {"steps", "materials"})
        sql(
            "UPDATE document SET deleted_at=%s, deleted_by=1 WHERE document_id=%s",
            [TODAY, self.log_id],
        )
        self.assertDocError("DOCUMENT_NOT_FOUND", doc.document_sections, self.log_id, ())

    def test_real_bom_view_missing(self):
        """재검토 r2 C1: BOM 줄 뷰를 실제로 없애면 저장은 ③④만 건너뛰고 작성완료는 409."""
        self.add_steps(full_step("GEN", self.gen()))
        self.fill_info()
        sql("DROP VIEW v_doc_batch_bom_line")  # 테스트 트랜잭션 안 — 끝나면 되돌림
        line = self.inv.lines[102]
        self.patch({"add": [{"section_def": "materials", "values": {"bom_line_id": line}}]})
        self.assertDocError("PLG_LINKED_UNAVAILABLE", self.complete)
        self.assertEqual(self.detail()["status"], "draft")
