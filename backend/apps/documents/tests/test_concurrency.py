"""DOC-TC-061/062: 실제 SQLite 잠금으로 동시 실행을 확인한다.

메모리 DB는 연결 간 잠금 동작이 파일 DB와 다르므로, 테스트 DB가 파일일 때만 실행한다.
실행 방법(dev-notes/document/s4-impl.md 참고):
  HACCP_TEST_FILE_DB=1 python manage.py test apps.documents.tests.test_concurrency \
      --settings=config.settings.test
"""

import os
import threading
import unittest

from django.db import close_old_connections, connection, transaction
from django.test import TransactionTestCase

from apps.documents import errors, services
from apps.documents.models import DocSection
from apps.documents.tests.base import make_document, setup_reference_data


def _file_db():
    name = str(connection.settings_dict.get("NAME", ""))
    return "memory" not in name and name != ":memory:"


@unittest.skipUnless(
    os.environ.get("HACCP_TEST_FILE_DB") and _file_db(),
    "파일 SQLite 테스트 DB에서만 실행 (HACCP_TEST_FILE_DB=1)",
)
class ConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.t = setup_reference_data()
        self.doc, self.rows = make_document(self.t["ccp"])

    def run_threads(self, first, second):
        """first가 잠금을 잡은 상태에서 second를 시작하고, second가 대기하는 동안 first를 끝낸다."""
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
        self.assertTrue(b.is_alive(), "두 번째 요청은 잠금을 기다려야 한다")
        release.set()
        a.join(20)
        b.join(20)
        return results

    def hold_inside(self, target):
        """target의 검증 단계에서 잠금을 잡은 채 멈추게 한다."""
        original = services._check_staff

        def wrapper(locked, release):
            def paused(*args, **kwargs):
                locked.set()
                release.wait(10)
                return original(*args, **kwargs)

            services._check_staff = paused
            try:
                return target()
            finally:
                services._check_staff = original

        return wrapper

    def test_tc061_two_updates_serialize(self):
        r1, r2 = self.rows["r1"].section_id, self.rows["r2"].section_id
        first = self.hold_inside(
            lambda: services.update_document(
                3,
                self.doc.document_id,
                {"sections": {"update": [{"section_id": r1, "values": {"temp": 91}}]}},
            )
        )

        def second(locked, release):
            return services.update_document(
                4,
                self.doc.document_id,
                {"sections": {"update": [{"section_id": r2, "values": {"temp": 92}}]}},
            )

        results = self.run_threads(first, second)
        self.assertEqual([results[k][0] for k in ("first", "second")], ["ok", "ok"], results)
        self.assertEqual(DocSection.objects.get(pk=r1).values_json["temp"], 91)
        self.assertEqual(DocSection.objects.get(pk=r2).values_json["temp"], 92)

    def test_tc062_update_first_then_lock(self):
        first = self.hold_inside(
            lambda: services.update_document(
                3, self.doc.document_id, {"document": {"subject": "수정 후 상신"}}
            )
        )

        def second(locked, release):
            with transaction.atomic():
                return services.lock_for_review(self.doc.document_id)

        results = self.run_threads(first, second)
        self.assertEqual([results[k][0] for k in ("first", "second")], ["ok", "ok"], results)
        self.doc.refresh_from_db()
        self.assertEqual((self.doc.subject, self.doc.status), ("수정 후 상신", "submitted"))

    def test_tc062_lock_first_then_update(self):
        def first(locked, release):
            with transaction.atomic():
                result = services.lock_for_review(self.doc.document_id)
                locked.set()
                release.wait(10)
                return result

        def second(locked, release):
            return services.update_document(
                3, self.doc.document_id, {"document": {"subject": "늦은 수정"}}
            )

        results = self.run_threads(first, second)
        self.assertEqual(results["first"][0], "ok")
        self.assertIsInstance(results["second"][1], errors.DocumentLocked)
        self.doc.refresh_from_db()
        self.assertEqual((self.doc.status, self.doc.subject), ("submitted", "CCP-2B/라인A"))
