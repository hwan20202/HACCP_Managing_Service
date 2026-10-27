"""PLG-TC-10~26·28 (p15-s2-spec.md 7장) — 생산일지 문서(S4b)."""

from unittest import mock

from django.db import connection, transaction
from django.test.utils import CaptureQueriesContext

from apps.doc_requirements import ccp as req_ccp
from apps.doc_requirements import errors as req_errors
from apps.doc_requirements import services as req
from apps.doc_requirements import todo as req_todo
from apps.document_workflow import services as wf
from apps.documents import services as doc
from apps.production_log import logbook, services
from apps.production_log.models import MasterChangeLog, ProcessTemplate
from apps.staff import roles

from .prodlog_base import TODAY, ProdLogTestCase, full_step, lines_unavailable, sql


def run(fn, *args):
    with transaction.atomic():
        return fn(*args)


class CreateAndShapeTests(ProdLogTestCase):
    def test_tc10_created_once_with_item_ref(self):
        kinds = [d["type_code"] for d in self.started["documents"]]
        self.assertEqual(kinds, ["CCP-1P", "CCP-2B", "CCP-3P", "PROD-LOG"])
        d = self.detail()
        self.assertEqual(d["record_key"], "PROD-LOG|batch:400")
        self.assertEqual(d["status"], "draft")
        ref = d["refs"][0]
        self.assertEqual((ref["production_batch_id"], ref["item_id"]), (400, 100))
        self.assertEqual(ref["label"], "PB-400 · 한동 효력환")
        self.assertEqual(d["target_summary"], "배치 PB-400 · 한동 효력환")
        sections = sorted(r["section_def"] for r in d["sections"])
        self.assertEqual(sections, ["info"])  # 공정 없음, 시스템 섹션 없음
        again = run(req.require_for_batch, 1, 400)
        self.assertEqual([d["result"] for d in again["documents"]], ["existing"] * 4)

    def test_tc11_no_approval(self):
        self.add_steps(full_step("GEN", self.gen()))
        self.fill_info()
        self.complete()
        d = self.detail()
        self.assertDocError("NO_APPROVAL_FORM", wf.submit, 1, self.log_id, d["version"])
        self.assertEqual(roles.approval_line("PROD-LOG")["reason"], "no_approval")
        self.assertFalse(doc.document_roles(d, 1)["permissions"]["submit"])
        self.assertTrue(doc.document_roles(d, 1)["permissions"]["write"])

    def test_tc23_docs_for_batch_prod_log_first(self):
        out = req.docs_for_batch(400)
        self.assertEqual(out["documents"][0]["type_code"], "PROD-LOG")
        self.assertIsNone(out["documents"][0]["process_code"])
        self.assertEqual([d["process_code"] for d in out["documents"][1:]], ["1P", "2B", "3P"])


class NotInstalledTests(ProdLogTestCase):
    install_prod_log = False

    def test_tc10_skipped_without_template(self):
        self.assertIsNone(self.log_id)
        self.assertEqual(
            [d["process_code"] for d in req.docs_for_batch(400)["documents"]], ["1P", "2B", "3P"]
        )


