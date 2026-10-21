"""P4 메소드 테스트 (수준 M). 이름의 tcNNN은 document/p4-s2-spec.md 7장의 TC ID.

파일 기능(F14~F18)·상신 잠금의 파일 보존(TC-141)은 스프린트 3 test_files.py에 있다.
"""

import ast
import re
from pathlib import Path

from django.db import connection, transaction
from django.test import TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext

from apps.core import trace
from apps.documents import errors, files, flows, services
from apps.documents.models import (
    DeviationAction,
    DeviationChecker,
    DocSection,
    Document,
    DocumentRef,
    DocumentTemplate,
)
from apps.documents.seed import ensure_templates
from apps.documents.tests.base import ccp_payload, make_document
from apps.documents.tests.p4 import (
    DAY,
    GOOD_1P,
    add_lot_row,
    at,
    attach_file,
    ccp1p_rows,
    complete,
    filled_ccp1p,
    goc,
    inspect,
    lot_ref,
    new_ccp,
    new_d01,
    new_d03,
    new_rows_doc,
    patch,
    rows_of,
    set_info,
    setup_p4,
    version_of,
)


def codes(ctx):
    return {d["code"] for d in ctx.exception.details}


def traced(func):
    record, token = trace.start("TEST", "method")
    try:
        return func(), [s.step_id for s in record.steps]
    finally:
        trace.stop(token)


class P4TestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.t = setup_p4()

    def lock(self, document_id, expected_version=None):
        with transaction.atomic():
            return services.lock_for_review(document_id, expected_version)

    def to_status(self, document_id, status):
        """completed → submitted → (approved|rejected). WF 없이 DOC 함수로만."""
        complete(document_id)
        if status == "completed":
            return
        self.lock(document_id)
        if status == "approved":
            services.mark_approved(document_id)
        elif status == "rejected":
            services.mark_rejected(document_id)


# ---------------------------------------------------------------- N1~N3


class GetOrCreateTests(P4TestCase):
    def test_tc120_twice_same_document(self):
        first = new_d01()
        second = new_d01()
        doc = first["document"]
        self.assertEqual((first["created"], second["created"]), (True, False))
        self.assertEqual(second["document"]["document_id"], doc["document_id"])
        self.assertEqual(
            (doc["status"], doc["version"], doc["record_key"]), ("draft", 1, "D01|lot:88")
        )
        info = [s for s in doc["sections"] if s["section_def"] == "info"]
        self.assertEqual([s["values"] for s in info], [{"item_name": "유자"}])
        self.assertEqual(Document.objects.count(), 1)
        self.assertEqual(DocumentRef.objects.count(), 1)
        self.assertEqual(doc["refs"][0]["label"], "RM-1011-01")
        self.assertEqual(doc["requirement"], "lot")

    def test_tc120_trace_matches_flow(self):
        _, ids = traced(new_d01)
        self.assertTrue(flows.matches("DOC-GOC", ids), ids)
        _, ids = traced(new_d01)
        self.assertEqual(ids, ["DOC-GOC-00", "DOC-GOC-01", "DOC-GOC-01a"])

    def test_tc122_invalid_input(self):
        with self.assertRaises(errors.ValidationFailed) as ctx:
            goc("D01", "D01|lot:x", [{"label": "대상 없음"}])
        self.assertEqual(codes(ctx), {"no_target"})
        with self.assertRaises(errors.ValidationFailed) as ctx:
            goc("D01", "D01|lot:999", lot_ref(999))
        self.assertEqual(codes(ctx), {"not_found"})
        DocumentTemplate.objects.filter(type_code="D02").update(is_active=False)
        with self.assertRaises(errors.TemplateInactive):
            goc("D02", "D02|lot:88", lot_ref(88))
        with self.assertRaises(errors.TemplateNotFound):
            goc("NOPE", "NOPE|lot:88", lot_ref(88))
        self.assertEqual(Document.objects.count(), 0)
        self.assertEqual(DocumentRef.objects.count(), 0)

    def test_values_must_be_valid(self):
        with self.assertRaises(errors.ValidationFailed) as ctx:
            goc(
                "CCP-1P",
                "CCP-1P|batch:12",
                [{"production_batch_id": 12}],
                {"info": {"inspector": 999}, "rounds": {}},
            )
        self.assertEqual(codes(ctx), {"unknown_staff", "unknown_section"})


