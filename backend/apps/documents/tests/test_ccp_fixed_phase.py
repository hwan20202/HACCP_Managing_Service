"""CCP 고정 시작·종료 행과 2B 시간 계산 판정."""

import importlib

from django.apps import apps as django_apps
from django.test import TestCase

from apps.documents import errors, services
from apps.documents.models import DocSection, Document
from apps.documents.tests.p4 import (
    DAY,
    at,
    filled_ccp1p,
    new_ccp,
    patch,
    rows_of,
    set_info,
    setup_p4,
    version_of,
)


class FixedPhaseTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        setup_p4()

    def test_new_ccp_has_two_unmeasured_anchor_rows(self):
        cases = (
            ("CCP-1P", "1P", "rounds", ("작업시작 전", "작업종료 후")),
            ("CCP-2B", "2B", "rounds", ("건조시작 전", "건조종료 전")),
            ("CCP-3P", "3P", "checks", ("시작", "종료")),
        )
        for code, process, section, expected in cases:
            with self.subTest(code=code):
                document_id = new_ccp(code, process, legacy=False)["document"]["document_id"]
                rows = rows_of(document_id, section)
                self.assertEqual([r["values"]["phase"] for r in rows], list(expected))
                self.assertTrue(all(r["recorded_by"] is None for r in rows))
                self.assertTrue(all("verdict" not in r["values"] for r in rows))
                if code == "CCP-3P":
                    self.assertEqual(rows_of(document_id, "summary"), [])
                measured = services.measurement_summary(DAY, [code])["documents"]
                own = next(r for r in measured if r["document_id"] == document_id)
                self.assertEqual(own["rows_by_section"][section], 0)

    def test_only_middle_can_be_added_and_anchors_cannot_change_or_delete(self):
        document_id = new_ccp(legacy=False)["document"]["document_id"]
        start, end = rows_of(document_id, "rounds")
        middle = {
            "phase": "작업 중",
            "measured_at": at("10:00"),
            "gauss": 10500,
            "rod_cleaned": "O",
        }
        patch(document_id, {"add": [{"section_def": "rounds", "values": middle}]})
        for body in (
            {"add": [{"section_def": "rounds", "values": {"phase": "작업시작 전"}}]},
            {"update": [{"section_id": start["section_id"], "values": {"phase": "작업 중"}}]},
            {"delete": [end["section_id"]]},
        ):
            with self.subTest(body=body), self.assertRaises(errors.ValidationFailed):
                patch(document_id, body)

    def test_2b_end_row_calculates_elapsed_and_two_independent_verdicts(self):
        document_id = new_ccp("CCP-2B", "2B", legacy=False)["document"]["document_id"]
        start, end = rows_of(document_id, "rounds")
        patch(
            document_id,
            {
                "update": [
                    {
                        "section_id": start["section_id"],
                        "values": {"measured_at": at("09:00"), "temp_c": 70},
                    },
                    {
                        "section_id": end["section_id"],
                        "values": {"measured_at": at("11:00"), "temp_c": 73},
                    },
                ]
            },
        )
        start, end = rows_of(document_id, "rounds")
        self.assertEqual(start["values"]["verdict"], "적합")
        self.assertNotIn("dry_minutes", start["values"])
        self.assertNotIn("time_verdict", start["values"])
        self.assertEqual(end["values"]["verdict"], "부적합")
        self.assertEqual(end["values"]["dry_minutes"], 120)
        self.assertEqual(end["values"]["time_verdict"], "적합")

    def test_2b_time_verdict_recalculates_without_changing_end_recorder(self):
        document_id = new_ccp("CCP-2B", "2B", legacy=False)["document"]["document_id"]
        start, end = rows_of(document_id, "rounds")
        patch(
            document_id,
            {
                "update": [
                    {
                        "section_id": start["section_id"],
                        "values": {"measured_at": at("09:00"), "temp_c": 70},
                    },
                    {
                        "section_id": end["section_id"],
                        "values": {"measured_at": at("11:00"), "temp_c": 70},
                    },
                ]
            },
        )
        original_end = rows_of(document_id, "rounds")[1]
        patch(
            document_id,
            {
                "update": [
                    {"section_id": start["section_id"], "values": {"measured_at": at("09:10")}}
                ]
            },
        )
        changed_end = rows_of(document_id, "rounds")[1]
        self.assertEqual(changed_end["values"]["dry_minutes"], 110)
        self.assertEqual(changed_end["values"]["time_verdict"], "부적합")
        self.assertEqual(changed_end["recorded_by"], original_end["recorded_by"])
        self.assertEqual(changed_end["recorded_at"], original_end["recorded_at"])
        summary = services.measurement_summary(DAY, ["CCP-2B"])["documents"]
        own = next(item for item in summary if item["document_id"] == document_id)
        self.assertTrue(
            any(
                reason["field"] == "dry_minutes"
                for row in own["nonconforming"]
                for reason in row["reasons"]
            )
        )

    def test_2b_rejects_manual_duration_and_reverse_time(self):
        document_id = new_ccp("CCP-2B", "2B", legacy=False)["document"]["document_id"]
        start, end = rows_of(document_id, "rounds")
        for values in ({"dry_minutes": 120}, {"time_verdict": "적합"}):
            with self.subTest(values=values), self.assertRaises(errors.ValidationFailed):
                patch(
                    document_id, {"update": [{"section_id": end["section_id"], "values": values}]}
                )
        patch(
            document_id,
            {
                "update": [
                    {
                        "section_id": start["section_id"],
                        "values": {"measured_at": at("11:00"), "temp_c": 70},
                    },
                    {
                        "section_id": end["section_id"],
                        "values": {"measured_at": at("09:00"), "temp_c": 70},
                    },
                ]
            },
        )
        set_info(document_id, {"inspector": 4})
        with self.assertRaises(errors.CompletionIncomplete) as caught:
            services.complete_document(3, document_id, version_of(document_id))
        self.assertTrue(any(p["code"] == "time_order" for p in caught.exception.details))

    def test_2b_overnight_duration_is_120_minutes(self):
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
        self.assertEqual(rows_of(document_id, "rounds")[1]["values"]["dry_minutes"], 120)

    def test_2b_time_only_nonconforming_requires_deviation(self):
        document_id = new_ccp("CCP-2B", "2B", legacy=False)["document"]["document_id"]
        start, end = rows_of(document_id, "rounds")
        patch(
            document_id,
            {
                "update": [
                    {
                        "section_id": start["section_id"],
                        "values": {"measured_at": at("09:00"), "temp_c": 70},
                    },
                    {
                        "section_id": end["section_id"],
                        "values": {"measured_at": at("10:54"), "temp_c": 70},
                    },
                ]
            },
        )
        set_info(document_id, {"inspector": 4})
        self.assertEqual(rows_of(document_id, "rounds")[1]["values"]["time_verdict"], "부적합")
        with self.assertRaises(errors.CompletionIncomplete) as caught:
            services.complete_document(3, document_id, version_of(document_id))
        self.assertTrue(any(p["code"] == "deviation_required" for p in caught.exception.details))

    def test_2b_elapsed_limit_includes_115_and_125_minutes(self):
        document_id = new_ccp("CCP-2B", "2B", legacy=False)["document"]["document_id"]
        section = next(
            s
            for s in Document.objects.get(pk=document_id).template.schema_json["sections"]
            if s["key"] == "rounds"
        )
        for end_time, minutes, verdict in (
            ("10:54", 114, "부적합"),
            ("10:55", 115, "적합"),
            ("11:05", 125, "적합"),
            ("11:06", 126, "부적합"),
        ):
            with self.subTest(end_time=end_time):
                result, issue = services.validation.elapsed_values(
                    section,
                    [
                        {"phase": "건조시작 전", "measured_at": at("09:00")},
                        {"phase": "건조종료 전", "measured_at": at(end_time)},
                    ],
                )
                self.assertIsNone(issue)
                self.assertEqual(
                    (result["dry_minutes"], result["time_verdict"]), (minutes, verdict)
                )

    def test_3p_summary_remains_addable(self):
        document_id = new_ccp("CCP-3P", "3P", legacy=False)["document"]["document_id"]
        patch(
            document_id,
            {"add": [{"section_def": "summary", "values": {"passed_qty": 10, "detected_qty": 0}}]},
        )
        self.assertEqual(len(rows_of(document_id, "summary")), 1)


class DraftMigrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        setup_p4()

    def test_draft_backfill_is_idempotent_and_completed_stays_old(self):
        draft = new_ccp("CCP-2B", "2B")["document"]["document_id"]
        old_version = Document.objects.get(pk=draft).version
        completed = filled_ccp1p()
        services.complete_document(3, completed, Document.objects.get(pk=completed).version)
        migration = importlib.import_module("apps.documents.migrations.0005_ccp_fixed_phase_rows")
        migration.forward(django_apps, None)
        self.assertEqual(Document.objects.get(pk=draft).template.version, 2)
        self.assertEqual(Document.objects.get(pk=draft).version, old_version + 1)
        self.assertEqual(
            [r["values"]["phase"] for r in rows_of(draft, "rounds")], ["건조시작 전", "건조종료 전"]
        )
        self.assertEqual(Document.objects.get(pk=completed).template.version, 1)
        migration.forward(django_apps, None)
        self.assertEqual(Document.objects.get(pk=draft).version, old_version + 1)
        start, end = DocSection.objects.filter(document_id=draft, section_def="rounds").order_by(
            "row_no"
        )
        start.values_json = {
            "phase": "건조시작 전",
            "measured_at": at("09:00"),
            "temp_c": 70,
            "dry_minutes": 0,
        }
        end.values_json = {
            "phase": "건조종료 전",
            "measured_at": at("11:00"),
            "temp_c": 70,
            "dry_minutes": 120,
        }
        start.save(update_fields=["values_json"])
        end.save(update_fields=["values_json"])
        elapsed_migration = importlib.import_module(
            "apps.documents.migrations.0006_ccp2b_elapsed_duration"
        )
        elapsed_migration.forward(django_apps, None)
        self.assertEqual(Document.objects.get(pk=draft).template.version, 3)
        self.assertEqual(Document.objects.get(pk=draft).version, old_version + 2)
        self.assertNotIn("dry_minutes", rows_of(draft, "rounds")[0]["values"])
        self.assertEqual(rows_of(draft, "rounds")[1]["values"]["dry_minutes"], 120)
        self.assertEqual(rows_of(draft, "rounds")[1]["values"]["time_verdict"], "적합")
        self.assertEqual(Document.objects.get(pk=completed).template.version, 1)
        elapsed_migration.forward(django_apps, None)
        self.assertEqual(Document.objects.get(pk=draft).version, old_version + 2)
