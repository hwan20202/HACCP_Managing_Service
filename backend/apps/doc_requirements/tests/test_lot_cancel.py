"""D-178 입고 취소 → 입고 서류 연쇄 소프트 딜리트(REQ F12 · DOC N10 · APR A13)와 취소 LOT 조회.

이름의 tcNNN은 LC-TC ID(dev-notes/doc-requirements/lot-cancel-s4.md 4장).
"""

from django.db import connection, transaction
from django.test import TestCase

from apps.approvals.models import Approval, ApprovalRequest
from apps.core import trace as tracing
from apps.doc_requirements import errors, flows, services
from apps.document_workflow import services as wf
from apps.document_workflow.tests.base import invariant_violations
from apps.documents import services as doc
from apps.documents.models import Document, DocumentCorrection
from apps.staff.services import InvalidStaff

from .base import DAY, by_type, detail, in_tx, set_status, setup_req
from .test_services import SLOTS, approve_d03, lot


def cancel_receipt(lot_id):
    """수불 입고 취소 흉내(receipt_status = CANCELLED — 수불 cancel_receipt와 같은 열)."""
    with connection.cursor() as c:
        c.execute(
            "UPDATE incoming_receipts SET receipt_status = 'CANCELLED',"
            " cancelled_at = datetime('now', 'localtime'), cancel_reason = '시험'"
            " WHERE lot_id = %s",
            [lot_id],
        )


def delete(lot_id, actor=3):
    return in_tx(services.delete_lot_documents, actor, lot_id)


def submit(document_id):
    set_status(document_id, "completed")
    with transaction.atomic():
        return wf.submit(3, document_id, detail(document_id)["version"], [dict(s) for s in SLOTS])


class LotCancelTestCase(TestCase):
    def setUp(self):
        setup_req()

    def tearDown(self):
        self.assertEqual(invariant_violations(), [])