class GetOrCreateOutsideTransactionTests(TransactionTestCase):
    def setUp(self):
        setup_p4()

    def test_tc121_requires_transaction(self):
        with self.assertRaises(errors.TransactionRequired):
            services.get_or_create_document(3, "D01", "D01|lot:88", DAY, lot_ref(88))
        with self.assertRaises(errors.TransactionRequired):
            services.add_ref_row(3, 1, "lots", {}, lot_ref(88), "lot_id")
        self.assertEqual(Document.objects.count(), 0)


class AddRefRowTests(P4TestCase):
    """N2는 일반 기능으로 남긴다(P6a-S2 Q2) — D03 대신 행 단위 시험 양식으로 확인."""

    def setUp(self):
        self.d03 = new_rows_doc()["document"]["document_id"]

    def test_tc124_add_twice(self):
        first = add_lot_row(self.d03, 88)
        version = version_of(self.d03)
        second = add_lot_row(self.d03, 88)
        self.assertEqual((first["created"], second["created"]), (True, False))
        self.assertEqual(first["section_id"], second["section_id"])
        self.assertEqual(version, 2)
        self.assertEqual(version_of(self.d03), 2)  # 두 번째는 버전 변화 없음
        self.assertEqual(
            DocSection.objects.filter(document_id=self.d03, section_def="lots").count(), 1
        )
        self.assertEqual(DocumentRef.objects.filter(section_id__isnull=False).count(), 1)

    def test_tc124_trace_matches_flow(self):
        _, ids = traced(lambda: add_lot_row(self.d03, 88))
        self.assertTrue(flows.matches("DOC-ARR", ids), ids)

    def test_tc125_locked_states(self):
        add_lot_row(
            self.d03,
            88,
            {"appearance": "양호", "packaging": "양호", "labeling": "양호", "verdict": "PASS"},
        )
        # P14 r13: 테스트 전용 양식(TEST-LOT-ROWS)은 역할 설정에 없어 팀장(1)만 쓴다(R07·R08)
        set_info(self.d03, {"inspector": 4}, actor=1)
        complete(self.d03, actor=1)
        version = version_of(self.d03)
        with self.assertRaises(errors.DocumentLocked):
            add_lot_row(self.d03, 89)
        self.lock(self.d03)
        with self.assertRaises(errors.DocumentLocked):
            add_lot_row(self.d03, 90)
        self.assertEqual(version_of(self.d03), version + 1)  # 잠금 +1만
        self.assertEqual(
            DocSection.objects.filter(document_id=self.d03, section_def="lots").count(), 1
        )

    def test_tc128_locked_but_row_exists(self):
        add_lot_row(
            self.d03,
            88,
            {"appearance": "양호", "packaging": "양호", "labeling": "양호", "verdict": "PASS"},
        )
        # P14 r13: 테스트 전용 양식 — 점검자 지정은 팀장(R08), 점검자 3이 작성완료(R07 점검자)
        set_info(self.d03, {"inspector": 3}, actor=1)
        self.to_status(self.d03, "submitted")
        version = version_of(self.d03)
        again = add_lot_row(self.d03, 88)
        self.assertEqual(again["created"], False)
        self.assertEqual(version_of(self.d03), version)

    def test_readonly_values_allowed_for_system(self):
        out = add_lot_row(self.d03, 88, {"supplier_name": "고흥농협"})
        row = DocSection.objects.get(pk=out["section_id"])
        self.assertEqual(row.values_json["supplier_name"], "고흥농협")
        self.assertEqual(row.recorded_by_id, 3)