class SaveCheckTests(ProdLogTestCase):
    def test_tc14_step_checks(self):
        gen = self.gen()
        error = self.assertDocError(
            "VALIDATION_ERROR",
            self.add_steps,
            full_step("INNER", self.builtin("INNER")),
            full_step("INNER", self.builtin("INNER")),
        )
        self.assertEqual(error.details[0]["code"], "duplicate_builtin")
        error = self.assertDocError("VALIDATION_ERROR", self.add_steps, full_step("INNER", gen))
        self.assertEqual(error.details[0]["code"], "process_mismatch")
        error = self.assertDocError("VALIDATION_ERROR", self.add_steps, full_step("OUTER", None))
        self.assertEqual(error.details[0]["code"], "process_mismatch")
        # CCP 일지가 없으면 CCP 행 불가(R04) — CCP-2B 일지를 지움(삭제 표시)
        sql(
            "UPDATE document SET deleted_at=%s, deleted_by=1 WHERE document_id=%s",
            [TODAY, self.ccp_id("CCP-2B")],
        )
        error = self.assertDocError(
            "VALIDATION_ERROR", self.add_steps, full_step("CCP-2B", self.builtin("CCP-2B"))
        )
        self.assertEqual(error.details[0]["code"], "ccp_doc_missing")
        self.add_steps(
            full_step("CCP-1P", self.builtin("CCP-1P")),
            {"kind": "GEN", "name": "직접 입력", "mode": "QTY"},
        )

    def test_tc16_done_computed_and_system_field(self):
        self.add_steps(full_step("GEN", self.gen()), {"kind": "GEN", "name": "반쯤", "mode": "QTY"})
        rows = [r for r in self.detail()["sections"] if r["section_def"] == "steps"]
        self.assertEqual([r["values"]["done"] for r in rows], [True, False])
        self.patch(
            {
                "update": [
                    {
                        "section_id": rows[1]["section_id"],
                        "values": {"work_date": TODAY, "worker": 1, "qty": 3, "qty_unit": "kg"},
                    }
                ]
            }
        )
        rows = [r for r in self.detail()["sections"] if r["section_def"] == "steps"]
        self.assertTrue(rows[1]["values"]["done"])
        self.patch({"update": [{"section_id": rows[1]["section_id"], "values": {"worker": None}}]})
        rows = [r for r in self.detail()["sections"] if r["section_def"] == "steps"]
        self.assertFalse(rows[1]["values"]["done"])
        error = self.assertDocError(
            "VALIDATION_ERROR",
            self.patch,
            {"update": [{"section_id": rows[0]["section_id"], "values": {"done": False}}]},
        )
        self.assertEqual(error.details[0]["code"], "readonly")

    def test_tc18_materials_r23(self):
        lines = self.inv.lines
        ok = {
            "add": [
                {
                    "section_def": "materials",
                    "values": {"bom_line_id": lines[102], "used": 90, "worker": 1},
                }
            ]
        }
        self.patch(ok)
        for values, code in (
            ({"worker": 1}, "required"),
            ({"bom_line_id": lines[102]}, "duplicate"),
            ({"bom_line_id": 99999}, "not_batch_line"),
            ({"bom_line_id": lines[103], "used": 5}, "stock_managed"),
        ):
            error = self.assertDocError(
                "VALIDATION_ERROR",
                self.patch,
                {"add": [{"section_def": "materials", "values": values}]},
            )
            self.assertEqual(error.details[0]["code"], code, values)
        # 연동 실패: ③④만 건너뜀(①② 그대로)
        with lines_unavailable():
            self.patch({"add": [{"section_def": "materials", "values": {"bom_line_id": 99999}}]})
            self.assertDocError(
                "VALIDATION_ERROR",
                self.patch,
                {"add": [{"section_def": "materials", "values": {"bom_line_id": lines[102]}}]},
            )

    def test_tc25_cancelled_batch(self):
        self.inv.cancel()
        self.assertDocError("PLG_BATCH_CANCELLED", self.add_steps, full_step("GEN", self.gen()))
        self.assertDocError("PLG_BATCH_CANCELLED", self.complete)

    def test_tc26_permission(self):
        self.assertDocError("ROLE_REQUIRED", self.add_steps, full_step("GEN", self.gen()), actor=2)
        tid = run(
            services.create_template,
            1,
            {"name": "효력환", "steps": [{"process_id": self.builtin("OUTER")}]},
        )["process_template_id"]
        self.assertDocError(
            "ROLE_REQUIRED", run, logbook.template_rows, 2, self.log_id, tid, "replace"
        )
        self.assertDocError(
            "ROLE_REQUIRED",
            run,
            logbook.save_template_from_rows,
            2,
            self.log_id,
            {"name": "x", "steps": []},
        )


