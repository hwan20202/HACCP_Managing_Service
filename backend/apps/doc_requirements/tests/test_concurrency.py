"""REQ 동시 실행 ★ (REQ-TC-007·008·009·013): 실제 SQLite 잠금. 파일 DB에서만 실행한다.

HACCP_TEST_FILE_DB=1 python manage.py test apps.doc_requirements.tests.test_concurrency \
    --settings=config.settings.test_filedb

호출자 흉내: 같은 트랜잭션에서 자기 쓰기(touched_at) → require_for_*. 첫 호출이 자기 쓰기 뒤에
멈춘 동안 두 번째 호출을 시작하고, 두 번째가 기다리는(또는 실패하는) 동안 첫 호출을 끝낸다.
"""

import os
import threading
import unittest

from django.db import close_old_connections, connection, transaction
from django.test import TransactionTestCase

from apps.doc_requirements import services
from apps.documents.models import Document, DocumentRef
from apps.documents.tests.test_concurrency import _file_db

from .base import cleanup_refs, d03_rows, setup_req, touch_batch, touch_lot


@unittest.skipUnless(
    os.environ.get("HACCP_TEST_FILE_DB") and _file_db(),
    "파일 SQLite 테스트 DB에서만 실행 (HACCP_TEST_FILE_DB=1)",
)
class ReqConcurrencyTests(TransactionTestCase):
    def setUp(self):
        setup_req()

    def tearDown(self):
        cleanup_refs()

    def run_pair(self, first, second, second_waits=True):
        locked, release = threading.Event(), threading.Event()
        results = {}

        def run(name, func):
            try:
                results[name] = ("ok", func(locked, release))
            except Exception as error:  # noqa: BLE001 - 결과 비교용
                results[name] = ("error", error)
            finally:
                close_old_connections()
                connection.close()

        a = threading.Thread(target=run, args=("first", first))
        a.start()
        self.assertTrue(locked.wait(10))
        b = threading.Thread(target=run, args=("second", second))
        b.start()
        b.join(0.5)
        if second_waits:
            self.assertTrue(b.is_alive(), "두 번째 호출은 첫 호출의 쓰기 잠금을 기다려야 한다")
        release.set()
        a.join(30)
        b.join(30)
        return results

    @staticmethod
    def caller(touch, target_id, call, *, hold=False, write_first=True):
        def run(locked, release):
            with transaction.atomic():
                if write_first:
                    touch(target_id)
                if hold:
                    locked.set()
                    release.wait(10)
                return call(3, target_id)

        return run

    def test_tc007_same_lot(self):
        first = self.caller(touch_lot, 88, services.require_for_lot, hold=True)
        second = self.caller(touch_lot, 88, services.require_for_lot)
        results = self.run_pair(first, second)
        self.assertEqual([results[k][0] for k in ("first", "second")], ["ok", "ok"], results)
        self.assertEqual(
            [d["result"] for d in results["first"][1]["documents"]],
            ["created", "created", "row_added"],
        )
        self.assertEqual(
            [d["result"] for d in results["second"][1]["documents"]],
            ["existing", "existing", "row_existing"],
        )
        self.assertEqual((Document.objects.count(), DocumentRef.objects.count()), (3, 3))

    def test_tc008_two_lots_same_day(self):
        first = self.caller(touch_lot, 88, services.require_for_lot, hold=True)
        second = self.caller(touch_lot, 89, services.require_for_lot)
        results = self.run_pair(first, second)
        self.assertEqual([results[k][0] for k in ("first", "second")], ["ok", "ok"], results)
        d03 = Document.objects.filter(record_key__startswith="D03|").values_list("pk", flat=True)
        self.assertEqual(len(d03), 1)
        self.assertEqual(sorted(d03_rows(d03[0])), [88, 89])

    def test_tc009_write_first_rule(self):
        # ① 두 번째가 자기 쓰기 없이(첫 SQL = 읽기) 부르면 즉시 database is locked
        first = self.caller(touch_lot, 88, services.require_for_lot, hold=True)
        second = self.caller(touch_lot, 89, services.require_for_lot, write_first=False)
        results = self.run_pair(first, second, second_waits=False)
        self.assertEqual(results["first"][0], "ok", results)
        self.assertEqual(results["second"][0], "error", results)
        self.assertIn("database is locked", str(results["second"][1]))
        cleanup_refs()
        Document.objects.all().delete()
        # ② 자기 쓰기를 먼저 하면 기다렸다가 성공
        first = self.caller(touch_lot, 88, services.require_for_lot, hold=True)
        second = self.caller(touch_lot, 89, services.require_for_lot)
        results = self.run_pair(first, second)
        self.assertEqual([results[k][0] for k in ("first", "second")], ["ok", "ok"], results)

    def test_tc013_same_batch(self):
        first = self.caller(touch_batch, 12, services.require_for_batch, hold=True)
        second = self.caller(touch_batch, 12, services.require_for_batch)
        results = self.run_pair(first, second)
        self.assertEqual([results[k][0] for k in ("first", "second")], ["ok", "ok"], results)
        self.assertEqual([d["result"] for d in results["second"][1]["documents"]], ["existing"] * 3)
        self.assertEqual(Document.objects.count(), 3)