class DeleteLotDocumentsTests(LotCancelTestCase):
    def test_tc001_drafts(self):
        ids = {k: v["document_id"] for k, v in by_type(lot(88)).items()}
        other = by_type(lot(89))["D01"]["document_id"]
        cancel_receipt(88)
        out = delete(88)
        self.assertEqual(
            [(d["type_code"], d["status"], d["result"]) for d in out["documents"]],
            [("D01", "draft", "deleted"), ("D02", "draft", "deleted"), ("D03", "draft", "deleted")],
        )
        self.assertEqual((out["closed_requests"], out["closed_corrections"]), (0, 0))
        self.assertEqual(out["lot"]["receipt_status"], "CANCELLED")
        rows = Document.objects.filter(pk__in=ids.values()).values_list("deleted_by_id", "version")
        self.assertEqual(sorted(rows), [(3, 2), (3, 2), (3, 2)])
        # 요구 키는 그대로(D-178 Q4 a) · 다른 LOT 문서는 그대로
        self.assertEqual(Document.objects.get(pk=ids["D01"]).record_key, "D01|lot:88")
        self.assertIsNone(Document.objects.get(pk=other).deleted_at)

    def test_tc002_with_history(self):
        """Q1 b: 결재 중·승인·정정 중·반려 문서도 지움 — 진행 중 회차는 닫고 정정도 닫음."""
        ids = {k: v["document_id"] for k, v in by_type(lot(88)).items()}
        approve_d03(ids["D03"], "PASS")
        with transaction.atomic():
            doc.start_correction(3, ids["D03"], detail(ids["D03"])["version"], "판정 재확인")
        open_req = submit(ids["D01"])["request"]
        rejected = submit(ids["D02"])["request"]
        with transaction.atomic():
            wf.decide(3, rejected["slots"][0]["approval_id"], "rejected", "다시")
        approved_before = ApprovalRequest.objects.filter(status="approved").count()
        total_before = ApprovalRequest.objects.count()
        out = delete(88)
        self.assertEqual(
            {d["type_code"]: (d["status"], d["result"]) for d in out["documents"]},
            {
                "D01": ("submitted", "deleted"),
                "D02": ("rejected", "deleted"),
                "D03": ("correcting", "deleted"),
            },
        )
        self.assertEqual((out["closed_requests"], out["closed_corrections"]), (1, 1))
        req = ApprovalRequest.objects.get(pk=open_req["request_id"])
        self.assertEqual(req.status, "cancelled")
        self.assertIsNotNone(req.closed_at)
        self.assertEqual(
            list(Approval.objects.filter(request_id=req.pk).values_list("state", flat=True)),
            ["skipped", "skipped"],
        )
        # 결재 회차·승인 기록·스냅샷은 남김
        self.assertEqual(ApprovalRequest.objects.count(), total_before)
        self.assertEqual(ApprovalRequest.objects.filter(status="approved").count(), approved_before)
        c = DocumentCorrection.objects.get(document_id=ids["D03"])
        self.assertEqual((c.outcome, c.closed_at is not None), ("cancelled", True))
        self.assertEqual(Document.objects.filter(pk__in=ids.values(), deleted_at=None).count(), 0)

    def test_tc003_twice_and_receipt_not_checked(self):
        lot(88)
        first = delete(88)  # Q2 b: 입고 상태를 보지 않음(취소 전에도 지움)
        again = delete(88)
        self.assertEqual({d["result"] for d in first["documents"]}, {"deleted"})
        self.assertEqual(again["documents"], [])  # N3는 지운 문서를 빼고 찾음
        self.assertEqual((again["closed_requests"], again["closed_corrections"]), (0, 0))

    def test_tc004_input_errors(self):
        with self.assertRaises(errors.ValidationFailed):
            delete("88")
        with self.assertRaises(InvalidStaff):
            delete(88, actor=999)
        with self.assertRaises(errors.LotNotFound):
            delete(9999)
        with self.assertRaises(errors.LotNotIncoming):
            delete(90)

    def test_tc005_no_documents(self):
        out = delete(89)  # 입고 LOT이지만 문서를 아직 안 만듦
        self.assertEqual(out["documents"], [])

    def test_tc006_flow(self):
        lot(88)
        current, token = tracing.start()
        try:
            delete(88)
        finally:
            tracing.stop(token)
        steps = [s.step_id for s in current.steps]
        self.assertTrue(flows.matches("REQ-DEL", steps), steps)
        self.assertIn("APR-SYS-01", steps)
        self.assertIn("DOC-SDL-03", steps)

    def test_tc007_pending_deviation_hidden(self):
        d03 = by_type(lot(88))["D03"]["document_id"]
        with transaction.atomic():
            dv = doc.create_deviation(
                3, d03, {"description": "포장 파손", "action_result": "반품", "checker_ids": [4]}
            )
        set_status(d03, "completed")  # 일반 양식은 작성완료 뒤 확인 대기에 나옴(S1a-Q5 a)
        before = doc.pending_deviations(4, DAY)
        delete(88)
        after = doc.pending_deviations(4, DAY)
        ids = lambda out: {r["deviation_id"] for r in out["rows"]}  # noqa: E731
        self.assertIn(dv["deviation_id"], ids(before))
        self.assertNotIn(dv["deviation_id"], ids(after))


class CancelledLotReadTests(LotCancelTestCase):
    """취소된(소프트 딜리트) LOT은 입고 서류 조회에서 없는 LOT — LOT_NOT_FOUND."""

    def test_tc010_docs_for_lot(self):
        lot(88)
        self.assertEqual(len(services.docs_for_lot(88)["documents"]), 3)
        cancel_receipt(88)
        with self.assertRaises(errors.LotNotFound):
            services.docs_for_lot(88)

    def test_tc011_require_for_lot(self):
        cancel_receipt(88)
        with self.assertRaises(errors.LotNotFound):
            lot(88)
        self.assertEqual(Document.objects.filter(record_key__startswith="D01|lot:88").count(), 0)

    def test_tc012_bundle_excludes_cancelled(self):
        lot(88)
        lot(89)
        cancel_receipt(88)
        out = services.incoming_bundle(3, DAY)
        self.assertEqual([x["lot_id"] for x in out["lots"]], [89])

    def test_tc013_api_404(self):
        lot(88)
        cancel_receipt(88)
        response = self.client.get("/api/v1/lots/88/documents", HTTP_X_STAFF_ID="3")
        self.assertEqual((response.status_code, response.json()["code"]), (404, "LOT_NOT_FOUND"))


