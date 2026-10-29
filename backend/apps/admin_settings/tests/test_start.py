"""P16 B1(D-268 a): 실제 수불 생산 시작 경로에서의 CCP 적용 기록 — 기록·롤백.

운영에서 작성 요구(require_for_batch)는 수불 `start_batch`(생산 시작)와
시작 없이 완료할 때만 불린다.
"""

from unittest import mock

from django.db import transaction
from django.utils import timezone

from apps.admin_settings.models import BatchCcpApplied, ItemCcp
from apps.core.http import ApiError
from apps.documents import services as doc
from apps.documents.models import Document
from apps.inventory.models import BatchStatus, ProductionBatch
from apps.inventory.production import start_batch
from apps.inventory.test_production import ProductionTestCase


class StartBatchTests(ProductionTestCase):
    def setUp(self):
        self.receive(self.raw, "10", "p16-raw")
        ItemCcp.objects.create(item=self.semi, mode="own", ccp_2b=True, updated_at=timezone.now())

    def test_start_records_item_setting(self):
        batch = self.batch(self.semi)
        self.assertFalse(BatchCcpApplied.objects.filter(batch_id=batch.pk).exists())  # 계획 배치
        start_batch(batch_id=batch.pk, staff_id=self.staff.pk)
        self.assertEqual(BatchCcpApplied.objects.get(batch_id=batch.pk).processes, ["2B"])
        codes = set(Document.objects.values_list("template__type_code", flat=True))
        self.assertEqual(codes & {"CCP-1P", "CCP-2B", "CCP-3P"}, {"CCP-2B"})

    def test_start_failure_rolls_back_record(self):
        batch = self.batch(self.semi)
        failing = mock.patch.object(
            doc, "get_or_create_document", side_effect=ApiError("시험 실패", code="TEST_FAIL")
        )
        with failing, self.assertRaises(ApiError), transaction.atomic():
            start_batch(batch_id=batch.pk, staff_id=self.staff.pk)
        self.assertFalse(BatchCcpApplied.objects.filter(batch_id=batch.pk).exists())
        batch = ProductionBatch.objects.get(pk=batch.pk)
        self.assertEqual(batch.status, BatchStatus.PLANNED)