class CompletionTests(ProdLogTestCase):
    def test_tc16_required(self):
        error = self.assertDocError("COMPLETION_INCOMPLETE", self.complete)
        paths = {e["path"] for e in error.details}
        self.assertIn("sections[steps]", paths)
        self.assertIn("sections[info].inspector", paths)
        self.add_steps(
            {
                "kind": "OUTER",
                "process_id": self.builtin("OUTER"),
                "name": "외포장",
                "work_date": TODAY,
                "worker": 1,
                "dur_on": True,
            },
        )
        self.fill_info()
        error = self.assertDocError("COMPLETION_INCOMPLETE", self.complete)
        missing = sorted(e["path"].split(".")[-1] for e in error.details)
        self.assertEqual(missing, ["dur_unit", "dur_value", "expiry", "fg_qty", "material"])

    def test_tc20_linked_unavailable(self):
        self.add_steps(full_step("GEN", self.gen()))
        self.fill_info()
        with mock.patch.object(
            req, "production_log_source", side_effect=req_errors.SourceUnavailable()
        ):
            self.assertDocError("PLG_LINKED_UNAVAILABLE", self.complete)
        self.assertEqual(self.detail()["status"], "draft")

    def test_tc21_frozen_and_reopen(self):
        self.inv.use(103, 6_000000, line=self.inv.lines[103])
        self.patch(
            {
                "add": [
                    {
                        "section_def": "materials",
                        "values": {"bom_line_id": self.inv.lines[102], "used": 90},
                    }
                ]
            }
        )
        self.add_steps(full_step("GEN", self.gen()))
        self.fill_info()
        self.complete()
        d = self.detail()
        frozen = [r for r in d["sections"] if r["section_def"] == "frozen_materials"]
        self.assertEqual(len(frozen), 4)
        head = next(r["values"] for r in d["sections"] if r["section_def"] == "frozen_batch")
        self.assertEqual(
            (head["product"], head["report_no"], head["planned"]),
            ("[기타가공품] 한동 효력환", "2024-123", "100 kg"),
        )
        water = next(
            r["values"] for r in frozen if r["values"]["bom_line_id"] == self.inv.lines[102]
        )
        self.assertEqual(water["used_e6"], 90_000000)  # 직접 입력 고정
        linked = logbook.linked_data(self.log_id)
        self.assertFalse(linked["changed"])
        self.inv.use(103, 1_000000, line=self.inv.lines[103])  # 작성완료 뒤 투입
        self.assertTrue(logbook.linked_data(self.log_id)["changed"])
        error = self.assertDocError(
            "SYSTEM_SECTION", self.reopen_and_patch_frozen, frozen[0]["section_id"]
        )
        self.assertEqual(error.details[0]["code"], "system_section")

    def reopen_and_patch_frozen(self, section_id):
        self.reopen()
        sections = [r["section_def"] for r in self.detail()["sections"]]
        self.assertNotIn("frozen_batch", sections)  # 재개 때 지움
        return self.patch({"add": [{"section_def": "frozen_materials", "values": {"line_no": 1}}]})


