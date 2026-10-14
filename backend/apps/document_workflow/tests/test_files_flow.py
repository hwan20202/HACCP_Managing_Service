"""파일 업로드 통합 흐름 (스프린트 3 — document-files/s4-basis.md F-TC-05·09, ISS-009).

D01·D02(작성 요구 문서)를 파일 1개로 작성완료 → 상신 → 승인까지 진행하고, 정정 중 파일을 끊어도
승인본(결재 회차 스냅샷)의 파일을 계속 열 수 있는지 본다.
"""

import json

from django.test import TestCase

from apps.document_workflow import services
from apps.document_workflow.tests.base import (
    invariant_violations,
    setup_reference_data,
    slot_ids,
    slots,
    version_of,
)
from apps.documents.tests.p4 import goc, lot_ref, setup_p4
from apps.documents.tests.test_files import MediaMixin, pdf


class FileWorkflowTests(MediaMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.t = setup_reference_data()
        setup_p4()

    def tearDown(self):
        self.assertEqual(invariant_violations(), [])
        super().tearDown()

    def post(self, path, body, staff=3):
        return self.client.post(
            f"/api/v1/{path}",
            json.dumps(body),
            content_type="application/json",
            HTTP_X_STAFF_ID=str(staff),
        )

    def lot_document(self, code, lot_id=88):
        info = {"item_name": "유자"}
        if code == "D02":
            info["doc_kind"] = "원산지 증명"
        return goc(code, f"{code}|lot:{lot_id}", lot_ref(lot_id), {"info": info})["document"][
            "document_id"
        ]

    def upload(self, document_id, name="coa.pdf"):
        response = self.client.post(
            f"/api/v1/documents/{document_id}/files",
            {"file": pdf(name), "expected_version": version_of(document_id)},
            HTTP_X_STAFF_ID="3",
        )
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()["file"]["file_id"]

    def approve(self, document_id):
        submitted = self.post(
            f"documents/{document_id}/submit",
            {"expected_version": version_of(document_id), "slots": slots()},
        )
        self.assertEqual(submitted.status_code, 201, submitted.content)
        request = submitted.json()["request"]
        ids = slot_ids(request)
        for slot_no, actor in ((1, 3), (2, 2), (3, 1)):
            services.decide(actor, ids[slot_no], "approved")
        return request["request_id"]

    def test_ftc09_lot_documents_complete_submit_approve(self):
        for code in ("D01", "D02"):
            with self.subTest(code=code):
                document_id = self.lot_document(code)
                file_id = self.upload(document_id)
                done = self.post(
                    f"documents/{document_id}/complete",
                    {"expected_version": version_of(document_id)},
                )
                self.assertEqual(done.status_code, 200, done.content)
                request_id = self.approve(document_id)
                detail = self.client.get(f"/api/v1/approval-requests/{request_id}").json()
                self.assertEqual(detail["status"], "approved")
                self.assertEqual([f["file_id"] for f in detail["snapshot"]["files"]], [file_id])

    def test_ftc05_approved_file_survives_detach_in_correction(self):
        document_id = self.lot_document("D01")
        file_id = self.upload(document_id)
        self.post(f"documents/{document_id}/complete", {"expected_version": 2})
        request_id = self.approve(document_id)
        started = self.post(
            f"documents/{document_id}/correction",
            {"expected_version": version_of(document_id), "reason": "성적서 교체"},
        )
        self.assertEqual(started.status_code, 200, started.content)
        detached = self.client.delete(
            f"/api/v1/documents/{document_id}/files/{file_id}"
            f"?expected_version={version_of(document_id)}",
            HTTP_X_STAFF_ID="3",
        )
        self.assertEqual(detached.status_code, 200, detached.content)
        self.assertEqual(self.client.get(f"/api/v1/documents/{document_id}").json()["files"], [])
        snapshot = self.client.get(f"/api/v1/approval-requests/{request_id}").json()["snapshot"]
        self.assertEqual([f["file_id"] for f in snapshot["files"]], [file_id])
        shown = self.client.get(f"/api/v1/files/{file_id}")
        self.assertEqual(shown.status_code, 200)  # 보존 표시로 실제 파일이 남아 있다
        # 본문을 끝까지 읽어 응답을 닫는다(close() 직접 호출은 테스트 DB 연결을 닫음)
        self.assertEqual(b"".join(shown.streaming_content)[:5], b"%PDF-")
        # 새 파일로 다시 작성완료 → 재상신 → 승인
        new_file = self.upload(document_id, "new.pdf")
        self.post(
            f"documents/{document_id}/complete", {"expected_version": version_of(document_id)}
        )
        second = self.approve(document_id)
        snapshot = self.client.get(f"/api/v1/approval-requests/{second}").json()["snapshot"]
        self.assertEqual([f["file_id"] for f in snapshot["files"]], [new_file])
