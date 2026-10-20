"""P11-TC-028★: 확인자 2명이 같은 버전으로 동시 확인(파일 DB 전용).

  HACCP_TEST_FILE_DB=1 python manage.py test apps.documents.tests.test_p11_concurrency \
      --settings=config.settings.test_filedb

첫 쓰기(조건부 UPDATE) 뒤 멈춘 쪽이 이기고, 다른 쪽은 409 ALREADY_CHECKED.
"""

import os
import unittest

from django.test import TransactionTestCase

from apps.documents import errors, services
from apps.documents.models import DeviationAction, DocumentRef
from apps.documents.tests import test_concurrency as base

from .p11 import ccp_doc, deviation, setup_p11


@unittest.skipUnless(
    os.environ.get("HACCP_TEST_FILE_DB") and base._file_db(),
    "파일 SQLite 테스트 DB에서만 실행 (HACCP_TEST_FILE_DB=1)",
)
class P11CheckConcurrencyTests(TransactionTestCase):
    run_threads = base.ConcurrencyTests.run_threads
    hold_after = base.ConcurrencyTests.hold_after

    def setUp(self):
        setup_p11()

    def tearDown(self):
        DocumentRef.objects.all().delete()  # managed=False — flush 대상이 아님(P4 테스트와 같음)

    def test_tc028_two_checkers(self):
        x = deviation(ccp_doc("CCP-1P", 12), checkers=(3, 5))

        def check(actor):
            return services.check_deviation(actor, x["deviation_id"], 1)

        results = self.run_threads(
            self.hold_after(lambda: check(3), "DOC-DVK-02"), lambda _l, _r: check(5)
        )
        self.assertEqual(results["first"][0], "ok", results)
        self.assertEqual(results["second"][0], "error", results)
        self.assertIsInstance(results["second"][1], errors.AlreadyChecked)
        row = DeviationAction.objects.get(pk=x["deviation_id"])
        self.assertEqual((row.checked_by_id, row.version), (3, 2))