class LinkedTests(ProdLogTestCase):
    def test_tc18_linked_rows(self):
        self.inv.use(103, 6_000000, day="2026-10-26", line=self.inv.lines[103])
        self.inv.use(104, 3000_000000, day="2026-10-25", line=self.inv.lines[103])  # 대체 g
        self.inv.use(105, 2_000000, line=self.inv.lines[105])
        out = logbook.linked_data(self.log_id)
        rows = out["linked"]["materials"]
        self.assertEqual([r["line_no"] for r in rows], [1, 2, 3, 4])
        nok = rows[0]
        self.assertEqual(
            (nok["ratio_e6"], nok["standard_e6"], nok["used_e6"]), (90000, 9_000000, 9_000000)
        )
        self.assertEqual(nok["first_date"], "2026-10-25")
        self.assertEqual(nok["origin"], "뉴질랜드 → 러시아(대체)")
        self.assertEqual(nok["alternatives"], ["녹용(러시아)"])
        self.assertIsNone(rows[3]["ratio_e6"])  # EA ↔ kg 비율 없음(R20)
        self.assertIsNone(rows[2]["used_e6"])  # 미투입
        self.assertEqual(out["linked"]["batch"]["product"], "[기타가공품] 한동 효력환")
        self.assertEqual(set(out["ccp_documents"]), {"CCP-1P", "CCP-2B", "CCP-3P"})
        self.assertIsNone(out["error"])

    def test_tc19_unavailable(self):
        with mock.patch.object(
            req, "production_log_source", side_effect=req_errors.SourceUnavailable()
        ):
            out = logbook.linked_data(self.log_id)
        self.assertEqual((out["linked"], out["error"]), (None, "SOURCE_UNAVAILABLE"))

    def test_tc28_query_count(self):
        with CaptureQueriesContext(connection) as q:
            logbook.linked_data(self.log_id)
        self.assertLessEqual(len(q), 6, [x["sql"][:80] for x in q])  # 템플릿 있으면 7(r1)


class TemplateFlowTests(ProdLogTestCase):
    def make_template(self):
        gen = self.gen("분쇄", std_duration={"value": 1, "unit": "시간"})
        steps = [
            {"process_id": gen},
            {"process_id": self.builtin("CCP-2B")},
            {"process_id": self.builtin("INNER"), "overrides": {"spec": "1환 3.75 g"}},
            {"process_id": self.builtin("OUTER")},
        ]
        return run(services.create_template, 1, {"name": "효력환", "steps": steps})[
            "process_template_id"
        ], gen

    def test_tc12_template_rows(self):
        tid, gen = self.make_template()
        out = run(logbook.template_rows, 1, self.log_id, tid, "replace")
        self.assertEqual([r["kind"] for r in out["rows"]], ["GEN", "CCP-2B", "INNER", "OUTER"])
        first = out["rows"][0]
        self.assertEqual(
            (first["work_date"], first["dur_on"], first["dur_value"]), (TODAY, True, 1.0)
        )
        self.assertEqual(out["rows"][2]["spec"], "1환 3.75 g")
        t = ProcessTemplate.objects.get(pk=tid)
        self.assertEqual(t.used_count, 1)
        self.assertIsNotNone(t.last_used_at)
        self.assertEqual(self.detail()["sections"][0]["section_def"], "info")  # 일지에는 안 씀
        # 덧붙이기: 이미 있는 기본 제공 건너뜀, CCP 일지 없는 CCP 빠짐
        self.add_steps(full_step("OUTER", self.builtin("OUTER")))
        sql(
            "UPDATE document SET deleted_at=%s, deleted_by=1 WHERE document_id=%s",
            [TODAY, self.ccp_id("CCP-2B")],
        )
        out = run(logbook.template_rows, 1, self.log_id, tid, "append")
        self.assertEqual(out["skipped_dup"], ["OUTER"])
        self.assertEqual(out["skipped_ccp"], ["CCP-2B"])
        self.assertEqual([r["kind"] for r in out["rows"]], ["GEN", "INNER"])
        self.assertDocError(
            "PLG_IN_USE", run, services.delete_template, 1, tid, 1
        )  # 불러온 적 있음

    def test_tc13_save_template(self):
        gen = self.gen("분쇄")
        rows = [
            {"kind": "GEN", "process_id": gen, "name": "곱게 분쇄", "mode": "JUDGE"},
            {"kind": "GEN", "name": "일지 한정"},
            {
                "kind": "INNER",
                "process_id": self.builtin("INNER"),
                "name": "내포장",
                "spec": "500 g",
            },
        ]
        out = run(
            logbook.save_template_from_rows, 1, self.log_id, {"name": "새 템플릿", "steps": rows}
        )
        steps = out["template"]["steps"]
        self.assertEqual(out["skipped_rows"], 1)
        self.assertEqual(steps[0]["overrides"], {"name": "곱게 분쇄"})
        self.assertEqual(steps[1]["overrides"], {"spec": "500 g"})
        error = self.assertDocError(
            "PLG_NAME_TAKEN",
            run,
            logbook.save_template_from_rows,
            1,
            self.log_id,
            {"name": "새 템플릿", "steps": rows[:1]},
        )
        tid, version = error.details[0]["id"], error.details[0]["version"]
        overwrite = {"name": "새 템플릿", "steps": rows[:1], "overwrite": True}
        self.assertDocError(  # A8: 버전 없이 덮어쓰기 안 됨
            "VALIDATION_ERROR", run, logbook.save_template_from_rows, 1, self.log_id, overwrite
        )
        self.assertDocError(  # A8: 그 사이 바뀐 템플릿
            "VERSION_CONFLICT",
            run,
            logbook.save_template_from_rows,
            1,
            self.log_id,
            {**overwrite, "expected_version": version + 1},
        )
        out = run(
            logbook.save_template_from_rows,
            1,
            self.log_id,
            {**overwrite, "expected_version": version},
        )
        self.assertTrue(out["overwritten"])
        self.assertEqual(out["template"]["step_count"], 1)
        log = (
            MasterChangeLog.objects.filter(target="template", target_id=tid).order_by("-pk").first()
        )
        self.assertEqual((log.action, log.document_id), ("overwrite", self.log_id))

    def test_tc15_register_process(self):
        gen = self.gen("분쇄")
        out = run(logbook.register_from_document, 1, self.log_id, {"name": " 분쇄 ", "mode": "QTY"})
        self.assertEqual((out["linked_existing"], out["process"]["process_id"]), (True, gen))
        out = run(logbook.register_from_document, 1, self.log_id, {"name": "환주", "mode": "QTY"})
        self.assertFalse(out["linked_existing"])
        log = MasterChangeLog.objects.get(target="process", target_id=out["process"]["process_id"])
        self.assertEqual((log.action, log.document_id), ("register", self.log_id))

    def test_last_template_for_item(self):
        tid, _ = self.make_template()
        self.patch(
            {
                "update": [
                    {
                        "section_id": self.section_id("info"),
                        "values": {"template_id": tid, "template_name": "효력환"},
                    }
                ]
            }
        )
        self.assertEqual(
            logbook.linked_data(self.log_id)["last_template"]["process_template_id"], tid
        )


