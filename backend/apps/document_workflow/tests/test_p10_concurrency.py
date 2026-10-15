"""P10-TC-026: 같은 회차의 마지막 칸 승인과 상신 취소 동시(파일 DB 전용).

  HACCP_TEST_FILE_DB=1 python manage.py test apps.document_workflow.tests.test_p10_concurrency \
      --settings=config.settings.test_filedb

첫 쓰기(APR 조건부 UPDATE) 뒤 멈춘 쪽이 이기고, 다른 쪽은 409 REQUEST_CLOSED.
"""

import os
import threading
import unittest

from django.test import TransactionTestCase

from apps.approvals import errors as apr_errors
from apps.approvals import services as apr
from apps.document_workflow import services
from apps.document_workflow.tests import test_concurrency as wf_base
from apps.document_workflow.tests.base import (
    invariant_violations,
    new_document,
    setup_reference_data,
    slot_ids,
)
from apps.documents import services as doc

TWO = [
    {"slot_no": 1, "label": "담당자", "approver_id": 2},
    {"slot_no": 2, "label": "HACCP팀장", "approver_id": 1},
]


@unittest.skipUnless(
    os.environ.get("HACCP_TEST_FILE_DB") and wf_base._file_db(), "파일 SQLite 테스트 DB에서만 실행"
)
class P10CancelConcurrencyTests(TransactionTestCase):
    pause_after = wf_base.WfConcurrencyTests.pause_after
    race = wf_base.WfConcurrencyTests.race

    def setUp(self):
        self.t = setup_reference_data()
        self.locked, self.release = threading.Event(), threading.Event()
        self.calls = {}

    def tearDown(self):
        self.assertEqual(invariant_violations(), [])

    def last_slot_pending(self):
        out = services.submit(3, new_document(self.t), 2, TWO)
        ids = slot_ids(out["request"])
        services.decide(2, ids[1], "approved")
        return out["document"]["document_id"], out["request"]["request_id"], ids[2]

    def test_tc026a_approve_first(self):
        document_id, request_id, last = self.last_slot_pending()
        self.pause_after(apr, "decide")
        r = self.race(
            lambda: services.decide(1, last, "approved"),
            lambda: services.cancel_submission(3, request_id),
        )
        self.assertEqual(r["first"][0], "ok", r)
        self.assertIsInstance(r["second"][1], apr_errors.RequestClosed)
        self.assertEqual(doc.get_document(document_id)["status"], "approved")

    def test_tc026b_cancel_first(self):
        document_id, request_id, last = self.last_slot_pending()
        self.pause_after(apr, "cancel_request")
        r = self.race(
            lambda: services.cancel_submission(3, request_id),
            lambda: services.decide(1, last, "approved"),
        )
        self.assertEqual(r["first"][0], "ok", r)
        self.assertIsInstance(r["second"][1], apr_errors.RequestClosed)
        self.assertEqual(doc.get_document(document_id)["status"], "completed")
        self.assertEqual(apr.get_request(request_id)["status"], "cancelled")
