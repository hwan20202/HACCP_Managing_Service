"""DOC-TC-034 / DOC-NFR-04: 문서 1만 건에서 목록 조회 500ms 이내.

시간이 걸리므로 기본 검사에서는 건너뛴다. 실행: HACCP_PERF_TESTS=1 python manage.py test ...
"""

import os
import time
import unittest
from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from apps.documents import services
from apps.documents.models import Document
from apps.documents.tests.base import setup_reference_data


@unittest.skipUnless(os.environ.get("HACCP_PERF_TESTS"), "HACCP_PERF_TESTS=1 일 때만 실행")
class ListPerformanceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        t = setup_reference_data()
        now = timezone.now()
        Document.objects.bulk_create(
            Document(
                template=t["ccp"],
                work_date=date(2026, 10, 9) - timedelta(days=n % 365),
                created_by_id=(n % 5) + 1,
                assignee_id=2,
                status="draft",
                created_at=now,
                updated_at=now,
            )
            for n in range(10_000)
        )

    def test_tc034_list_under_500ms(self):
        started = time.perf_counter()
        result = services.list_documents({"from": "2026-01-01", "to": "2026-10-09"}, 3)
        elapsed = (time.perf_counter() - started) * 1000
        self.assertEqual(len(result["items"]), 20)
        self.assertLess(elapsed, 500, f"{elapsed:.1f} ms")
        print(f"\n[perf] list_documents 1만 건: {elapsed:.1f} ms, total={result['total']}")