class CcpValueTests(ProdLogTestCase):
    def test_tc17_ccp_values(self):
        self.assertEqual(logbook.ccp_values(self.log_id, "CCP-1P")["verdict"], None)  # 측정 없음
        ccp = doc.get_document(self.ccp_id("CCP-1P"))
        rows = [r for r in ccp["sections"] if r["section_def"] == "rounds"]
        doc.update_document(
            1,
            ccp["document_id"],
            {
                "expected_version": ccp["version"],
                "sections": {
                    "update": [
                        {
                            "section_id": rows[0]["section_id"],
                            "values": {
                                "measured_at": f"{TODAY}T09:00",
                                "gauss": 9000,
                                "rod_cleaned": "O",
                            },
                        }
                    ]
                },
            },
        )
        self.assertEqual(logbook.ccp_values(self.log_id, "CCP-1P")["verdict"], "적합")
        ccp = doc.get_document(self.ccp_id("CCP-2B"))
        end = next(
            r
            for r in ccp["sections"]
            if r["section_def"] == "rounds" and r["values"].get("phase") == "건조종료 전"
        )
        start = next(
            r
            for r in ccp["sections"]
            if r["section_def"] == "rounds" and r["values"].get("phase") == "건조시작 전"
        )
        doc.update_document(
            1,
            ccp["document_id"],
            {
                "expected_version": ccp["version"],
                "sections": {
                    "update": [
                        {
                            "section_id": start["section_id"],
                            "values": {"measured_at": f"{TODAY}T09:00", "temp_c": 70.0},
                        },
                        {
                            "section_id": end["section_id"],
                            "values": {"measured_at": f"{TODAY}T11:00", "temp_c": 69.8},
                        },
                    ]
                },
            },
        )
        out = logbook.ccp_values(self.log_id, "CCP-2B")
        self.assertEqual((out["temp"], out["time_min"]), (69.8, 120))
        sql(
            "UPDATE document SET deleted_at=%s, deleted_by=1 WHERE document_id=%s",
            [TODAY, self.ccp_id("CCP-3P")],
        )
        self.assertDocError("PLG_CCP_DOC_MISSING", logbook.ccp_values, self.log_id, "CCP-3P")