class FindTests(P4TestCase):
    def test_tc127_find_by_ref(self):
        d01 = new_d01()["document"]["document_id"]
        d03 = new_d03()["document"]["document_id"]
        rows = new_rows_doc()["document"]["document_id"]
        section_id = add_lot_row(rows, 88)["section_id"]
        p1 = new_ccp()["document"]["document_id"]
        p2 = new_ccp("CCP-2B", "2B")["document"]["document_id"]
        by_lot = services.find_documents_by_ref(lot_id=88)
        self.assertEqual(
            [(r["document_id"], r["type_code"], r["section_id"]) for r in by_lot],
            [(d01, "D01", None), (d03, "D03", None), (rows, "TEST-LOT-ROWS", section_id)],
        )
        by_batch = services.find_documents_by_ref(production_batch_id=12)
        self.assertEqual({r["document_id"] for r in by_batch}, {p1, p2})
        one = services.find_documents_by_ref(production_batch_id=12, process_code="1P")
        self.assertEqual([r["document_id"] for r in one], [p1])
        _, ids = traced(lambda: services.find_documents_by_ref(lot_id=88))
        self.assertTrue(flows.matches("DOC-FND", ids), ids)


# ---------------------------------------------------------------- F12·F13 작성완료·재개


class CompleteTests(P4TestCase):
    def filled_d03(self):
        d03 = new_d03()["document"]["document_id"]
        inspect(d03)
        set_info(d03, {"inspector": 4})
        return d03

    def test_tc130_complete(self):
        d03 = self.filled_d03()
        version = version_of(d03)
        result = complete(d03, actor=4)
        doc = Document.objects.get(pk=d03)
        self.assertEqual((result["status"], doc.status), ("completed", "completed"))
        self.assertEqual((doc.completed_by_id, doc.version), (4, version + 1))
        self.assertIsNotNone(doc.completed_at)
        self.assertEqual(result["completed_by"], 4)

    def test_tc131_problems_and_no_change(self):
        document_id = new_ccp()["document"]["document_id"]
        patch(
            document_id,
            {
                "add": [
                    {"section_def": "rounds", "values": v}
                    for v in ccp1p_rows(("작업시작 전", "10:00", 9800, "O"))
                ]
            },
        )
        patch(
            document_id,
            {
                "add": [
                    {
                        "section_def": "rounds",
                        "values": {
                            "phase": "작업 중",
                            "measured_at": at("09:00"),
                            "rod_cleaned": "O",
                        },
                    }
                ]
            },
        )
        before = Document.objects.filter(pk=document_id).values().get()
        with self.assertRaises(errors.CompletionIncomplete) as ctx:
            complete(document_id)
        found = codes(ctx)
        self.assertEqual(found, {"required", "phase_order", "deviation_required"})
        paths = {d["path"] for d in ctx.exception.details}
        self.assertIn("sections[info#1].values.inspector", paths)
        self.assertEqual(Document.objects.filter(pk=document_id).values().get(), before)

    def test_tc131_min_rows(self):
        document_id = new_ccp()["document"]["document_id"]
        set_info(document_id, {"inspector": 4})
        patch(
            document_id,
            {
                "add": [
                    {"section_def": "rounds", "values": v}
                    for v in ccp1p_rows(("작업시작 전", "08:00", 10500, "O"))
                ]
            },
        )
        with self.assertRaises(errors.CompletionIncomplete) as ctx:
            complete(document_id)
        self.assertIn("min_rows", codes(ctx))

    def test_tc153_phase_order(self):
        cases = {
            "정상": (GOOD_1P, None),
            "종료가 작업 중보다 이름": (
                (
                    ("작업시작 전", "08:50", 10500, "O"),
                    ("작업 중", "09:50", 10300, "O"),
                    ("작업종료 후", "09:30", 10200, "O"),
                ),
                "phase_order",
            ),
            "시작·종료 같은 시각": (
                (("작업시작 전", "08:50", 10500, "O"), ("작업종료 후", "08:50", 10200, "O")),
                None,
            ),
        }
        for name, (specs, expected) in cases.items():
            with self.subTest(name):
                Document.objects.all().update(
                    record_key=None, deleted_at="2026-10-11T00:00Z", deleted_by=1
                )
                document_id = filled_ccp1p(specs)
                if expected is None:
                    self.assertEqual(complete(document_id)["status"], "completed")
                else:
                    with self.assertRaises(errors.CompletionIncomplete) as ctx:
                        complete(document_id)
                    self.assertEqual(codes(ctx), {expected})

    def test_tc132_files_required(self):
        d01 = new_d01()["document"]["document_id"]
        with self.assertRaises(errors.CompletionIncomplete) as ctx:
            complete(d01)
        self.assertEqual(codes(ctx), {"files_required"})
        attach_file(d01)
        self.assertEqual(complete(d01)["status"], "completed")

    def test_tc133_failures(self):
        done = filled_ccp1p()
        complete(done)
        with self.assertRaises(errors.DocumentLocked):
            complete(done)
        self.lock(done)
        with self.assertRaises(errors.DocumentLocked):
            complete(done)
        doc, _ = make_document(ensure_templates()[("CCP_MONITORING", 1)])
        services.delete_document(3, doc.document_id)
        with self.assertRaises(errors.DocumentNotFound):
            services.complete_document(3, doc.document_id, 2)
        other = new_d01()["document"]["document_id"]
        with self.assertRaises(errors.VersionConflict):
            services.complete_document(3, other, 5)

    def test_tc134_rejected_to_completed(self):
        document_id = filled_ccp1p()
        self.to_status(document_id, "rejected")
        self.assertEqual(complete(document_id)["status"], "completed")

    def test_tc136_reopen(self):
        document_id = filled_ccp1p()
        complete(document_id)
        result = services.reopen_document(3, document_id, version_of(document_id))
        doc = Document.objects.get(pk=document_id)
        self.assertEqual(
            (result["status"], doc.completed_at, doc.completed_by_id), ("draft", None, None)
        )
        with self.assertRaises(errors.InvalidTransition):
            services.reopen_document(3, document_id, version_of(document_id))
        with self.assertRaises(errors.VersionConflict):
            complete(document_id)
            services.reopen_document(3, document_id, 1)

    def test_tc138_completed_is_locked(self):
        document_id = filled_ccp1p()
        complete(document_id)
        with self.assertRaises(errors.DocumentLocked):
            patch(document_id, document={"subject": "x"})

    def test_tc140_lock_only_completed(self):
        document_id = filled_ccp1p()
        with self.assertRaises(errors.DocumentLocked):
            self.lock(document_id)
        self.to_status(document_id, "rejected")
        with self.assertRaises(errors.DocumentLocked):
            self.lock(document_id)
        complete(document_id)
        self.assertEqual(self.lock(document_id)["status"], "submitted")

    def test_trace_matches_flows(self):
        document_id = filled_ccp1p()
        _, ids = traced(lambda: complete(document_id))
        self.assertTrue(flows.matches("DOC-CMP", ["DOC-CMP-01", *ids]), ids)
        _, ids = traced(lambda: services.reopen_document(3, document_id, version_of(document_id)))
        self.assertTrue(flows.matches("DOC-ROP", ["DOC-ROP-01", *ids]), ids)


