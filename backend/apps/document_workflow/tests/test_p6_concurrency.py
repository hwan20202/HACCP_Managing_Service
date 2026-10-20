"""P6 정정 동시 실행 ★ (P6-TC-005·009·052): 실제 SQLite 잠금. 파일 DB에서만 실행한다.

HACCP_TEST_FILE_DB=1 python manage.py test apps.document_workflow.tests.test_p6_concurrency \
    --settings=config.settings.test_filedb

먼저 시작한 요청은 첫 쓰기 단계 직후 트랜잭션을 잡은 채 멈추고, 두 번째 요청은 쓰기 잠금을 기다린다.
"""

import os
import unittest

from django.test import TransactionTestCase

from apps.document_workflow import services
from apps.document_workflow.tests.base import (
    invariant_violations,
    new_document,
    setup_reference_data,
    slot_ids,
    sql,
    version_of,
)
from apps.documents import errors
from apps.documents import services as doc
from apps.documents.tests import test_concurrency as base


@unittest.skipUnless(
    os.environ.get("HACCP_TEST_FILE_DB") and base._file_db(),
    "파일 SQLite 테스트 DB에서만 실행 (HACCP_TEST_FILE_DB=1)",
)
class P6ConcurrencyTests(TransactionTestCase):
    run_threads = base.ConcurrencyTests.run_threads
    hold_after = base.ConcurrencyTests.hold_after

    def setUp(self):
        self.t = setup_reference_data()

    def tearDown(self):
        self.assertEqual(invariant_violations(), [])  # P6-TC-090

    def approved_document(self):
        document_id = new_document(self.t)
        request = services.submit(3, document_id, version_of(document_id))["request"]
        ids = slot_ids(request)
        for slot_no, actor in ((1, 3), (2, 5)):
            services.decide(actor, ids[slot_no], "approved")
        return document_id

    def open_corrections(self, document_id):
        return sql(
            "SELECT COUNT(*) FROM document_correction WHERE document_id=%s AND closed_at IS NULL",
            [document_id],
        )[0][0]

    def test_tc005_two_starts(self):
        document_id = self.approved_document()
        version = version_of(document_id)

        def start(actor):
            return lambda: doc.start_correction(actor, document_id, version, f"staff {actor}")

        results = self.run_threads(
            self.hold_after(start(3), "DOC-COR-03"),
            lambda _l, _r: start(5)(),  # P14: 5 = 팀장(R04)
        )
        self.assertEqual(results["first"][0], "ok", results)
        self.assertEqual(results["second"][0], "error")
        # 상태가 버전보다 먼저 판정된다(정정 중 = 승인 아님)
        self.assertIsInstance(results["second"][1], errors.InvalidTransition)
        self.assertEqual(self.open_corrections(document_id), 1)

    def test_tc009_cancel_vs_update(self):
        for first_is_cancel in (True, False):
            with self.subTest(first_is_cancel=first_is_cancel):
                document_id = self.approved_document()
                doc.start_correction(3, document_id, version_of(document_id), "판정 오기")
                version = version_of(document_id)

                def cancel():
                    return doc.cancel_correction(3, document_id, version)

                def update():
                    return doc.update_document(
                        3,
                        document_id,
                        {"expected_version": version, "document": {"subject": "늦은 수정"}},
                    )

                first, second = (cancel, update) if first_is_cancel else (update, cancel)
                step = "DOC-CCN-02" if first_is_cancel else "DOC-UPD-03"
                results = self.run_threads(
                    self.hold_after(first, step), lambda _l, _r, f=second: f()
                )
                self.assertEqual(results["first"][0], "ok", results)
                expected = errors.DocumentLocked if first_is_cancel else errors.VersionConflict
                self.assertIsInstance(results["second"][1], expected)
                status = doc.get_document(document_id)["status"]
                self.assertEqual(status, "approved" if first_is_cancel else "correcting")

    def test_tc052_start_vs_patch(self):
        for first_is_start in (True, False):
            with self.subTest(first_is_start=first_is_start):
                document_id = self.approved_document()
                version = version_of(document_id)

                def start():
                    return doc.start_correction(3, document_id, version, "판정 오기")

                def patch():
                    return doc.update_document(
                        3, document_id, {"expected_version": version, "document": {"subject": "x"}}
                    )

                first, second = (start, patch) if first_is_start else (patch, start)
                if first_is_start:
                    results = self.run_threads(
                        self.hold_after(first, "DOC-COR-03"), lambda _l, _r, f=second: f()
                    )
                    self.assertEqual(results["first"][0], "ok", results)
                    # 정정 중은 수정 가능 상태라 버전으로 거부된다(p6-s4a G3)
                    self.assertIsInstance(results["second"][1], errors.VersionConflict)
                else:
                    # 승인 문서는 수정 불가 — 조건부 UPDATE 0행이라 잠금을 잡지 않고 바로 거부된다
                    with self.assertRaises(errors.DocumentLocked):
                        patch()
                    start()
                self.assertEqual(doc.get_document(document_id)["status"], "correcting")
                self.assertEqual(self.open_corrections(document_id), 1)