class DeleteLotDocumentsMoreTests(LotCancelTestCase):
    """S4 검증 보강(사용자 요청 — 화면 확인이 없어 테스트로 다시 확인)."""

    def ids(self, lot_id):
        return {k: v["document_id"] for k, v in by_type(lot(lot_id)).items()}

    def test_tc008_approved_completed_and_cancelled_submission(self):
        """승인(정정 없음) · 작성완료(상신 안 함) · 상신 취소 뒤 작성 재개(draft)도 지움."""
        ids = self.ids(88)
        approve_d03(ids["D03"], "PASS")
        set_status(ids["D02"], "completed")
        req = submit(ids["D01"])["request"]
        with transaction.atomic():
            wf.cancel_submission(3, req["request_id"])
        with transaction.atomic():
            doc.reopen_document(3, ids["D01"], detail(ids["D01"])["version"])
        statuses = {k: Document.objects.get(pk=v).status for k, v in ids.items()}
        self.assertEqual(statuses, {"D01": "draft", "D02": "completed", "D03": "approved"})
        out = delete(88)
        self.assertEqual({d["result"] for d in out["documents"]}, {"deleted"})
        self.assertEqual(out["closed_requests"], 0)  # 상신 취소된 회차는 이미 닫혀 있음
        self.assertEqual(Document.objects.filter(pk__in=ids.values(), deleted_at=None).count(), 0)

    def test_tc009_partial_decisions_kept_snapshot_kept(self):
        """진행 중 회차의 승인한 칸은 그대로, 대기 칸만 skipped · 승인 회차 스냅샷 그대로."""
        ids = self.ids(88)
        approve_d03(ids["D03"], "PASS")
        approved = ApprovalRequest.objects.get(document_id=ids["D03"], status="approved")
        snapshot = approved.snapshot_json
        req = submit(ids["D01"])["request"]
        first = req["slots"][0]["approval_id"]
        with transaction.atomic():
            wf.decide(3, first, "approved")
        delete(88)
        states = dict(
            Approval.objects.filter(request_id=req["request_id"]).values_list("slot_no", "state")
        )
        self.assertEqual(states, {1: "approved", 2: "skipped"})
        approved.refresh_from_db()
        self.assertEqual((approved.status, approved.snapshot_json), ("approved", snapshot))

    def test_tc014_inbox_and_decide_after_delete(self):
        """닫힌 회차는 결재함 대기에서 빠지고, 남은 칸을 승인하려 하면 거부."""
        ids = self.ids(88)
        req = submit(ids["D01"])["request"]
        second = req["slots"][1]["approval_id"]
        pending = lambda: [  # noqa: E731
            i["request"]["request_id"] for i in apr_inbox(1)["items"]
        ]
        self.assertIn(req["request_id"], pending())
        delete(88)
        self.assertNotIn(req["request_id"], pending())
        from apps.core.http import ApiError

        with self.assertRaises(ApiError):
            with transaction.atomic():
                wf.decide(1, second, "approved")
        self.assertEqual(Approval.objects.get(pk=second).state, "skipped")

    def test_tc015_rollback_all_or_nothing(self):
        """같은 트랜잭션에서 뒤에 오류가 나면(수불 쪽 롤백) 문서·회차·정정 모두 그대로."""
        ids = self.ids(88)
        req = submit(ids["D01"])["request"]
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                services.delete_lot_documents(3, 88)
                raise RuntimeError("수불 쪽 뒤 단계 실패")
        self.assertEqual(Document.objects.filter(pk__in=ids.values(), deleted_at=None).count(), 3)
        self.assertEqual(ApprovalRequest.objects.get(pk=req["request_id"]).status, "in_progress")

    def test_tc016_deleted_documents_disappear_everywhere(self):
        """지운 문서: 상세 404 · 목록·작성 필요·LOT 문서 찾기에서 빠짐 · 파일 연결 행은 남음."""
        from apps.doc_requirements import todo
        from apps.documents import errors as doc_errors
        from apps.documents.models import DocumentFile

        ids = self.ids(88)
        keep = self.ids(89)
        files_before = DocumentFile.objects.filter(document_id__in=ids.values()).count()

        def todo_ids():
            out = todo.todo_list(3, DAY)
            rows = [r for g in out["groups"] for r in g["rows"] + g["past"]["rows"]]
            rows += out["awaiting_submit"]["rows"]
            got = {r.get("document_id") for r in rows}
            for r in rows:  # D03 묶음 줄은 묶음 안 문서 id 목록을 가짐
                got |= set((r.get("bundle") or {}).get("document_ids") or [])
            return got

        def listed():
            items = doc.list_documents({"from": DAY, "to": DAY})["items"]
            one = {d["document_id"] for d in items if "document_id" in d}
            d03 = sum(
                d["count"] for d in items if d.get("kind") == "bundle" and d["type_code"] == "D03"
            )
            return one, d03

        self.assertTrue(todo_ids() & set(ids.values()))  # 지우기 전에는 작성 필요에 있음(양성 대조)
        one_before, d03_before = listed()
        self.assertTrue({ids["D01"], ids["D02"]} <= one_before)
        delete(88)
        with self.assertRaises(doc_errors.DocumentNotFound):
            doc.get_document(ids["D01"])
        one_after, d03_after = listed()
        self.assertFalse(one_after & set(ids.values()))
        self.assertTrue({keep["D01"], keep["D02"]} <= one_after)
        self.assertEqual(d03_after, d03_before - 1)  # D03는 입고일 묶음 줄 — 지운 1건만 빠짐
        self.assertFalse(todo_ids() & set(ids.values()))
        found = doc.find_documents_by_lots([88, 89], ["D03"])
        self.assertEqual({r["lot_id"] for r in found}, {89})
        self.assertEqual(
            DocumentFile.objects.filter(document_id__in=ids.values()).count(), files_before
        )

    def test_tc017_lot_without_receipt_and_completed_receipt(self):
        """입고 건 없는 LOT(기초재고 흉내)은 LOT_NOT_FOUND 그대로, 취소 안 된 입고는 조회됨."""
        with connection.cursor() as c:
            c.execute("DELETE FROM incoming_receipts WHERE lot_id = 91")
        with self.assertRaises(errors.LotNotFound):
            services.docs_for_lot(91)
        lot(88)
        self.assertEqual(services.docs_for_lot(88)["lot"]["received_date"], DAY)