# ---------------------------------------------------------------- F06·F07·F08 변경


class CreateUpdateRuleTests(P4TestCase):
    def test_tc145_create_without_required(self):
        payload = ccp_payload(ensure_templates()[("CCP_MONITORING", 1)])
        payload["sections"][0]["values"] = {}
        result = services.create_document(3, payload)
        self.assertEqual(result["status"], "draft")

    def test_tc146_requirement_only(self):
        with self.assertRaises(errors.TemplateRequirementOnly):
            services.create_document(
                3,
                {"template_id": self.t["D01"].template_id, "work_date": DAY, "sections": []},
            )
        self.assertEqual(Document.objects.count(), 0)

    def test_tc147_system_values(self):
        d03 = new_d03()["document"]["document_id"]
        info = rows_of(d03, "info")[0]
        rows_doc = new_rows_doc()["document"]["document_id"]
        add_lot_row(rows_doc, 88)
        row = rows_of(rows_doc, "lots")[0]
        ccp = new_ccp()["document"]["document_id"]
        cases = [
            (
                d03,
                {"update": [{"section_id": info["section_id"], "values": {"item_name": "x"}}]},
                None,
                "readonly",
            ),
            (
                ccp,
                {
                    "add": [
                        {
                            "section_def": "rounds",
                            "values": {**ccp1p_rows(GOOD_1P[0])[0], "verdict": "적합"},
                        }
                    ]
                },
                None,
                "readonly",
            ),
            (
                rows_doc,
                {"add": [{"section_def": "lots", "values": {"appearance": "양호"}}]},
                None,
                "system_rows",
            ),
            (rows_doc, {"delete": [row["section_id"]]}, None, "system_rows"),
            (d03, None, {"work_date": "2026-10-12"}, "fixed"),
        ]
        for document_id, sections, document, code in cases:
            with self.subTest(code=code, sections=sections, document=document):
                version = version_of(document_id)
                with self.assertRaises(errors.ValidationFailed) as ctx:
                    patch(document_id, sections, document, actor=1)  # P14 r13: 팀장(R07)
                self.assertEqual(codes(ctx), {code})
                self.assertEqual(version_of(document_id), version)

    def test_tc148_ccp1p_verdict(self):
        document_id = new_ccp()["document"]["document_id"]
        values = [
            {"phase": "작업 중", "measured_at": at("09:00"), "gauss": 10500, "rod_cleaned": "O"},
            {"phase": "작업 중", "measured_at": at("10:00"), "gauss": 9800, "rod_cleaned": "O"},
            {"phase": "작업 중", "measured_at": at("11:00"), "rod_cleaned": "O"},
            {"phase": "작업 중", "measured_at": at("12:00"), "gauss": 10000, "rod_cleaned": "O"},
        ]
        patch(document_id, {"add": [{"section_def": "rounds", "values": v} for v in values]})
        verdicts = [r["values"].get("verdict") for r in rows_of(document_id, "rounds")]
        self.assertEqual(verdicts, ["적합", "부적합", None, "적합"])
        first = rows_of(document_id, "rounds")[0]
        patch(
            document_id,
            {"update": [{"section_id": first["section_id"], "values": {"gauss": 9000}}]},
        )
        self.assertEqual(
            rows_of(document_id, "rounds")[0]["values"]["verdict"], "부적합"
        )  # UPD-05b

    def test_tc152_ccp3p(self):
        document_id = new_ccp("CCP-3P", "3P")["document"]["document_id"]
        ok = {"fe_only": "○", "sts_only": "○", "product_only": "X"}  # v2(P12 DP-03)
        ok.update(product_fe="○", product_sus="○")
        checks = [
            {"phase": "시작", "passed_at": at("08:40"), **ok},
            {"phase": "종료", "passed_at": at("17:00"), **ok, "sts_only": "X"},
        ]
        patch(document_id, {"add": [{"section_def": "checks", "values": v} for v in checks]})
        self.assertEqual(
            [r["values"]["verdict"] for r in rows_of(document_id, "checks")], ["적합", "부적합"]
        )
        set_info(document_id, {"inspector": 4})
        first = rows_of(document_id, "checks")[1]
        patch(
            document_id,
            {"update": [{"section_id": first["section_id"], "values": {"sts_only": "○"}}]},
        )
        patch(
            document_id,
            {
                "add": [
                    {"section_def": "summary", "values": {"passed_qty": 1180, "detected_qty": 0}}
                ]
            },
        )
        self.assertEqual(complete(document_id)["status"], "completed")
        services.reopen_document(3, document_id, version_of(document_id))
        summary = rows_of(document_id, "summary")[0]
        patch(
            document_id,
            {"update": [{"section_id": summary["section_id"], "values": {"detected_qty": 1}}]},
        )
        with self.assertRaises(errors.CompletionIncomplete) as ctx:
            complete(document_id)
        self.assertEqual(codes(ctx), {"deviation_required"})

    def test_tc149_datetime_format(self):
        document_id = new_ccp()["document"]["document_id"]
        for bad in ("2026-10-11 09:50", "2026-13-01T09:00"):
            with self.subTest(bad), self.assertRaises(errors.ValidationFailed) as ctx:
                patch(
                    document_id,
                    {
                        "add": [
                            {
                                "section_def": "rounds",
                                "values": {"phase": "작업 중", "measured_at": bad},
                            }
                        ]
                    },
                )
            self.assertEqual(codes(ctx), {"invalid"})

    def test_tc150_requirement_document_not_deletable(self):
        d01 = new_d01()["document"]["document_id"]
        with self.assertRaises(errors.DocumentNotDeletable) as ctx:
            services.delete_document(3, d01)
        self.assertEqual(ctx.exception.details[0]["code"], "requirement")


