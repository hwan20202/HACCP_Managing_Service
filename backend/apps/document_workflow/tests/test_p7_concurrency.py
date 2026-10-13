"""P7 동시 실행 ★ (P7-TC-017·018·040·069)와 NFR-02 50건 시간(파일 DB). 파일 DB에서만 실행한다.

HACCP_TEST_FILE_DB=1 python manage.py test apps.document_workflow.tests.test_p7_concurrency \
    --settings=config.settings.test_filedb

먼저 시작한 요청은 첫 쓰기 단계 직후 트랜잭션을 잡은 채 멈추고, 두 번째 요청은 쓰기 잠금을 기다린다.
"""

import os
import sys
import time
import unittest
from contextlib import contextmanager

from django.test import TransactionTestCase

from apps.approvals import services as apr_services
from apps.core import trace
from apps.document_workflow import services as wf
from apps.document_workflow.tests.base import invariant_violations
from apps.document_workflow.tests.p7 import d03, setup_p7, slots, sql, status_of, version_of
from apps.documents import errors
from apps.documents import services as doc
from apps.documents.signals import document_transitioned
from apps.documents.tests import test_concurrency as base


def hold_after(module, target, step_id):
    """target이 module의 step_id 단계를 처음 마친 직후 멈추게 한다(잠금을 쥔 채)."""
    original = trace.step

    def wrapper(locked, release):
        held = []

        @contextmanager
        def paused(sid, *args, **kwargs):
            with original(sid, *args, **kwargs) as s:
                yield s
            if sid == step_id and not held:
                held.append(sid)
                locked.set()
                release.wait(10)

        module.step = paused
        try:
            return target()
        finally:
            module.step = original

    return wrapper


@unittest.skipUnless(
    os.environ.get("HACCP_TEST_FILE_DB") and base._file_db(),
    "파일 SQLite 테스트 DB에서만 실행 (HACCP_TEST_FILE_DB=1)",
)
class P7ConcurrencyTests(TransactionTestCase):
    run_threads = base.ConcurrencyTests.run_threads

    def setUp(self):
        setup_p7()

    def tearDown(self):
        self.assertEqual(invariant_violations(), [])
        sql("DELETE FROM document_ref")  # managed=False라 flush 대상이 아니다(D-059 Q6)

    def test_tc017_two_approvers_same_document(self):
        shared, a_other, b_other = d03("submitted"), d03("submitted"), d03("submitted_partial")
        approved = []

        def listener(sender, **kwargs):
            if kwargs["event"] == "approved" and kwargs["document_id"] == shared["document_id"]:
                approved.append(kwargs["document_id"])

        document_transitioned.connect(listener, weak=False, dispatch_uid="test.p7.017")
        self.addCleanup(document_transitioned.disconnect, dispatch_uid="test.p7.017")

        def first():
            return wf.batch_approve(3, [shared["slots"][1], a_other["slots"][1]])

        results = self.run_threads(
            hold_after(apr_services, first, "APR-DEC-02"),
            lambda _l, _r: wf.batch_approve(1, [shared["slots"][2], b_other["slots"][2]]),
        )
        self.assertEqual(results["first"][0], "ok", results)
        self.assertEqual(results["second"][0], "ok", results)
        self.assertEqual(results["first"][1]["succeeded"], 2)
        self.assertEqual(results["second"][1]["succeeded"], 2)
        self.assertEqual(status_of(shared["document_id"])[0], "approved")
        self.assertEqual(approved, [shared["document_id"]])  # 승인 확정은 한 번

    def test_tc018_same_slot_twice(self):
        m = d03("submitted")

        def approve():
            return wf.batch_approve(3, [m["slots"][1]])

        results = self.run_threads(
            hold_after(apr_services, approve, "APR-DEC-02"), lambda _l, _r: approve()
        )
        self.assertEqual(results["first"][1]["succeeded"], 1, results)
        line = results["second"][1]["results"][0]
        self.assertEqual(line["error"]["code"], "ALREADY_DECIDED")

    def test_tc040_submit_vs_reopen(self):
        for submit_first in (True, False):
            with self.subTest(submit_first=submit_first):
                m = d03("completed")
                version = version_of(m["document_id"])
                items = [{"document_id": m["document_id"], "expected_version": version}]

                def batch_submit():
                    return wf.batch_submit(3, items, slots())

                def reopen():
                    return doc.reopen_document(3, m["document_id"], version)

                if submit_first:
                    results = self.run_threads(
                        hold_after(doc, batch_submit, "DOC-LCK-01"), lambda _l, _r: reopen()
                    )
                    self.assertEqual(results["first"][1]["succeeded"], 1, results)
                    self.assertIsInstance(results["second"][1], errors.InvalidTransition)
                    self.assertEqual(status_of(m["document_id"])[0], "submitted")
                else:
                    results = self.run_threads(
                        hold_after(doc, reopen, "DOC-ROP-02"), lambda _l, _r: batch_submit()
                    )
                    self.assertEqual(results["first"][0], "ok", results)
                    error = results["second"][1]["results"][0]["error"]
                    self.assertEqual(
                        (error["code"], error["details"][0]["code"]), ("DOCUMENT_LOCKED", "draft")
                    )
                    self.assertEqual(status_of(m["document_id"])[0], "draft")

    def test_tc069_inspector_vs_update(self):
        for inspector_first in (True, False):
            with self.subTest(inspector_first=inspector_first):
                m = d03("empty")
                version = version_of(m["document_id"])

                def inspector():
                    return doc.batch_set_inspector(
                        3, [{"document_id": m["document_id"], "expected_version": version}], 4
                    )

                def update():
                    return doc.update_document(
                        3,
                        m["document_id"],
                        {"expected_version": version, "document": {"subject": "동시 수정"}},
                    )

                if inspector_first:
                    results = self.run_threads(
                        hold_after(doc, inspector, "DOC-BIN-05"), lambda _l, _r: update()
                    )
                    self.assertEqual(results["first"][1]["succeeded"], 1, results)
                    self.assertIsInstance(results["second"][1], errors.VersionConflict)
                else:
                    results = self.run_threads(
                        hold_after(doc, update, "DOC-UPD-03"), lambda _l, _r: inspector()
                    )
                    self.assertEqual(results["first"][0], "ok", results)
                    error = results["second"][1]["results"][0]["error"]
                    self.assertEqual(error["code"], "VERSION_CONFLICT")
                self.assertEqual(version_of(m["document_id"]), version + 1)

    def test_nfr02_fifty_on_file_db(self):
        """P7-NFR-02(S4 완료 조건, Q1): 50건 일괄 승인·상신이 2초 이내인지 기록."""
        waiting = [d03("submitted_partial") for _ in range(50)]
        started = time.perf_counter()
        approved = wf.batch_approve(1, [m["slots"][2] for m in waiting])
        approve_ms = (time.perf_counter() - started) * 1000
        completed = [d03("completed") for _ in range(50)]
        items = [
            {"document_id": m["document_id"], "expected_version": version_of(m["document_id"])}
            for m in completed
        ]
        started = time.perf_counter()
        submitted = wf.batch_submit(3, items, slots())
        submit_ms = (time.perf_counter() - started) * 1000
        self.assertEqual((approved["succeeded"], submitted["succeeded"]), (50, 50))
        sys.stderr.write(
            f"\n[P7 NFR-02] 파일 DB 50건: 일괄 승인 {approve_ms:.0f} ms,"
            f" 일괄 상신 {submit_ms:.0f} ms\n"
        )
