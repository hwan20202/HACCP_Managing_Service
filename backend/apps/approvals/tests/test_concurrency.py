"""APR-TC-021/022: 실제 SQLite 잠금으로 동시 결재를 확인한다(파일 DB 전용).

  HACCP_TEST_FILE_DB=1 python manage.py test apps.approvals.tests.test_concurrency \
      --settings=filedb_settings
"""

import copy
import os
import threading
import unittest

from django.db import close_old_connections, connection, transaction
from django.test import TransactionTestCase

from apps.approvals import errors, services
from apps.approvals.models import ApprovalRequest
from apps.approvals.tests.base import (
    SLOTS,
    ensure_staff,
    make_document,
    make_template,
    ref,
    snapshot_for,
)


def _file_db():
    name = str(connection.settings_dict.get("NAME", ""))
    return "memory" not in name and name != ":memory:"


@unittest.skipUnless(
    os.environ.get("HACCP_TEST_FILE_DB") and _file_db(), "파일 SQLite 테스트 DB에서만 실행"
)
class DecideConcurrencyTests(TransactionTestCase):
    def setUp(self):
        ensure_staff()
        tpl = make_template()
        doc = make_document(tpl)
        with transaction.atomic():
            self.req = services.open_request(
                ref(doc, tpl), snapshot_for(doc), 3, copy.deepcopy(SLOTS)
            )
            self.ids = {s["slot_no"]: s["approval_id"] for s in self.req["slots"]}
            services.decide(self.ids[1], 3, "approved")

    def race(self, first, second):
        """first는 decide 후 트랜잭션을 열어 둔 채 멈추고, second는 그동안 잠금을 기다린다."""
        locked, release, results = threading.Event(), threading.Event(), {}

        def run(name, func, hold):
            try:
                with transaction.atomic():
                    results[name] = ("ok", func())
                    if hold:
                        locked.set()
                        release.wait(10)
            except Exception as error:  # noqa: BLE001 - 결과 비교용
                results[name] = ("error", error)
                locked.set()
            finally:
                close_old_connections()
                connection.close()

        a = threading.Thread(target=run, args=("first", first, True))
        a.start()
        self.assertTrue(locked.wait(10))
        b = threading.Thread(target=run, args=("second", second, False))
        b.start()
        b.join(0.5)
        self.assertTrue(b.is_alive(), "두 번째 결재는 잠금을 기다려야 한다")
        release.set()
        a.join(20)
        b.join(20)
        return results

    def test_tc021_last_two_approvals(self):
        r = self.race(
            lambda: services.decide(self.ids[2], 2, "approved"),
            lambda: services.decide(self.ids[3], 1, "approved"),
        )
        self.assertEqual(r["first"][0], "ok", r)
        self.assertEqual(r["second"][0], "ok", r)
        self.assertEqual(r["first"][1]["request_status"], "in_progress")
        self.assertEqual(
            (r["second"][1]["request_status"], r["second"][1]["pending_count"]), ("approved", 0)
        )
        self.assertEqual(ApprovalRequest.objects.get(pk=self.req["request_id"]).status, "approved")

    def test_tc022_reject_then_approve(self):
        r = self.race(
            lambda: services.decide(self.ids[2], 2, "rejected", "누락"),
            lambda: services.decide(self.ids[3], 1, "approved"),
        )
        self.assertEqual(r["first"][1]["request_status"], "rejected")
        self.assertEqual(r["second"][0], "error")
        self.assertIsInstance(r["second"][1], errors.RequestClosed)
        self.assertEqual(ApprovalRequest.objects.get(pk=self.req["request_id"]).status, "rejected")