# ---------------------------------------------------------------- F19~F21 개선조치


class DeviationTests(P4TestCase):
    def setUp(self):
        self.doc = filled_ccp1p()

    def create(self, **data):
        body = {"description": "09:50 자력 9,800G", "actor_id": 4, "checker_ids": [2, 5], **data}
        return services.create_deviation(4, self.doc, body)

    def test_tc170_create_on_approved(self):
        self.to_status(self.doc, "approved")
        version = version_of(self.doc)
        result = self.create()
        self.assertEqual(DeviationAction.objects.count(), 1)
        self.assertEqual(DeviationChecker.objects.count(), 2)
        self.assertEqual(result["checker_ids"], [2, 5])
        self.assertEqual(version_of(self.doc), version)
        _, ids = traced(lambda: self.create(checker_ids=[]))
        self.assertTrue(flows.matches("DOC-DVC", ["DOC-DVC-00", *ids]), ids)

    def test_tc171_invalid(self):
        other = new_d01()["document"]["document_id"]
        other_row = rows_of(other, "info")[0]["section_id"]
        cases = [
            ({"description": "   "}, "required"),
            ({"section_id": other_row}, "not_found"),
            ({"actor_id": 999}, "unknown_staff"),
            ({"checker_ids": [2, 2]}, "duplicate"),
            ({"checker_ids": list(range(1, 12))}, "max_items"),
            ({"description": "x" * 501}, "max_length"),
        ]
        for data, code in cases:
            with self.subTest(code), self.assertRaises(errors.ValidationFailed) as ctx:
                self.create(**data)
            self.assertEqual(codes(ctx), {code})
        self.assertEqual(DeviationAction.objects.count(), 0)
        with self.assertRaises(errors.DocumentNotFound):
            services.create_deviation(4, 9999, {"description": "x"})

    def test_tc172_update(self):
        created = self.create()
        # P14 r13: 수정하는 사람 = CCP 담당자(3) — 2는 CCP 역할이 없어 403(R07)
        result = services.update_deviation(
            3, created["deviation_id"], 1, {"action_result": "재조정 후 적합", "checker_ids": [3]}
        )
        self.assertEqual((result["version"], result["checker_ids"]), (2, [3]))
        row = DeviationAction.objects.get(pk=created["deviation_id"])
        self.assertEqual((row.updated_by_id, row.action_result), (3, "재조정 후 적합"))
        with self.assertRaises(errors.VersionConflict):
            services.update_deviation(3, created["deviation_id"], 1, {"action_result": "x"})
        _, ids = traced(
            lambda: services.update_deviation(3, created["deviation_id"], 2, {"action_result": "y"})
        )
        self.assertTrue(flows.matches("DOC-DVU", ["DOC-DVU-00", *ids]), ids)

    def test_tc174_delete(self):
        created = self.create()
        services.delete_deviation(4, created["deviation_id"], 1)
        self.assertIsNotNone(DeviationAction.objects.get(pk=created["deviation_id"]).deleted_at)
        self.assertEqual(services.get_document(self.doc)["deviations"], [])
        with self.assertRaises(errors.DeviationNotFound):
            services.delete_deviation(4, created["deviation_id"], 2)

    def test_c103_row_delete_keeps_deviation(self):
        """ERD v5 C103 대체: DB FK에 ON DELETE가 없으므로(D1) ORM이 관련 행을 NULL로 바꾼다."""
        row = rows_of(self.doc, "rounds")[1]
        created = self.create(section_id=row["section_id"])
        patch(self.doc, {"delete": [row["section_id"]]})
        deviation = DeviationAction.objects.get(pk=created["deviation_id"])
        self.assertIsNone(deviation.section_id)
        self.assertIsNone(deviation.deleted_at)

    def test_tc175_deleted_deviation_not_counted(self):
        first = rows_of(self.doc, "rounds")[1]
        patch(
            self.doc, {"update": [{"section_id": first["section_id"], "values": {"gauss": 9800}}]}
        )
        created = self.create()
        services.delete_deviation(4, created["deviation_id"], 1)
        with self.assertRaises(errors.CompletionIncomplete) as ctx:
            complete(self.doc)
        self.assertEqual(codes(ctx), {"deviation_required"})
        self.create()
        self.assertEqual(complete(self.doc)["status"], "completed")


