"""파일 업로드 동시 실행 ★ (document-files/s4-basis.md F-TC-10): 실제 SQLite 잠금. 파일 DB에서만.

HACCP_TEST_FILE_DB=1 python manage.py test apps.documents.tests.test_files_concurrency \
    --settings=config.settings.test_filedb
"""

import os
import unittest
from contextlib import contextmanager

from django.test import TransactionTestCase

from apps.core import trace
from apps.documents import errors, files, services
from apps.documents.models import DocumentRef, File
from apps.documents.tests import test_concurrency as base
from apps.documents.tests.p4 import setup_p4, version_of
from apps.documents.tests.test_files import MediaMixin, d01, pdf


def hold_after(target, step_id):
    """target이 step_id 단계를 마친 직후 멈춘다. services·files 두 모듈의 step을 함께 바꾼다."""
    original = trace.step

    def wrapper(locked, release):
        @contextmanager
        def paused(sid, *args, **kwargs):
            with original(sid, *args, **kwargs) as s:
                yield s
            if sid == step_id:
                locked.set()
                release.wait(10)

        services.step = files.step = paused
        try:
            return target()
        finally:
            services.step = files.step = original

    return wrapper


@unittest.skipUnless(
    os.environ.get("HACCP_TEST_FILE_DB") and base._file_db(),
    "파일 SQLite 테스트 DB에서만 실행 (HACCP_TEST_FILE_DB=1)",
)
class FileConcurrencyTests(MediaMixin, TransactionTestCase):
    run_threads = base.ConcurrencyTests.run_threads

    def setUp(self):
        super().setUp()
        setup_p4()

    def tearDown(self):
        DocumentRef.objects.all().delete()  # managed=False(D-059 Q6)
        super().tearDown()

    def test_ftc10_upload_vs_update(self):
        for first_name in ("upload", "update"):
            with self.subTest(first=first_name):
                document_id = d01(88 if first_name == "upload" else 89)
                version = version_of(document_id)

                def upload():
                    return files.attach_file(3, document_id, version, pdf())

                def update():
                    return services.update_document(
                        3, document_id, {"expected_version": version, "document": {"subject": "x"}}
                    )

                first, second = (upload, update) if first_name == "upload" else (update, upload)
                step = "DOC-FUP-04" if first is upload else "DOC-UPD-03"
                results = self.run_threads(hold_after(first, step), lambda _l, _r: second())
                self.assertEqual(results["first"][0], "ok", results)
                self.assertIsInstance(results["second"][1], errors.VersionConflict)
                self.assertEqual(version_of(document_id), version + 1)
        # 업로드가 진 쪽(두 번째 경우)은 쓴 파일을 지웠다 → 디스크에는 이긴 업로드 1개만
        self.assertEqual(File.objects.count(), 1)
        self.assertEqual(len(self.disk_files()), 1)