def apr_inbox(actor_id):
    from apps.approvals import services as apr

    return apr.list_inbox(actor_id, "pending")


class DevLotListTests(LotCancelTestCase):
    """개발 LOT 목록(REQ-D01)이 취소 LOT 때문에 통째로 실패하지 않음(S4 검증 중 발견 — r1)."""

    def test_tc018_dev_lot_list_with_cancelled(self):
        from django.conf import settings
        from django.test import override_settings

        lot(88)
        lot(89)
        cancel_receipt(88)
        with override_settings(
            ROOT_URLCONF="apps.devtools.test_urls",
            MIDDLEWARE=[*settings.MIDDLEWARE, "apps.devtools.middleware.TraceMiddleware"],
        ):
            res = self.client.get(f"/api/dev/req/lots?date={DAY}", HTTP_X_STAFF_ID="3")
        self.assertEqual(res.status_code, 200, res.content)
        rows = {x["lot_id"]: x for x in res.json()["items"]}
        self.assertEqual((rows[88]["receipt_status"], rows[88]["documents"]), ("CANCELLED", []))
        self.assertEqual(len(rows[89]["documents"]), 3)


class RealInventoryCancelTests(TestCase):
    """실제 수불 입고·입고 취소 서비스와 함께(수불 코드 안 고침, 훅 연결은 테스트에서만 흉내)."""

    @classmethod
    def setUpTestData(cls):
        from io import StringIO

        from django.core.management import call_command

        from apps.inventory.models import Item, Staff, Supplier
        from apps.inventory.test_support import seed_document_forms

        seed_document_forms()
        call_command("seed_master", "--sample", stdout=StringIO())
        cls.raw = Item.objects.get(item_code="1000001")
        cls.supplier = Supplier.objects.get(supplier_code="V001")
        cls.staff = Staff.objects.get(staff_code="S001")

    def receive(self, key):
        import datetime

        from apps.inventory.fields import kst_now
        from apps.inventory.receiving import ReceiptInput, register_receipt

        return register_receipt(
            ReceiptInput(
                item_id=self.raw.pk,
                supplier_id=self.supplier.pk,
                staff_id=self.staff.pk,
                received_date=kst_now().date(),
                quantity="50",
                idempotency_key=key,
                expiration_date=datetime.date(2027, 9, 1),
            )
        )

    def wired(self):
        """D-178 Q3: 수불 훅이 F12를 부르는 1줄 — 연결 뒤 모양을 테스트 안에서만 흉내."""
        from unittest import mock

        def hook(*, lot_id, reason, staff_id):
            return services.delete_lot_documents(staff_id, lot_id)

        return mock.patch("apps.inventory.document_bridge.incoming_receipt_cancelled", hook)

    def cancel(self, receipt):
        from apps.inventory.receiving import cancel_receipt

        return cancel_receipt(receipt_id=receipt.pk, staff_id=self.staff.pk, reason="잘못 입고")

    def docs(self, lot_id):
        return list(
            Document.objects.filter(record_key__endswith=f"|lot:{lot_id}").values_list(
                "record_key", "deleted_at"
            )
        )

    def test_tc020_cancel_deletes_documents(self):
        receipt = self.receive("lc-1")
        with self.wired():
            self.cancel(receipt)
        receipt.refresh_from_db()
        self.assertEqual(receipt.receipt_status, "CANCELLED")
        rows = self.docs(receipt.lot_id)
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(deleted for _, deleted in rows))
        with self.assertRaises(errors.LotNotFound):
            services.docs_for_lot(receipt.lot_id)

    def test_tc021_rejected_history_deleted(self):
        """반려 이력(스냅샷 있음)은 수불 차단을 통과 → 문서 쪽이 함께 지움(ISS-046 빈틈 해소)."""
        receipt = self.receive("lc-2")
        d01 = next(i for k, i in self._ids(receipt) if k.startswith("D01"))
        out = submit(d01)["request"]
        with transaction.atomic():
            wf.decide(3, out["slots"][0]["approval_id"], "rejected", "다시")
        with self.wired():
            self.cancel(receipt)
        self.assertIsNotNone(Document.objects.get(pk=d01).deleted_at)
        self.assertEqual(ApprovalRequest.objects.get(pk=out["request_id"]).status, "rejected")

    def test_tc022_inventory_blocker_still_blocks_open_approval(self):
        """지금 수불 receipt_cancel_blockers: 결재 중 문서가 있으면 수불이 취소 거부 — 문서 그대로.
        (D-178 Q1 b를 실제로 쓰려면 수불 쪽이 이 차단을 다시 정해야 함 — lot-cancel-s4.md 4장)"""
        from apps.inventory.receiving import ReceivingError

        receipt = self.receive("lc-3")
        d01 = next(i for k, i in self._ids(receipt) if k.startswith("D01"))
        submit(d01)
        with self.wired(), self.assertRaises(ReceivingError):
            self.cancel(receipt)
        receipt.refresh_from_db()
        self.assertEqual(receipt.receipt_status, "COMPLETED")
        self.assertTrue(all(deleted is None for _, deleted in self.docs(receipt.lot_id)))

    def test_tc023_document_error_rolls_back_cancel(self):
        """문서 쪽 오류(ApiError)면 입고 취소도 롤백(수불 트랜잭션 안, 인터페이스 4장)."""
        from unittest import mock

        from apps.core.http import ApiError

        receipt = self.receive("lc-4")

        def failing(*, lot_id, reason, staff_id):
            services.delete_lot_documents(staff_id, lot_id)
            raise ApiError("시험 실패")

        with mock.patch("apps.inventory.document_bridge.incoming_receipt_cancelled", failing):
            with self.assertRaises(ApiError):
                self.cancel(receipt)
        receipt.refresh_from_db()
        self.assertEqual(receipt.receipt_status, "COMPLETED")
        self.assertTrue(all(deleted is None for _, deleted in self.docs(receipt.lot_id)))
        self.assertEqual(len(services.docs_for_lot(receipt.lot_id)["documents"]), 3)

    def _ids(self, receipt):
        return list(
            Document.objects.filter(record_key__endswith=f"|lot:{receipt.lot_id}").values_list(
                "record_key", "document_id"
            )
        )
