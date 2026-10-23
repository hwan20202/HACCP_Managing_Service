"""CCP-1P v3 자력 기준과 작성중 이관."""

import importlib

from django.apps import apps as django_apps
from django.test import TestCase
from django.utils import timezone

from apps.documents.models import DocSection, Document, DocumentTemplate
from apps.documents.tests.p4 import at, new_ccp, patch, rows_of, setup_p4

MIGRATION = importlib.import_module("apps.documents.migrations.0007_ccp1p_gauss_8000")


class Ccp1pGauss8000Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        setup_p4()

    def test_new_template_boundary_and_cleaning(self):
        document_id = new_ccp(legacy=False)["document"]["document_id"]
        self.assertEqual(Document.objects.get(pk=document_id).template.version, 3)
        self.assertEqual(
            list(
                DocumentTemplate.objects.filter(type_code="CCP-1P", is_active=True).values_list(
                    "version", flat=True
                )
            ),
            [3],
        )
        start = rows_of(document_id, "rounds")[0]
        for gauss, cleaned, verdict in (
            (7999, "O", "부적합"),
            (8000, "O", "적합"),
            (9999, "O", "적합"),
            (8000, "X", "부적합"),
        ):
            with self.subTest(gauss=gauss, cleaned=cleaned):
                patch(
                    document_id,
                    {
                        "update": [
                            {
                                "section_id": start["section_id"],
                                "values": {"gauss": gauss, "rod_cleaned": cleaned},
                            }
                        ]
                    },
                )
                self.assertEqual(rows_of(document_id, "rounds")[0]["values"]["verdict"], verdict)
        guide = Document.objects.get(pk=document_id).template.schema_json["guide"][0]["rows"][0][1]
        self.assertIn("자력 8,000 가우스 이상", guide)
        self.assertIn("자석봉 Φ42.7 사용", guide)
        old = DocumentTemplate.objects.get(type_code="CCP-1P", version=2).schema_json
        self.assertIn("자력 10,000 가우스 이상", old["guide"][0]["rows"][0][1])

    def test_draft_migration_recomputes_verdict_and_is_idempotent(self):
        document_id = new_ccp(legacy=False)["document"]["document_id"]
        old = DocumentTemplate.objects.get(type_code="CCP-1P", version=2)
        Document.objects.filter(pk=document_id).update(template_id=old.pk)
        row = DocSection.objects.get(pk=rows_of(document_id, "rounds")[0]["section_id"])
        recorded_at = timezone.now()
        row.values_json = {
            "phase": "작업시작 전",
            "measured_at": at("08:50"),
            "gauss": 9800,
            "rod_cleaned": "O",
            "verdict": "부적합",
        }
        row.recorded_by_id = 3
        row.recorded_at = recorded_at
        row.save(update_fields=["values_json", "recorded_by", "recorded_at"])
        before = Document.objects.get(pk=document_id).version

        MIGRATION.forward(django_apps, None)
        document = Document.objects.get(pk=document_id)
        row.refresh_from_db()
        self.assertEqual((document.template.version, document.version), (3, before + 1))
        self.assertEqual(row.values_json["verdict"], "적합")
        self.assertEqual((row.recorded_by_id, row.recorded_at), (3, recorded_at))
        MIGRATION.forward(django_apps, None)
        self.assertEqual(Document.objects.get(pk=document_id).version, before + 1)
