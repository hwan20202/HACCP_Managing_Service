"""WF-TC-020~024: 실제 SQLite 잠금으로 동시 실행을 확인한다(파일 DB 전용).

  HACCP_TEST_FILE_DB=1 python manage.py test apps.document_workflow.tests.test_concurrency \
      --settings=filedb_settings

먼저 시작한 요청("first" 스레드)은 첫 쓰기 뒤 지정한 함수 안에서 멈춘 채 트랜잭션을 잡고 있고,
두 번째 요청은 그동안 SQLite 쓰기 잠금을 기다린다.
"""

import os
import threading
import unittest

from django.db import close_old_connections, connection, transaction
from django.test import TransactionTestCase

from apps.approvals import errors as apr_errors
from apps.approvals import services as apr
from apps.document_workflow import services
from apps.document_workflow.tests.base import (
    invariant_violations,
    new_document,
    setup_reference_data,
    slot_ids,
)
from apps.documents import errors as doc_errors
from apps.documents import services as doc


def _file_db():
    name = str(connection.settings_dict.get("NAME", ""))
    return "memory" not in name and name != ":memory:"


@unittest.skipUnless(
    os.environ.get("HACCP_TEST_FILE_DB") and _file_db(), "파일 SQLite 테스트 DB에서만 실행"
)
class WfConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.t = setup_reference_data()
        self.locked, self.release = threading.Event(), threading.Event()
        self.calls = {"mark_approved": 0, "mark_rejected": 0}

    def tearDown(self):
        self.assertEqual(invariant_violations(), [])

    def pause_after(self, module, name):
        """module.name을 감싸 first 스레드만 실행 후 멈추게 한다. 호출 수도 센다."""
        original = getattr(module, name)

        def wrapper(*args, **kwargs):
            result = original(*args, **kwargs)
            if name in self.calls:
                self.calls[name] += 1
            if threading.current_thread().name == "first":
                self.locked.set()
                self.release.wait(10)
            return result

        setattr(module, name, wrapper)
        self.addCleanup(setattr, module, name, original)

    def race(self, first, second):
        results = {}

        def run(name, func):
            try:
                results[name] = ("ok", func())
            except Exception as error:  # noqa: BLE001 - 결과 비교용
                results[name] = ("error", error)
                self.locked.set()
            finally:
                close_old_connections()
                connection.close()

        a = threading.Thread(target=run, args=("first", first), name="first")
        a.start()
        self.assertTrue(self.locked.wait(10))
        b = threading.Thread(target=run, args=("second", second), name="second")
        b.start()
        b.join(0.5)
        self.assertTrue(b.is_alive(), "두 번째 요청은 잠금을 기다려야 한다")
        self.release.set()
        a.join(20)
        b.join(20)
        return results

    def submitted(self):
        out = services.submit(3, new_document(self.t), 2)  # v2 = 작성완료
        return out["document"]["document_id"], slot_ids(out["request"])

    def count_mark(self):
        for name in ("mark_approved", "mark_rejected"):
            original = getattr(doc, name)

            def counter(*args, _o=original, _n=name, **kwargs):
                self.calls[_n] += 1
                return _o(*args, **kwargs)

            setattr(doc, name, counter)
            self.addCleanup(setattr, doc, name, original)

    def hold(self, func):
        """func를 바깥 트랜잭션 안에서 실행하고 잠금을 쥔 채 멈춘다(first 스레드용)."""

        def run():
            with transaction.atomic():
                result = func()
                self.locked.set()
                self.release.wait(10)
                return result

        return run

    # P4(p4-s2-spec 7.1): 작성완료 문서는 수정이 항상 DOCUMENT_LOCKED라서
    # "상신과 수정 동시"는 "상신과 작성 재개 동시"(같은 버전)로 바꾼다.
    def test_tc020a_submit_first_then_reopen(self):
        document_id = new_document(self.t)
        self.pause_after(doc, "get_document")  # 잠금(첫 쓰기) 직후 멈춤
        r = self.race(
            lambda: services.submit(3, document_id, 2),
            lambda: doc.reopen_document(3, document_id, 2),
        )
        self.assertEqual(r["first"][0], "ok", r)
        self.assertIsInstance(r["second"][1], doc_errors.InvalidTransition)

    def test_tc020b_reopen_first_then_submit(self):
        document_id = new_document(self.t)
        r = self.race(
            self.hold(lambda: doc.reopen_document(3, document_id, 2)),
            lambda: services.submit(3, document_id, 2),
        )
        self.assertEqual(r["first"][0], "ok", r)
        self.assertIsInstance(r["second"][1], doc_errors.DocumentLocked)  # 404 → 상태 → 버전
        self.assertEqual(doc.get_document(document_id)["status"], "draft")

    def test_tc021a_same_middle_slot_twice(self):
        document_id, ids = self.submitted()
        self.count_mark()
        self.pause_after(apr, "decide")
        r = self.race(
            lambda: services.decide(3, ids[1], "approved"),
            lambda: services.decide(3, ids[1], "approved"),
        )
        self.assertEqual(r["first"][1]["request_status"], "in_progress", r)
        self.assertIsInstance(r["second"][1], apr_errors.AlreadyDecided)
        self.assertEqual(self.calls, {"mark_approved": 0, "mark_rejected": 0})
        self.assertEqual(doc.get_document(document_id)["status"], "submitted")

    def test_tc021b_same_last_slot_twice(self):
        """마지막 칸: 먼저 처리가 회차를 끝내므로 APR 판정 순서상 RequestClosed가 먼저다."""
        document_id, ids = self.submitted()
        services.decide(3, ids[1], "approved")
        self.count_mark()
        self.pause_after(apr, "decide")
        r = self.race(
            lambda: services.decide(5, ids[2], "approved"),
            lambda: services.decide(5, ids[2], "approved"),
        )
        self.assertEqual(r["first"][1]["request_status"], "approved", r)
        self.assertIsInstance(r["second"][1], apr_errors.RequestClosed)
        self.assertEqual(self.calls["mark_approved"], 1)
        self.assertEqual(doc.get_document(document_id)["status"], "approved")

    def test_role_tc20_two_candidates_same_slot(self):
        """ROLE-TC-20: 같은 역할 칸을 두 후보(3·1)가 동시 승인 → 한 명만.

        결재자 = 먼저 처리한 사람, 둘째는 409 ALREADY_DECIDED.
        """
        document_id, ids = self.submitted()
        self.pause_after(apr, "decide")
        r = self.race(
            lambda: services.decide(3, ids[1], "approved"),
            lambda: services.decide(1, ids[1], "approved"),
        )
        self.assertEqual(r["first"][1]["request_status"], "in_progress", r)
        self.assertIsInstance(r["second"][1], apr_errors.AlreadyDecided)
        slot = apr.list_requests(document_id)["items"][0]["slots"][0]
        self.assertEqual((slot["approver_id"], slot["state"]), (3, "approved"))

    def test_tc022_last_two_approvals(self):
        document_id, ids = self.submitted()
        self.count_mark()
        self.pause_after(apr, "decide")
        r = self.race(
            lambda: services.decide(3, ids[1], "approved"),
            lambda: services.decide(5, ids[2], "approved"),
        )
        self.assertEqual(r["first"][1]["request_status"], "in_progress", r)
        self.assertEqual(r["second"][1]["request_status"], "approved", r)
        self.assertEqual(self.calls["mark_approved"], 1)
        self.assertEqual(doc.get_document(document_id)["status"], "approved")

    def test_tc023_reject_then_approve(self):
        document_id, ids = self.submitted()
        self.pause_after(apr, "decide")
        r = self.race(
            lambda: services.decide(5, ids[2], "rejected", "누락"),
            lambda: services.decide(3, ids[1], "approved"),
        )
        self.assertEqual(r["first"][1]["request_status"], "rejected", r)
        self.assertIsInstance(r["second"][1], apr_errors.RequestClosed)
        self.assertEqual(doc.get_document(document_id)["status"], "rejected")

    def test_tc024_double_submit(self):
        document_id = new_document(self.t)
        self.pause_after(doc, "get_document")
        r = self.race(
            lambda: services.submit(3, document_id, 2),
            lambda: services.submit(1, document_id, 2),  # 1 = 담당자이면서 팀장
        )
        self.assertEqual(r["first"][0], "ok", r)
        self.assertIsInstance(r["second"][1], doc_errors.DocumentLocked)
        self.assertEqual(len(apr.list_requests(document_id)["items"]), 1)