# ---------------------------------------------------------------- F04·F05 조회


class ReadTests(P4TestCase):
    def test_tc177_detail_parts(self):
        document_id = filled_ccp1p()
        dev = services.create_deviation(4, document_id, {"description": "x", "checker_ids": [2]})
        services.delete_deviation(
            4, services.create_deviation(4, document_id, {"description": "y"})["deviation_id"], 1
        )
        attach_file(document_id)
        detail = services.get_document(document_id)
        self.assertEqual(detail["refs"][0]["production_batch_id"], 12)
        self.assertEqual([d["deviation_id"] for d in detail["deviations"]], [dev["deviation_id"]])
        self.assertEqual(len(detail["files"]), 1)
        self.assertEqual(detail["requirement"], "batch")

    def test_tc178_target_filter(self):
        d03 = new_d03()["document"]["document_id"]
        d01 = new_d01(89)["document"]["document_id"]
        new_ccp()
        found = services.list_documents({"target": "RM-1011"}, 1)
        # P7(DOC-F04 변경): D03은 작업일마다 묶음 줄 1개 — 대상 필터는 문서마다 먼저 적용
        docs = [i for i in found["items"] if i["kind"] == "document"]
        bundles = [i for i in found["items"] if i["kind"] == "bundle"]
        self.assertEqual({i["document_id"] for i in docs}, {d01})
        self.assertEqual([(b["type_code"], b["count"]) for b in bundles], [("D03", 1)])
        summaries = {i["document_id"]: i["target_summary"] for i in docs}
        self.assertEqual(summaries[d01], "LOT RM-1011-02 · 유자")  # P6a: 품명(D-088 Q3·Q6)
        self.assertEqual(
            services.get_document(d03)["target_summary"], "LOT RM-1011-01 · 유자 · 고흥농협"
        )  # P7 상세: 매입처까지(ISS-018)
        with self.assertRaises(errors.InvalidFilter):
            services.list_documents({"target": "x" * 51}, 1)

    def test_tc179_has_coa_hint(self):
        d88 = new_d03(88)["document"]["document_id"]
        d89 = new_d03(89)["document"]["document_id"]
        attach_file(new_d01(88)["document"]["document_id"])
        new_d01(89)
        before = list(DocSection.objects.order_by("pk").values_list("values_json", flat=True))
        hints = []
        for d03 in (d88, d89):  # P6a: D03은 LOT 문서, 힌트는 문서 단위 LOT 기준(2.3)
            detail = services.get_document(d03)
            hints += [
                s.get("hints", {}).get("has_coa")
                for s in detail["sections"]
                if s["section_def"] == "inspection"
            ]
        self.assertEqual(hints, ["유", "무"])
        after = list(DocSection.objects.order_by("pk").values_list("values_json", flat=True))
        self.assertEqual(before, after)

    def test_tc151_templates_flag(self):
        ensure_templates()
        items = {i["type_code"]: i for i in services.list_templates()}
        self.assertTrue(items["D03"]["requirement_only"])
        self.assertFalse(items["CCP_MONITORING"]["requirement_only"])


