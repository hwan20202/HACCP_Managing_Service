"""파일 업로드 테스트 (스프린트 3, F14~F18·A11~A14·DOC-LCK-01b).

이름의 tcNNN은 document/p4-s2-spec.md 8장 DOC-TC, ftcNN은 document-files/s4-basis.md 4장 F-TC.
실제 파일은 테스트마다 임시 MEDIA_ROOT에 쓰고 지운다.
"""

import shutil
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.core import trace
from apps.documents import errors, files, flows, services
from apps.documents.models import FILE_MAX_BYTES, Document, DocumentFile, File
from apps.documents.tests.p4 import (
    PASS_INSPECTION,
    complete,
    goc,
    inspect,
    lot_ref,
    new_d03,
    setup_p4,
    version_of,
)
from apps.documents.tests.test_api import TRACE_MIDDLEWARE

PDF_HEAD = b"%PDF-1.4\n"
PNG_HEAD = b"\x89PNG\r\n\x1a\n"
JPEG_HEAD = b"\xff\xd8\xff\xe0"


def pdf(name="coa.pdf", size=1024):
    return SimpleUploadedFile(name, PDF_HEAD + b"0" * (size - len(PDF_HEAD)), "application/pdf")


def doc_id(result):
    return result["document"]["document_id"]


def d01(lot_id=88, item="유자", supplier="고흥농협"):
    return doc_id(
        goc(
            "D01",
            f"D01|lot:{lot_id}",
            lot_ref(lot_id),
            {"info": {"item_name": item, "supplier_name": supplier}},
        )
    )


def d02(lot_id=88):
    return doc_id(goc("D02", f"D02|lot:{lot_id}", lot_ref(lot_id), {"info": {"item_name": "유자"}}))


def upload(document_id, upload_file=None, actor=3):
    return files.attach_file(actor, document_id, version_of(document_id), upload_file or pdf())


def codes(ctx):
    return [d.get("reason") or d.get("code") for d in ctx.exception.details]


class MediaMixin:
    """MEDIA_ROOT를 임시 폴더로 바꾼다(실제 data/uploads를 건드리지 않음)."""

    def setUp(self):
        super().setUp()
        self.media = tempfile.mkdtemp(prefix="haccp-media-")
        self._media_override = override_settings(MEDIA_ROOT=self.media)
        self._media_override.enable()

    def tearDown(self):
        self._media_override.disable()
        shutil.rmtree(self.media, ignore_errors=True)
        super().tearDown()

    def disk_files(self):
        return sorted(p for p in Path(self.media).rglob("*") if p.is_file())


