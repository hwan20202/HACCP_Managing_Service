"""P12 DP-03: CCP-3P v2(캔디류 양식)와 v1 → v2 바꾸기(마이그레이션 0004)."""

import importlib

from django.apps import apps as django_apps
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.documents import ccp3p_v2, services
from apps.documents.models import DocSection, Document, DocumentTemplate
from apps.documents.seed_forms import CCP_3P_V2
from apps.documents.tests.p4 import DAY, at, new_ccp, patch, rows_of, setup_p4

SECTION = ccp3p_v2.checks_section_of(CCP_3P_V2)
MIGRATION = importlib.import_module("apps.documents.migrations.0004_ccp3p_v2")
# DOC는 APR을 import하지 않는다(TC-090) — 마이그레이션처럼 앱 레지스트리로 모델을 얻음
ApprovalRequest = django_apps.get_model("approvals", "ApprovalRequest")

V1_OK = {
    **dict.fromkeys(("fe_l", "fe_c", "fe_r", "sus_l", "sus_c", "sus_r"), "○"),
    "product_only": "X",
    "product_fe": "○",
    "product_sus": "○",
}


class ConvertRuleTests(SimpleTestCase):
    def test_combine_m1(self):
        self.assertEqual(ccp3p_v2.combine(["○", "○", "○"]), "○")
        self.assertEqual(ccp3p_v2.combine(["○", "X", "○"]), "X")
        self.assertEqual(ccp3p_v2.combine(["X", None, "○"]), "X")  # X가 빈칸보다 먼저
        self.assertIsNone(ccp3p_v2.combine(["○", None, "○"]))
        self.assertIsNone(ccp3p_v2.combine([None, None, None]))

    def test_check_row_and_verdict(self):
        row = {"phase": "중간", "passed_at": at("10:40"), **V1_OK, "sus_r": "X", "note": "재확인"}
        new = ccp3p_v2.convert_check(row, SECTION)
        self.assertEqual(
            new,
            {
                "phase": "중간",
                "passed_at": at("10:40"),
                "fe_only": "○",
                "sts_only": "X",
                "product_only": "X",
                "product_fe": "○",
                "product_sus": "○",
                "verdict": "부적합",
            },
        )
        ok = ccp3p_v2.convert_check({"phase": "시작", "passed_at": at("08:40"), **V1_OK}, SECTION)
        self.assertEqual(ok["verdict"], "적합")

    def test_note_moves_to_first_summary(self):
        checks = [
            {"passed_at": at("10:40"), "note": "센서 재확인"},
            {"passed_at": at("08:40"), "note": " 첫 통과 "},
            {"passed_at": at("09:00"), "note": ""},
        ]
        _, summaries, added = ccp3p_v2.convert(
            checks, [{"note": "이상 없음"}, {"note": "둘째"}], "유자차", SECTION
        )
        self.assertFalse(added)
        self.assertEqual(
            summaries[0]["note"],
            "이상 없음 [행 비고] 10-11 08:40 첫 통과 / 10-11 10:40 센서 재확인",
        )
        self.assertEqual(summaries[1]["note"], "둘째")

    def test_note_without_summary_adds_row(self):
        _, summaries, added = ccp3p_v2.convert([{"note": "a"}], [], "유자차", SECTION)
        self.assertTrue(added)
        self.assertEqual(summaries, [{"item_name": "유자차", "note": "[행 비고] a"}])
        _, summaries, added = ccp3p_v2.convert([{"note": ""}], [], "유자차", SECTION)
        self.assertEqual((summaries, added), ([], False))

    def test_note_limit(self):
        text = ccp3p_v2.merge_note("가" * 495, ["나" * 20])
        self.assertEqual(len(text), ccp3p_v2.NOTE_LIMIT)
        self.assertTrue(text.endswith("…"))

    def test_snapshot(self):
        snapshot = {
            "document_id": 1,
            "template": {"template_id": 7, "type_code": "CCP-3P", "version": 1, "name": "x"},
            "sections": [
                {"section_def": "info", "values": {"item_name": "유자차"}},
                {
                    "section_def": "checks",
                    "values": {**V1_OK, "note": "메모", "passed_at": at("08:40")},
                },
            ],
        }
        new = ccp3p_v2.convert_snapshot(snapshot, {"template_id": 9, "version": 2}, SECTION)
        self.assertEqual(new["template"]["template_id"], 9)
        self.assertEqual(new["template"]["version"], 2)
        checks = [s for s in new["sections"] if s["section_def"] == "checks"]
        self.assertNotIn("note", checks[0]["values"])
        self.assertEqual(checks[0]["values"]["fe_only"], "○")
        summary = [s for s in new["sections"] if s["section_def"] == "summary"]
        self.assertEqual(summary[0]["values"]["note"], "[행 비고] 10-11 08:40 메모")
        self.assertEqual(snapshot["template"]["version"], 1)  # 입력은 그대로


class TemplateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        setup_p4()

    def test_v2_active_v1_inactive(self):
        active = DocumentTemplate.objects.filter(type_code="CCP-3P", is_active=True)
        self.assertEqual(list(active.values_list("version", flat=True)), [2])
        self.assertTrue(DocumentTemplate.objects.filter(type_code="CCP-3P", version=1).exists())

    def test_new_document_is_v2(self):
        detail = new_ccp("CCP-3P", "3P")["document"]
        self.assertEqual(services.get_document(detail["document_id"])["template"]["version"], 2)

    def test_v2_input_and_completion_rules(self):
        document_id = new_ccp("CCP-3P", "3P")["document"]["document_id"]
        ok = {"fe_only": "○", "sts_only": "○", "product_only": "X"}
        ok.update(product_fe="○", product_sus="○")
        start = {"phase": "시작", "passed_at": at("08:40"), **ok}
        end = {"phase": "종료", "passed_at": at("17:00"), **ok, "product_only": "○"}
        patch(document_id, {"add": [{"section_def": "checks", "values": v} for v in (start, end)]})
        verdicts = [r["values"]["verdict"] for r in rows_of(document_id, "checks")]
        self.assertEqual(verdicts, ["적합", "부적합"])  # 제품만 통과에서 검출 = 부적합
        stale = {"phase": "중간", "passed_at": at("12:00"), "fe_l": "○"}
        with self.assertRaises(Exception):  # v1 키는 v2에 없음
            patch(document_id, {"add": [{"section_def": "checks", "values": stale}]})


class MigrationTests(TestCase):
    """0004 forward: v1 문서·행·결재 스냅샷 → v2."""

    @classmethod
    def setUpTestData(cls):
        setup_p4()

    def make_v1_document(self):
        v1 = DocumentTemplate.objects.get(type_code="CCP-3P", version=1)
        DocumentTemplate.objects.filter(pk=v1.pk).update(is_active=True)
        document_id = new_ccp("CCP-3P", "3P")["document"]["document_id"]
        Document.objects.filter(pk=document_id).update(template_id=v1.template_id)
        document = Document.objects.get(pk=document_id)
        rows = [
            {"phase": "시작", "passed_at": at("08:40"), **V1_OK, "note": "첫 통과"},
            {"phase": "종료", "passed_at": at("17:00"), **V1_OK, "fe_c": "X", "verdict": "부적합"},
        ]
        for n, values in enumerate(rows, start=1):
            DocSection.objects.create(
                document=document, section_def="checks", row_no=n, values_json=values
            )
        snapshot = services.get_document(document_id)
        request = ApprovalRequest.objects.create(
            document=document, attempt=1, status="approved", document_version=document.version,
            template=v1, work_date=DAY, snapshot_json=snapshot, requested_by_id=3,
            requested_at=timezone.now(), closed_at=timezone.now(),
        )  # fmt: skip
        return document, request

    def run_forward(self):
        MIGRATION.forward(django_apps, None)

    def test_forward_converts_rows_snapshot_and_template(self):
        document, request = self.make_v1_document()
        self.run_forward()
        after = Document.objects.get(pk=document.pk)
        self.assertEqual(after.template.version, 2)
        self.assertEqual(after.version, document.version + 1)
        checks = [r["values"] for r in rows_of(document.pk, "checks")]
        self.assertEqual([c["fe_only"] for c in checks], ["○", "X"])
        self.assertEqual([c["verdict"] for c in checks], ["적합", "부적합"])
        self.assertFalse(any("note" in c or "fe_l" in c for c in checks))
        summary = rows_of(document.pk, "summary")
        self.assertEqual(len(summary), 1)
        self.assertEqual(summary[0]["values"]["note"], "[행 비고] 10-11 08:40 첫 통과")
        self.assertEqual(summary[0]["values"]["item_name"], "유자차")
        request.refresh_from_db()
        self.assertEqual(request.template.version, 2)
        self.assertEqual(request.snapshot_json["template"]["version"], 2)
        snap_checks = [s for s in request.snapshot_json["sections"] if s["section_def"] == "checks"]
        self.assertEqual(snap_checks[1]["values"]["fe_only"], "X")
        self.assertFalse(DocumentTemplate.objects.get(type_code="CCP-3P", version=1).is_active)

    def test_forward_twice_is_noop(self):
        document, _ = self.make_v1_document()
        self.run_forward()
        version = Document.objects.get(pk=document.pk).version
        self.run_forward()
        self.assertEqual(Document.objects.get(pk=document.pk).version, version)

    def test_no_v1_template_does_nothing(self):
        DocumentTemplate.objects.filter(type_code="CCP-3P", version=1).delete()
        self.run_forward()
        self.assertEqual(DocumentTemplate.objects.filter(type_code="CCP-3P").count(), 1)
