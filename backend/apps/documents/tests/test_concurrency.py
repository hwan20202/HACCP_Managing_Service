"""DOC-TC-061/062: 실제 SQLite 잠금으로 동시 실행을 확인한다.

P4 §7.1: 062는 "작성 재개 vs 상신 잠금"으로 바뀌었다(수정 vs 잠금은 성립하지 않아 삭제).

메모리 DB는 연결 간 잠금 동작이 파일 DB와 다르므로, 테스트 DB가 파일일 때만 실행한다.
실행 방법(dev-notes/document/p4-s4-impl.md 참고):
  HACCP_TEST_FILE_DB=1 python manage.py test apps.documents.tests.test_concurrency \
      --settings=config.settings.test_filedb
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

    def test_tc061_same_version_second_conflicts(self):
        """같은 버전을 읽은 두 수정: 직렬 처리되고 나중 요청은 VERSION_CONFLICT (ISS-001)."""
        r1, r2 = self.rows["r1"].section_id, self.rows["r2"].section_id
        first = self.hold_inside(
            lambda: services.update_document(
                3,
                self.doc.document_id,
                {
                    "expected_version": 1,
                    "sections": {"update": [{"section_id": r1, "values": {"temp": 91}}]},
                },
            )
        )

        def second(locked, release):
            return services.update_document(
                5,  # P14 r13: 다른 사람 = 팀장 5(역할 없는 4는 잠금 전 403 — ISR-01과 같은 종류)
                self.doc.document_id,
                {
                    "expected_version": 1,
                    "sections": {"update": [{"section_id": r2, "values": {"temp": 92}}]},
                },
            )

        results = self.run_threads(first, second)
        self.assertEqual(results["first"][0], "ok", results)
        self.assertIsInstance(results["second"][1], errors.VersionConflict)
        self.assertEqual(DocSection.objects.get(pk=r1).values_json["temp"], 91)
        self.assertEqual(DocSection.objects.get(pk=r2).values_json["temp"], 87.0)

    def hold_after(self, target, step_id):
        """target이 step_id 단계(잠금 UPDATE)를 마친 직후 멈추게 한다."""
        from apps.core import trace

        original = trace.step

        def wrapper(locked, release):
            from contextlib import contextmanager

            @contextmanager
            def paused(sid, *args, **kwargs):
                with original(sid, *args, **kwargs) as s:
                    yield s
                if sid == step_id:
                    locked.set()
                    release.wait(10)

            services.step = paused
            try:
                return target()
            finally:
                services.step = original

        return wrapper

    def test_tc062_reopen_vs_lock(self):
        """P4 §7.1: completed 문서에서 작성 재개와 상신 잠금 동시 — 먼저 잠근 쪽 기준."""
        for first_is_reopen in (True, False):
            with self.subTest(first_is_reopen=first_is_reopen):
                doc, _ = make_document(self.t["ccp"], status="completed")

                def reopen():
                    return services.reopen_document(3, doc.document_id, 1)

                def lock():
                    with transaction.atomic():
                        return services.lock_for_review(doc.document_id, expected_version=1)

                if first_is_reopen:
                    first = self.hold_after(reopen, "DOC-ROP-02")
                    second = lambda _locked, _release: lock()  # noqa: E731
                else:
                    first = self.hold_after(lock, "DOC-LCK-01")
                    second = lambda _locked, _release: reopen()  # noqa: E731
                results = self.run_threads(first, second)
                self.assertEqual(results["first"][0], "ok", results)
                doc.refresh_from_db()
                if first_is_reopen:
                    self.assertIsInstance(results["second"][1], errors.DocumentLocked)
                    self.assertEqual(doc.status, "draft")
                else:
                    self.assertIsInstance(results["second"][1], errors.InvalidTransition)
                    self.assertEqual(doc.status, "submitted")