# ---------------------------------------------------------------- NFR-12 경계


STOCK_TABLES = ("items", "lots", "production_batches", "stock_movements")
FORBIDDEN_IMPORTS = (
    "apps.devtools",
    "apps.doc_requirements",
    "apps.approvals",
    "apps.document_workflow",
    "apps.stock",
    "apps.inventory",
    "apps.production",
)
PACKAGE = Path(__file__).resolve().parents[1]


class BoundaryTests(P4TestCase):
    def test_tc180_no_stock_imports(self):
        offenders = []
        for path in PACKAGE.rglob("*.py"):
            if "tests" in path.parts or "migrations" in path.parts:
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                offenders += [f"{path.name}: {n}" for n in names if n.startswith(FORBIDDEN_IMPORTS)]
        self.assertEqual(offenders, [])

    def test_tc180_no_stock_tables_in_sql(self):
        with CaptureQueriesContext(connection) as ctx:
            d01 = new_d01()["document"]["document_id"]
            d03 = new_d03()["document"]["document_id"]
            services.find_documents_by_ref(lot_id=88)
            services.list_documents({"target": "RM"}, 1)
            services.get_document(d03)
            attach_file(d01)
            complete(d01)
            files.search_files({"type_code": "D01", "item": "유자"})  # 스프린트 3 F18
        pattern = re.compile(r'\b(FROM|JOIN)\s+"?(%s)"?\b' % "|".join(STOCK_TABLES), re.I)
        offenders = [q["sql"] for q in ctx.captured_queries if pattern.search(q["sql"])]
        self.assertEqual(offenders, [])


