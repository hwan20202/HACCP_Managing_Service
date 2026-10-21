"""P4 동시 실행 ★ (DOC-TC-123·126·139·173): 실제 SQLite 잠금. 파일 DB에서만 실행한다.

HACCP_TEST_FILE_DB=1 python manage.py test apps.documents.tests.test_p4_concurrency \
    --settings=config.settings.test_filedb
"""

import os
import unittest

from django.db import transaction
from django.test import TransactionTestCase

from apps.documents import errors, services
from apps.documents.models import DeviationAction, DocSection, Document, DocumentRef
from apps.documents.tests import test_concurrency as base
from apps.documents.tests.p4 import (
    DAY,
    add_lot_row,
    filled_ccp1p,
    lot_ref,
    new_rows_doc,
    rows_of,
    setup_p4,
    version_of,
)


@unittest.skipUnless(
    os.environ.get("HACCP_TEST_FILE_DB") and base._file_db(),
    "파일 SQLite 테스트 DB에서만 실행 (HACCP_TEST_FILE_DB=1)",
)
class P4ConcurrencyTests(TransactionTestCase):
    run_threads = base.ConcurrencyTests.run_threads
    hold_after = base.ConcurrencyTests.hold_after

    def setUp(self):
        setup_p4()

    def tearDown(self):
        # document_ref는 managed=False라 테스트 DB flush 대상이 아니다(D-059 Q6).
        # 남아 있으면 lots 삭제가 RESTRICT로 실패하므로 먼저 지운다.
        DocumentRef.objects.all().delete()

    def test_tc123_same_record_key(self):
        def call():
            with transaction.atomic():
                out = services.get_or_create_document(3, "D01", "D01|lot:88", DAY, lot_ref(88))
                return out["created"], out["document"]["document_id"]

        results = self.run_threads(self.hold_after(call, "DOC-GOC-01"), lambda _l, _r: call())
        self.assertEqual([results[k][0] for k in ("first", "second")], ["ok", "ok"], results)
        (c1, id1), (c2, id2) = results["first"][1], results["second"][1]
        self.assertEqual(((c1, c2), id1), ((True, False), id2))
        self.assertEqual((Document.objects.count(), DocumentRef.objects.count()), (1, 1))

    def test_tc126_rows_in_parallel(self):
        d03 = new_rows_doc()["document"]["document_id"]
        for first_lot, second_lot, rows in ((88, 89, 2), (90, 90, 3)):
            with self.subTest(first=first_lot, second=second_lot):
                results = self.run_threads(
                    self.hold_after(lambda lot=first_lot: add_lot_row(d03, lot), "DOC-ARR-01"),
                    lambda _l, _r, lot=second_lot: add_lot_row(d03, lot),
                )
                self.assertEqual([results[k][0] for k in ("first", "second")], ["ok", "ok"])
                lots = DocSection.objects.filter(document_id=d03, section_def="lots").count()
                self.assertEqual(lots, rows)
        self.assertEqual(DocumentRef.objects.filter(section_id__isnull=False).count(), 3)

    def test_tc139_complete_vs_update(self):
        document_id = filled_ccp1p()
        version = version_of(document_id)

        def complete():
            return services.complete_document(3, document_id, version)

        def update():
            return services.update_document(
                3, document_id, {"expected_version": version, "document": {"subject": "늦은 수정"}}
            )

        for first, second, expected in (
            (complete, update, errors.DocumentLocked),
            (update, complete, errors.VersionConflict),
        ):
            with self.subTest(first=first.__name__):
                Document.objects.filter(pk=document_id).update(
                    status="draft", completed_at=None, completed_by=None, version=version
                )
                step = "DOC-CMP-02" if first is complete else "DOC-UPD-03"
                results = self.run_threads(
                    self.hold_after(first, step), lambda _l, _r, f=second: f()
                )
                self.assertEqual(results["first"][0], "ok", results)
                self.assertIsInstance(results["second"][1], expected)

    def test_tc173_deviation_updates(self):
        document_id = filled_ccp1p()
        deviation_id = services.create_deviation(3, document_id, {"description": "x"})[
            "deviation_id"
        ]
        results = self.run_threads(
            self.hold_after(
                # P14 r13: 먼저 고치는 사람 = CCP-1P 담당자 3(2는 역할 없음 → 403), 뒤 = 점검자 4
                lambda: services.update_deviation(3, deviation_id, 1, {"action_result": "A"}),
                "DOC-DVU-02",
            ),
            lambda _l, _r: services.update_deviation(4, deviation_id, 1, {"action_result": "B"}),
        )
        self.assertEqual(results["first"][0], "ok", results)
        self.assertIsInstance(results["second"][1], errors.VersionConflict)
        row = DeviationAction.objects.get(pk=deviation_id)
        self.assertEqual((row.action_result, row.version), ("A", 2))
        self.assertEqual(rows_of(document_id, "info")[0]["values"]["inspector"], 4)