class FileTestCase(MediaMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.t = setup_p4()

    def lock(self, document_id):
        with transaction.atomic():
            return services.lock_for_review(document_id)

    def approve(self, document_id):
        """완료된 문서를 DOC 함수로 상신 잠금·승인(WF 없이 — 상태만 필요한 시험)."""
        self.lock(document_id)
        with transaction.atomic():
            services.mark_approved(document_id)

    def approved_d01(self, lot_id=88):
        document_id = d01(lot_id)
        file_id = upload(document_id)["file"]["file_id"]
        complete(document_id)
        self.approve(document_id)
        return document_id, file_id


# ---------------------------------------------------------------- F14 올리기


class AttachTests(FileTestCase):
    def test_tc160_upload(self):
        document_id = d01()
        before = version_of(document_id)
        out = upload(document_id, pdf(size=1024 * 1024))
        self.assertEqual(out["document_version"], before + 1)
        self.assertEqual(
            (out["file"]["original_name"], out["file"]["mime_type"], out["file"]["size_bytes"]),
            ("coa.pdf", "application/pdf", 1024 * 1024),
        )
        file = File.objects.get()
        self.assertEqual(DocumentFile.objects.filter(document_id=document_id).count(), 1)
        self.assertTrue(file.storage_path.startswith("files/"))
        self.assertTrue(file.storage_path.endswith(".pdf"))
        self.assertNotIn("coa", file.storage_path)  # 원래 이름은 DB에만(NFR-11)
        self.assertEqual(len(file.sha256), 64)
        self.assertEqual(self.disk_files(), [Path(self.media) / file.storage_path])

    def test_tc160_png_jpeg(self):
        document_id = d01()
        for name, head, mime in (
            ("a.PNG", PNG_HEAD, "image/png"),
            ("b.jpeg", JPEG_HEAD, "image/jpeg"),
            ("c.jpg", JPEG_HEAD, "image/jpeg"),
        ):
            with self.subTest(name=name):
                out = upload(document_id, SimpleUploadedFile(name, head + b"x" * 100))
                self.assertEqual(out["file"]["mime_type"], mime)

    def test_tc161_rejected(self):
        document_id = d01()
        cases = (
            (SimpleUploadedFile("x.exe", b"MZ" + b"0" * 10), "type"),
            (SimpleUploadedFile("fake.pdf", b"just text"), "type"),
            (SimpleUploadedFile("png.pdf", PNG_HEAD + b"0"), "type"),
            (pdf(size=FILE_MAX_BYTES + 1), "size"),
            (SimpleUploadedFile("empty.pdf", b""), "size"),
            # Django의 UploadedFile은 이름을 255자로 자른다 → 이름 검사는 그 밖의 호출자용(G1)
            (ContentFile(PDF_HEAD, name="a" * 252 + ".pdf"), "name"),
        )
        for upload_file, reason in cases:
            with self.subTest(name=upload_file.name[:20], reason=reason):
                with self.assertRaises(errors.FileRejected) as ctx:
                    upload(document_id, upload_file)
                self.assertEqual(codes(ctx), [reason])
        self.assertEqual(self.disk_files(), [])
        self.assertEqual((File.objects.count(), version_of(document_id)), (0, 1))
        out = upload(document_id, pdf(size=FILE_MAX_BYTES))  # 정확히 20MB
        self.assertEqual(out["file"]["size_bytes"], FILE_MAX_BYTES)

    def test_tc169_db_failure_removes_written_file(self):
        document_id = d01()
        with mock.patch.object(DocumentFile.objects, "create", side_effect=RuntimeError("DB")):
            with self.assertRaises(RuntimeError):
                upload(document_id)
        self.assertEqual((File.objects.count(), DocumentFile.objects.count()), (0, 0))
        self.assertEqual(self.disk_files(), [])
        self.assertEqual(version_of(document_id), 1)

    def test_tc162_locked_and_not_allowed(self):
        done = d01()
        upload(done)
        complete(done)
        with self.assertRaises(errors.DocumentLocked):
            upload(done)
        d03 = doc_id(new_d03())
        with self.assertRaises(errors.FilesNotAllowed):
            upload(d03)
        self.assertEqual(len(self.disk_files()), 1)  # 앞서 올린 1개만
        self.assertEqual(version_of(d03), 1)

    def test_upload_version_conflict_and_not_found(self):
        document_id = d01()
        with self.assertRaises(errors.VersionConflict):
            files.attach_file(3, document_id, 9, pdf())
        with self.assertRaises(errors.DocumentNotFound):
            files.attach_file(3, 99999, 1, pdf())
        self.assertEqual(self.disk_files(), [])


# ---------------------------------------------------------------- F15 연결 · F16 끊기


class LinkDetachTests(FileTestCase):
    def test_tc163_link(self):
        first, second = d01(88), d01(89)
        file_id = upload(first)["file"]["file_id"]
        out = files.link_file(3, second, version_of(second), file_id)
        self.assertEqual(out["document_version"], 2)
        self.assertEqual(DocumentFile.objects.filter(file_id=file_id).count(), 2)
        self.assertEqual(len(self.disk_files()), 1)  # 복사 없음
        with self.assertRaises(errors.FileAlreadyLinked):
            files.link_file(3, second, version_of(second), file_id)
        other = d02(90)
        foreign = upload(other)["file"]["file_id"]
        with self.assertRaises(errors.FileTemplateMismatch):
            files.link_file(3, second, version_of(second), foreign)
        with self.assertRaises(errors.FileNotFound):
            files.link_file(3, second, version_of(second), 99999)
        self.assertEqual(version_of(second), 2)  # 실패는 버전 그대로

    def test_link_not_allowed_template(self):
        file_id = upload(d01())["file"]["file_id"]
        d03 = doc_id(new_d03())
        with self.assertRaises(errors.FilesNotAllowed):
            files.link_file(3, d03, 1, file_id)

    def test_tc164_detach(self):
        a, b = d01(88), d01(89)
        shared = upload(a, pdf("shared.pdf"))["file"]["file_id"]
        files.link_file(3, b, version_of(b), shared)
        single = upload(a, pdf("single.pdf"))["file"]["file_id"]
        kept = upload(a, pdf("kept.pdf"))["file"]["file_id"]
        File.objects.filter(pk=kept).update(retained_at=timezone.now())
        with self.captureOnCommitCallbacks(execute=True):
            files.detach_file(3, a, version_of(a), shared)
        self.assertTrue(File.objects.filter(pk=shared).exists())
        with self.captureOnCommitCallbacks(execute=True):
            out = files.detach_file(3, a, version_of(a), single)
        self.assertFalse(File.objects.filter(pk=single).exists())
        with self.captureOnCommitCallbacks(execute=True):
            files.detach_file(3, a, version_of(a), kept)
        self.assertTrue(File.objects.filter(pk=kept).exists())
        self.assertEqual(out["document_version"], version_of(a) - 1)
        names = {File.objects.get(pk=i).storage_path for i in (shared, kept)}
        self.assertEqual({str(p.relative_to(self.media)) for p in self.disk_files()}, names)

    def test_tc164b_disk_delete_only_after_commit(self):
        document_id = d01()
        file_id = upload(document_id)["file"]["file_id"]
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            with self.assertRaises(RuntimeError):
                with transaction.atomic():
                    files.detach_file(3, document_id, version_of(document_id), file_id)
                    raise RuntimeError("커밋 전 오류")
        self.assertEqual(callbacks, [])
        self.assertTrue(DocumentFile.objects.filter(file_id=file_id).exists())
        self.assertEqual(len(self.disk_files()), 1)

    def test_tc165_detach_failures(self):
        document_id = d01()
        file_id = upload(document_id)["file"]["file_id"]
        other = upload(d01(89))["file"]["file_id"]
        with self.assertRaises(errors.FileNotLinked):
            files.detach_file(3, document_id, version_of(document_id), other)
        complete(document_id)
        with self.assertRaises(errors.DocumentLocked):
            files.detach_file(3, document_id, version_of(document_id), file_id)

    def test_deleted_document_link_counts(self):
        """F-002 Q4: 논리 삭제된 문서의 연결도 센다 → 실제 파일을 지우지 않는다."""
        a, b = d01(88), d01(89)
        file_id = upload(a)["file"]["file_id"]
        files.link_file(3, b, version_of(b), file_id)
        Document.objects.filter(pk=b).update(deleted_at=timezone.now(), deleted_by_id=3)
        with self.captureOnCommitCallbacks(execute=True):
            files.detach_file(3, a, version_of(a), file_id)
        self.assertTrue(File.objects.filter(pk=file_id).exists())


# ---------------------------------------------------------------- 정정 중·잠금·보존 (P6 이후)


class LifecycleTests(FileTestCase):
    def test_tc141_lock_retains(self):
        document_id = d01()
        file_id = upload(document_id)["file"]["file_id"]
        complete(document_id)
        self.lock(document_id)
        self.assertIsNotNone(File.objects.get(pk=file_id).retained_at)

    def test_ftc07_lock_keeps_existing_retention(self):
        document_id = d01()
        old = upload(document_id, pdf("old.pdf"))["file"]["file_id"]
        new = upload(document_id, pdf("new.pdf"))["file"]["file_id"]
        earlier = timezone.now() - timedelta(days=3)
        File.objects.filter(pk=old).update(retained_at=earlier)
        complete(document_id)
        record, token = trace.start("TEST", "method")
        try:
            self.lock(document_id)
        finally:
            trace.stop(token)
        self.assertEqual(File.objects.get(pk=old).retained_at, earlier)
        self.assertIsNotNone(File.objects.get(pk=new).retained_at)
        step = next(s for s in record.steps if s.step_id == "DOC-LCK-01b")
        self.assertEqual(step.detail, "보존 표시 1개")

    def test_ftc01_correcting_allows_file_changes(self):
        document_id, file_id = self.approved_d01()
        services.start_correction(3, document_id, version_of(document_id), "성적서 교체")
        v = version_of(document_id)
        new = upload(document_id, pdf("new.pdf"))["file"]["file_id"]
        other = upload(d01(89))["file"]["file_id"]
        files.link_file(3, document_id, v + 1, other)
        files.detach_file(3, document_id, v + 2, new)
        self.assertEqual(version_of(document_id), v + 3)

    def test_ftc02_submitted_and_approved_locked(self):
        document_id = d01()
        upload(document_id)
        complete(document_id)
        self.lock(document_id)
        with self.assertRaises(errors.DocumentLocked):
            upload(document_id)
        with transaction.atomic():
            services.mark_approved(document_id)
        with self.assertRaises(errors.DocumentLocked):
            upload(document_id)
        self.assertEqual(len(self.disk_files()), 1)

    def test_ftc03_file_change_blocks_correction_cancel(self):
        document_id, _ = self.approved_d01()
        services.start_correction(3, document_id, version_of(document_id), "성적서 교체")
        upload(document_id, pdf("new.pdf"))
        with self.assertRaises(errors.CorrectionHasChanges):
            services.cancel_correction(3, document_id, version_of(document_id))

    def test_ftc04_detach_retained_while_correcting(self):
        document_id, file_id = self.approved_d01()
        services.start_correction(3, document_id, version_of(document_id), "성적서 교체")
        with self.captureOnCommitCallbacks(execute=True):
            files.detach_file(3, document_id, version_of(document_id), file_id)
        self.assertFalse(DocumentFile.objects.filter(file_id=file_id).exists())
        self.assertTrue(File.objects.filter(pk=file_id).exists())
        self.assertEqual(len(self.disk_files()), 1)

    def test_ftc06_coa_hint_from_real_upload(self):
        upload(d01(88))
        d03 = doc_id(new_d03(88))
        inspect(d03, {k: v for k, v in PASS_INSPECTION.items()})
        rows = services.get_document(d03)["sections"]
        hinted = [r["hints"] for r in rows if "hints" in r]
        self.assertEqual(hinted, [{"has_coa": "유"}])

    def test_tc132_complete_with_real_upload(self):
        document_id = d01()
        with self.assertRaises(errors.CompletionIncomplete):
            complete(document_id)
        upload(document_id)
        self.assertEqual(complete(document_id)["status"], "completed")
        self.assertEqual(len(services.get_document(document_id)["files"]), 1)


# ---------------------------------------------------------------- F17 보기 · F18 검색


class OpenSearchTests(FileTestCase):
    def test_open_file(self):
        file_id = upload(d01())["file"]["file_id"]
        path, name, mime = files.open_file(file_id)
        self.assertEqual(
            (path.read_bytes()[:5], name, mime), (b"%PDF-", "coa.pdf", "application/pdf")
        )
        with self.assertRaises(errors.FileNotFound):
            files.open_file(99999)

    def test_tc168_search(self):
        a = d01(88, item="유자", supplier="고흥농협")
        b = d01(89, item="유자청", supplier="남해유자")
        c = d01(90, item="생강", supplier="고흥농협")
        fa = upload(a, pdf("a.pdf"))["file"]["file_id"]
        fb = upload(b, pdf("b.pdf"))["file"]["file_id"]
        fc = upload(c, pdf("c.pdf"))["file"]["file_id"]
        File.objects.filter(pk=fb).update(uploaded_at=timezone.now() - timedelta(days=100))
        found = files.search_files({"type_code": "D01", "item": "유자", "days": "90"})
        self.assertEqual([i["file_id"] for i in found["items"]], [fa])
        found = files.search_files({"type_code": "D01", "item": "유자", "days": "365"})
        self.assertEqual([i["file_id"] for i in found["items"]], [fa, fb])  # 최신순
        found = files.search_files({"type_code": "D01", "supplier": "고흥"})
        self.assertEqual([i["file_id"] for i in found["items"]], [fc, fa])
        self.assertEqual(
            found["items"][1]["documents"][0]["target_summary"], "LOT RM-1011-01 · 유자"
        )
        self.assertEqual(found["total"], 2)
        for bad in (
            {"type_code": "D01", "days": "0"},
            {"type_code": "D03"},
            {"type_code": "D01", "item": "x" * 51},
            {},
            {"type_code": "D01", "page": "0"},
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(errors.InvalidFilter):
                    files.search_files(bad)

    def test_search_excludes_deleted_documents(self):
        a = d01(88)
        upload(a)
        Document.objects.filter(pk=a).update(deleted_at=timezone.now(), deleted_by_id=3)
        self.assertEqual(files.search_files({"type_code": "D01"})["items"], [])

    def test_ftc_q3_unlinked_retained_file_cannot_be_linked(self):
        """F-002 Q3: 보존 표시만 남고 연결이 0개인 파일은 다른 문서에 연결하지 않는다."""
        document_id, file_id = self.approved_d01(88)
        services.start_correction(3, document_id, version_of(document_id), "성적서 교체")
        files.detach_file(3, document_id, version_of(document_id), file_id)
        target = d01(89)
        with self.assertRaises(errors.FileTemplateMismatch):
            files.link_file(3, target, version_of(target), file_id)


# ---------------------------------------------------------------- 흐름 단계(trace)


class FileFlowTests(FileTestCase):
    def ids(self, func):
        record, token = trace.start("TEST", "method")
        try:
            func()
        finally:
            trace.stop(token)
        return [s.step_id for s in record.steps]

    def test_method_flows(self):
        a, b = d01(88), d01(89)
        ids = self.ids(lambda: upload(a))
        self.assertEqual(ids, [f"DOC-FUP-0{n}" for n in range(2, 7)])
        file_id = File.objects.get().file_id
        ids = self.ids(lambda: files.link_file(3, b, version_of(b), file_id))
        self.assertEqual(ids, [f"DOC-FLK-0{n}" for n in range(2, 6)])
        ids = self.ids(lambda: files.detach_file(3, b, version_of(b), file_id))
        self.assertEqual(ids, [f"DOC-FDT-0{n}" for n in range(2, 5)])
        ids = self.ids(lambda: files.search_files({"type_code": "D01"}))
        self.assertEqual(ids, ["DOC-FSR-01", "DOC-FSR-02"])

        def conflict():
            with self.assertRaises(errors.VersionConflict):
                files.attach_file(3, a, 1, pdf())

        self.assertEqual(
            self.ids(conflict),
            ["DOC-FUP-02", "DOC-FUP-03", "DOC-FUP-04", "DOC-FUP-04a", "DOC-FUP-06a"],
        )


# ---------------------------------------------------------------- API (A11~A14)


class FileApiTestCase(FileTestCase):
    def multipart(self, document_id, upload_file=None, version=None, staff=3, **extra):
        data = {
            "file": upload_file or pdf(),
            "expected_version": version or version_of(document_id),
        }
        data.update(extra)
        headers = {} if staff is None else {"HTTP_X_STAFF_ID": str(staff)}
        return self.client.post(f"/api/v1/documents/{document_id}/files", data, **headers)

    def json_post(self, path, body, staff=3):
        import json

        return self.client.post(
            f"/api/v1/{path}",
            json.dumps(body),
            content_type="application/json",
            HTTP_X_STAFF_ID=str(staff),
        )

    def assertError(self, response, status, code):
        self.assertEqual(response.status_code, status, response.content)
        body = response.json()
        self.assertEqual((body["code"], set(body)), (code, {"code", "message", "details"}))


class FileApiTests(FileApiTestCase):
    def test_tc166_upload_view_detach(self):
        document_id = d01()
        created = self.multipart(document_id, pdf("유자_성적서_1011.pdf"))
        self.assertEqual(created.status_code, 201, created.content)
        file_id = created.json()["file"]["file_id"]
        self.assertEqual(created.json()["document_version"], 2)
        detail = self.client.get(f"/api/v1/documents/{document_id}").json()
        self.assertEqual([f["file_id"] for f in detail["files"]], [file_id])
        shown = self.client.get(f"/api/v1/files/{file_id}")
        self.assertEqual(shown.status_code, 200)
        self.assertEqual(shown["Content-Type"], "application/pdf")
        self.assertTrue(shown["Content-Disposition"].startswith("inline"))
        self.assertIn("filename*=utf-8''", shown["Content-Disposition"])
        self.assertEqual(b"".join(shown.streaming_content)[:5], b"%PDF-")
        deleted = self.client.delete(
            f"/api/v1/documents/{document_id}/files/{file_id}?expected_version=2",
            HTTP_X_STAFF_ID="3",
        )
        self.assertEqual((deleted.status_code, deleted.json()), (200, {"document_version": 3}))

    def test_upload_request_format(self):
        document_id = d01()
        self.assertError(self.multipart(document_id, staff=None), 400, "STAFF_HEADER_MISSING")
        self.assertError(self.multipart(document_id, version="x"), 400, "INVALID_REQUEST")
        self.assertError(self.multipart(document_id, note="x"), 400, "INVALID_REQUEST")
        no_file = self.client.post(
            f"/api/v1/documents/{document_id}/files",
            {"expected_version": 1},
            HTTP_X_STAFF_ID="3",
        )
        self.assertError(no_file, 400, "INVALID_REQUEST")
        rejected = self.multipart(document_id, SimpleUploadedFile("x.exe", b"MZ"))
        self.assertError(rejected, 400, "FILE_REJECTED")
        self.assertEqual(rejected.json()["details"][0]["reason"], "type")
        d03 = doc_id(new_d03())
        self.assertError(self.multipart(d03), 409, "FILES_NOT_ALLOWED")
        self.assertEqual(self.disk_files(), [])
        long_name = self.multipart(document_id, pdf("가" * 300 + ".pdf"))  # G1: Django가 자름
        self.assertEqual(long_name.status_code, 201, long_name.content)
        stored = long_name.json()["file"]["original_name"]
        self.assertEqual((len(stored), stored[-4:]), (255, ".pdf"))

    def test_tc166b_link_json(self):
        first, second = d01(88), d01(89)
        file_id = self.multipart(first).json()["file"]["file_id"]
        linked = self.json_post(
            f"documents/{second}/files", {"expected_version": 1, "link_file_id": file_id}
        )
        self.assertEqual(linked.status_code, 201, linked.content)
        foreign = self.multipart(d02(90)).json()["file"]["file_id"]
        self.assertError(
            self.json_post(
                f"documents/{second}/files", {"expected_version": 2, "link_file_id": foreign}
            ),
            409,
            "FILE_TEMPLATE_MISMATCH",
        )
        not_linked = self.client.delete(
            f"/api/v1/documents/{second}/files/{foreign}?expected_version=2", HTTP_X_STAFF_ID="3"
        )
        self.assertError(not_linked, 409, "FILE_NOT_LINKED")
        complete(second)
        locked = self.client.delete(
            f"/api/v1/documents/{second}/files/{file_id}?expected_version={version_of(second)}",
            HTTP_X_STAFF_ID="3",
        )
        self.assertError(locked, 409, "DOCUMENT_LOCKED")
        self.assertError(
            self.json_post(f"documents/{second}/files", {"expected_version": 1}),
            400,
            "INVALID_REQUEST",
        )

    def test_tc167_not_found(self):
        self.assertError(self.client.get("/api/v1/files/99999"), 404, "FILE_NOT_FOUND")
        file_id = self.multipart(d01()).json()["file"]["file_id"]
        for path in self.disk_files():
            path.unlink()
        self.assertError(self.client.get(f"/api/v1/files/{file_id}"), 404, "FILE_NOT_FOUND")

    def test_tc182_search_api(self):
        self.multipart(d01())
        found = self.client.get("/api/v1/files?type_code=D01&item=유자")
        self.assertEqual(found.status_code, 200, found.content)
        self.assertEqual(len(found.json()["items"]), 1)
        self.assertEqual(set(found.json()), {"items", "total", "page", "page_size"})
        self.assertError(
            self.client.get("/api/v1/files?type_code=D01&days=400"), 400, "INVALID_FILTER"
        )
        self.assertError(self.client.get("/api/v1/files?type_code=D01&x=1"), 400, "INVALID_REQUEST")

    def test_ftc08_no_trace_outside_dev(self):
        created = self.multipart(d01())
        self.assertNotIn("trace", created.json())
        self.assertNotIn("X-Trace-Id", created)


@override_settings(MIDDLEWARE=[*settings.MIDDLEWARE, TRACE_MIDDLEWARE])
class FileApiTraceTests(FileApiTestCase):
    def ids(self, response):
        return [s["step_id"] for s in response.json()["trace"]["steps"]]

    def test_api_flows_match(self):
        first, second = d01(88), d01(89)
        created = self.multipart(first)
        self.assertTrue(flows.matches("DOC-FUP", self.ids(created)), self.ids(created))
        file_id = created.json()["file"]["file_id"]
        linked = self.json_post(
            f"documents/{second}/files", {"expected_version": 1, "link_file_id": file_id}
        )
        self.assertTrue(flows.matches("DOC-FLK", self.ids(linked)), self.ids(linked))
        detached = self.client.delete(
            f"/api/v1/documents/{second}/files/{file_id}?expected_version=2", HTTP_X_STAFF_ID="3"
        )
        self.assertTrue(flows.matches("DOC-FDT", self.ids(detached)), self.ids(detached))
        searched = self.client.get("/api/v1/files?type_code=D01")
        self.assertTrue(flows.matches("DOC-FSR", self.ids(searched)), self.ids(searched))
        shown = self.client.get(f"/api/v1/files/{file_id}")
        self.assertIn("X-Trace-Id", shown)  # 파일 내용 응답은 헤더만(본문 변경 없음)
        self.assertEqual(b"".join(shown.streaming_content)[:5], b"%PDF-")