class ReqViewsTests(ProdLogTestCase):
    def test_tc22_todo(self):
        rows = [
            r
            for g in req_todo.todo_list(1, TODAY)["groups"]
            if g["key"] == "today"
            for r in g["rows"]
        ]
        self.assertIn("PROD-LOG", [r["type_code"] for r in rows])
        self.inv.cancel()
        rows = [
            r
            for g in req_todo.todo_list(1, TODAY)["groups"]
            if g["key"] == "today"
            for r in g["rows"]
        ]
        self.assertNotIn("PROD-LOG", [r["type_code"] for r in rows])

    def test_tc24_dashboard(self):
        self.add_steps(full_step("GEN", self.gen()), {"kind": "GEN", "name": "반쯤", "mode": "QTY"})
        out = req_ccp.ccp_dashboard(1, TODAY)
        batch = next(b for b in out["batches"] if b["batch_id"] == 400)
        self.assertEqual(
            batch["production_log"],
            {"document_id": self.log_id, "status": "draft", "steps_total": 2, "steps_done": 1},
        )


class ApiTests(ProdLogTestCase):
    def call(self, method, path, body=None, staff=1):
        import json

        headers = {} if staff is None else {"HTTP_X_STAFF_ID": str(staff)}
        if body is None:
            return getattr(self.client, method)(f"/api/v1/{path}", **headers)
        return getattr(self.client, method)(
            f"/api/v1/{path}", json.dumps(body), content_type="application/json", **headers
        )

    def test_api_a01_to_a05(self):
        base = f"production-logs/{self.log_id}"
        r = self.call("get", f"{base}/linked", staff=None)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(len(r.json()["linked"]["materials"]), 4)
        tid = run(
            services.create_template,
            1,
            {"name": "효력환", "steps": [{"process_id": self.builtin("OUTER")}]},
        )["process_template_id"]
        r = self.call("post", f"{base}/template-rows", {"template_id": tid, "mode": "replace"})
        self.assertEqual((r.status_code, r.json()["rows"][0]["kind"]), (200, "OUTER"))
        r = self.call("post", f"{base}/save-template", {"name": "새", "steps": r.json()["rows"]})
        self.assertEqual(r.status_code, 201, r.content)
        r = self.call("get", f"{base}/ccp-values?kind=CCP-2B", staff=None)
        self.assertEqual(r.status_code, 200, r.content)
        r = self.call("post", f"{base}/register-process", {"name": "환주", "mode": "QTY"})
        self.assertEqual(r.status_code, 201, r.content)
        r = self.call("post", f"{base}/register-process", {"name": "환주", "mode": "QTY"})
        self.assertEqual((r.status_code, r.json()["linked_existing"]), (200, True))
        r = self.call("post", f"{base}/register-process", {"name": "x", "mode": "QTY"}, staff=2)
        self.assertEqual(r.json()["code"], "ROLE_REQUIRED")
        self.assertEqual(self.call("get", "production-logs/999999/linked").status_code, 404)

    def test_api_submit_rejected(self):
        d = self.detail()
        r = self.call("post", f"documents/{self.log_id}/submit", {"expected_version": d["version"]})
        self.assertEqual((r.status_code, r.json()["code"]), (409, "NO_APPROVAL_FORM"))