# ---------------------------------------------------------------- P6a D03 v2(LOT 문서, D-084·D-088)


FULL = {"appearance": "양호", "packaging": "양호", "labeling": "양호", "verdict": "PASS"}


class P6aD03Tests(P4TestCase):
    def test_p6a_tc012_list_query_count(self):
        """D03이 든 목록. P7(DOC-F04 변경): D03 2건은 묶음 줄 1개 — 건수·페이지(UNION) + 묶음 집계
        + 묶음 전체 건수(기간 필터) = SQL 4(문서 줄이 없어 참조·품명 SQL 없음, 상한 6)."""
        new_d03()
        new_d03(lot_id=89)
        new_d01(89)
        with self.assertNumQueries(6):
            result = services.list_documents({"from": DAY, "to": DAY}, 1)
        bundle = next(i for i in result["items"] if i["kind"] == "bundle")
        self.assertEqual((bundle["count"], bundle["total"]), (2, 2))
        summaries = {i["target_summary"] for i in result["items"] if i["kind"] == "document"}
        self.assertIn("LOT RM-1011-02 · 유자", summaries)

    def test_p6a_tc010_completion_rules(self):
        """작성완료 검사: 점검자·판정 필수, 부적합이면 개선조치 1건 이상(비반복 섹션에서도)."""
        cases = [
            ({}, FULL, {"required"}),
            ({"inspector": 4}, {}, {"required"}),
            ({"inspector": 4}, {**FULL, "verdict": "FAIL"}, {"deviation_required"}),
        ]
        for info, inspection, expected in cases:
            with self.subTest(info=info, inspection=inspection), transaction.atomic():
                sid = transaction.savepoint()
                d03 = new_d03()["document"]["document_id"]
                if info:
                    set_info(d03, info)
                if inspection:
                    inspect(d03, inspection)
                with self.assertRaises(errors.CompletionIncomplete) as ctx:
                    complete(d03)
                self.assertTrue(expected <= codes(ctx), codes(ctx))
                transaction.savepoint_rollback(sid)
        d03 = new_d03()["document"]["document_id"]
        set_info(d03, {"inspector": 4})
        inspect(d03, {**FULL, "verdict": "FAIL"})
        body = {"description": "포장 파손", "action_result": "반품"}
        dev = services.create_deviation(4, d03, body)
        self.assertEqual(complete(d03)["status"], "completed")
        # P6a-TC-014: D03 개선조치에는 관련 행이 없다
        self.assertIsNone(DeviationAction.objects.get(pk=dev["deviation_id"]).section_id)

    def test_p6a_tc013_single_row_sections(self):
        d03 = new_d03()["document"]["document_id"]
        for section in ("inspection", "info"):
            with self.subTest(section=section):
                version = version_of(d03)
                with self.assertRaises(errors.ValidationFailed):
                    patch(d03, {"add": [{"section_def": section, "values": {}}]})
                self.assertEqual(version_of(d03), version)

    def test_p6a_tc030_template_versions(self):
        rows = dict(
            DocumentTemplate.objects.filter(type_code="D03").values_list("version", "is_active")
        )
        self.assertEqual(rows, {1: False, 2: True})
        self.assertEqual(self.t["D03"].version, 2)
        d03 = new_d03()["document"]["document_id"]
        self.assertEqual(Document.objects.get(pk=d03).template.version, 2)
        self.assertEqual(
            [s["section_def"] for s in services.get_document(d03)["sections"]],
            ["info", "inspection"],
        )
