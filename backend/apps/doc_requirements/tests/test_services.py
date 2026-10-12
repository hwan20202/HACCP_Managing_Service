"""REQ 메소드 테스트 M (s2-spec 7장 REQ-TC-001~032)."""

import ast
from pathlib import Path
from unittest import mock

from django.db import connection, transaction
from django.test import TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext

from apps.approvals import services as apr
from apps.approvals.models import ApprovalRequest
from apps.core import trace as tracing
from apps.doc_requirements import errors, flows, rules, services
from apps.document_workflow import services as wf
from apps.documents import services as doc
from apps.documents.models import DocSection, Document, DocumentRef
from apps.staff.services import InvalidStaff

from .base import (
    DAY,
    by_type,
    cleanup_refs,
    deactivate,
    detail,
    in_tx,
    set_status,
    setup_req,
)

SLOTS = [
    {"slot_no": 1, "label": "담당", "approver_id": 3},
    {"slot_no": 2, "label": "HACCP팀장", "approver_id": 1},
]


def lot(lot_id, actor=3):
    return in_tx(services.require_for_lot, actor, lot_id)


def batch(batch_id, actor=3):
    return in_tx(services.require_for_batch, actor, batch_id)


def approve_d03(document_id, verdict):
    """D03(LOT 문서, P6a) 검사 판정을 채우고 작성완료 → 상신 → 두 칸 승인(실제 DOC·WF 함수)."""
    sections = detail(document_id)["sections"]
    info = next(s for s in sections if s["section_def"] == "info")
    check = next(s for s in sections if s["section_def"] == rules.D03_INSPECTION)
    values = {"appearance": "양호", "packaging": "양호", "labeling": "양호", "verdict": verdict}
    updates = [
        {"section_id": info["section_id"], "values": {"inspector": 4}},
        {"section_id": check["section_id"], "values": values},
    ]
    with transaction.atomic():
        doc.update_document(
            3,
            document_id,
            {"expected_version": detail(document_id)["version"], "sections": {"update": updates}},
        )
    if verdict == "FAIL":  # 부적합이면 개선조치가 있어야 작성완료(P4)
        doc.create_deviation(4, document_id, {"description": "포장 파손", "action_result": "반품"})
    doc.complete_document(3, document_id, detail(document_id)["version"])
    out = wf.submit(3, document_id, detail(document_id)["version"], [dict(s) for s in SLOTS])
    ids = {s["slot_no"]: s["approval_id"] for s in out["request"]["slots"]}
    wf.decide(3, ids[1], "approved")
    wf.decide(1, ids[2], "approved")


class RequireForLotTests(TestCase):
    def setUp(self):
        setup_req()

    def test_tc001_first_call(self):
        out = lot(88)
        self.assertEqual([d["type_code"] for d in out["documents"]], ["D01", "D02", "D03"])
        d01, d02, d03 = (by_type(out)[k] for k in ("D01", "D02", "D03"))
        self.assertEqual((d01["result"], d01["record_key"]), ("created", "D01|lot:88"))
        self.assertEqual((d02["result"], d02["record_key"]), ("created", "D02|lot:88"))
        self.assertEqual((d03["result"], d03["record_key"]), ("created", "D03|lot:88"))
        self.assertNotIn("section_id", d03)  # P6a: D03도 문서 단위(행 결과 없음)
        info = next(s for s in detail(d01["document_id"])["sections"] if s["section_def"] == "info")
        self.assertEqual(
            info["values"],
            {
                "lot_number": "RM-1011-01",
                "item_name": "유자",
                "supplier_name": "고흥농협",
                "received_date": DAY,
            },
        )
        self.assertEqual(detail(d01["document_id"])["work_date"], DAY)
        self.assertEqual(
            list(
                DocumentRef.objects.filter(document_id=d01["document_id"]).values_list(
                    "section_id", "lot_id", "label"
                )
            ),
            [(None, 88, "RM-1011-01")],
        )
        d03_info = next(
            s for s in detail(d03["document_id"])["sections"] if s["section_def"] == "info"
        )
        row = d03_info["values"]
        self.assertEqual(
            {
                k: row[k]
                for k in (
                    "lot_number",
                    "received_date",
                    "supplier_name",
                    "material_kind",
                    "item_name",
                    "quantity",
                    "expiration_date",
                )
            },
            {
                "lot_number": "RM-1011-01",
                "received_date": DAY,
                "supplier_name": "고흥농협",
                "material_kind": "원료",
                "item_name": "유자",
                "quantity": "500kg",
                "expiration_date": "2027-04-30",
            },
        )
        self.assertEqual(detail(d03["document_id"])["template"]["version"], 2)
        self.assertEqual(
            set(DocumentRef.objects.values_list("section_id", "lot_id")), {(None, 88)}
        )  # 세 문서 모두 문서 단위 LOT 참조
        self.assertEqual((Document.objects.count(), DocumentRef.objects.count()), (3, 3))

    def test_tc002_recall_changes_nothing(self):
        first = lot(88)
        versions = dict(Document.objects.values_list("document_id", "version"))
        again = lot(88)
        self.assertEqual([d["result"] for d in again["documents"]], ["existing"] * 3)
        self.assertEqual(by_type(again)["D03"]["document_id"], by_type(first)["D03"]["document_id"])
        self.assertEqual(dict(Document.objects.values_list("document_id", "version")), versions)
        self.assertEqual((Document.objects.count(), DocumentRef.objects.count()), (3, 3))

    def test_p6a_tc020_other_lot_state_does_not_matter(self):
        """P6a-TC-020(REQ-TC-003·004·005 대체): 같은 날 다른 LOT의 D03 상태와 관계없이 새 D03.

        정정 중(correcting)은 ERD v6(P6 S4) 뒤에 이 매개변수에 더한다.
        """
        for status in ("draft", "rejected", "completed", "submitted", "approved"):
            with self.subTest(status=status), transaction.atomic():
                sid = transaction.savepoint()
                first = by_type(lot(88))["D03"]["document_id"]
                set_status(first, status)
                before = Document.objects.values_list("version", "status").get(pk=first)
                out = by_type(lot(89))["D03"]
                self.assertEqual((out["result"], out["record_key"]), ("created", "D03|lot:89"))
                self.assertNotEqual(out["document_id"], first)
                self.assertEqual(
                    Document.objects.values_list("version", "status").get(pk=first), before
                )
                transaction.savepoint_rollback(sid)

    def test_tc006_errors_leave_nothing(self):
        cases = [
            (3, 0, errors.ValidationFailed),
            (3, "88", errors.ValidationFailed),
            (3, None, errors.ValidationFailed),
            (3, True, errors.ValidationFailed),
            (3, 999, errors.LotNotFound),
            (3, 91, errors.LotNotFound),
            (3, 90, errors.LotNotIncoming),
            (99, 88, InvalidStaff),
        ]
        for actor, lot_id, error in cases:
            with self.subTest(actor=actor, lot_id=lot_id), self.assertRaises(error):
                lot(lot_id, actor)
        deactivate("D02")
        with self.assertRaises(doc.errors.TemplateInactive):
            lot(88)
        self.assertEqual((Document.objects.count(), DocumentRef.objects.count()), (0, 0))


class OutsideTransactionTests(TransactionTestCase):
    def setUp(self):
        setup_req()

    def tearDown(self):
        cleanup_refs()

    def test_tc006_tc012_transaction_required(self):
        with self.assertRaises(errors.TransactionRequired):
            services.require_for_lot(3, 88)
        with self.assertRaises(errors.TransactionRequired):
            services.require_for_batch(3, 12)
        self.assertEqual(Document.objects.count(), 0)


class RequireForBatchTests(TestCase):
    def setUp(self):
        setup_req()

    def test_tc010_manufacture(self):
        out = batch(12)
        self.assertEqual(
            [
                (d["type_code"], d["result"], d["process_code"], d["record_key"])
                for d in out["documents"]
            ],
            [(f"CCP-{p}", "created", p, f"CCP-{p}|batch:12") for p in ("1P", "2B", "3P")],
        )
        first = out["documents"][0]["document_id"]
        info = next(s for s in detail(first)["sections"] if s["section_def"] == "info")
        self.assertEqual(
            (info["values"]["item_name"], info["values"]["batch_qty_kg"]), ("유자차", 1200)
        )
        self.assertEqual(detail(first)["work_date"], DAY)
        self.assertEqual(
            sorted(DocumentRef.objects.values_list("production_batch_id", "process_code", "label")),
            [(12, p, "PB-1011-02") for p in ("1P", "2B", "3P")],
        )

    def test_tc011_recall_packaging_item_exception(self):
        batch(12)
        self.assertEqual([d["result"] for d in batch(12)["documents"]], ["existing"] * 3)
        self.assertEqual(batch(13)["documents"], [])
        with mock.patch.dict(rules.CCP_BY_ITEM, {3: ["1P"]}):
            self.assertEqual([d["type_code"] for d in batch(15)["documents"]], ["CCP-1P"])
        self.assertEqual(Document.objects.count(), 4)

    def test_tc012_errors(self):
        cases = [
            (3, 0, errors.ValidationFailed),
            (3, "x", errors.ValidationFailed),
            (3, 999, errors.BatchNotFound),
            (3, 14, errors.BatchCancelled),
            (99, 12, InvalidStaff),
        ]
        for actor, batch_id, error in cases:
            with self.subTest(batch_id=batch_id), self.assertRaises(error):
                batch(batch_id, actor)
        self.assertEqual(Document.objects.count(), 0)


class DocsForLotTests(TestCase):
    def setUp(self):
        setup_req()
        self.first = lot(88)
        self.d03 = by_type(self.first)["D03"]["document_id"]
        self.d03_89 = by_type(lot(89))["D03"]["document_id"]

    def test_tc020_approved_verdict(self):
        approve_d03(self.d03, "PASS")
        approve_d03(self.d03_89, "FAIL")
        out = services.docs_for_lot(88)
        self.assertEqual(
            out["lot"],
            {
                "lot_number": "RM-1011-01",
                "item_name": "유자",
                "supplier_name": "고흥농협",
                "received_date": DAY,
            },
        )
        found = by_type(out)
        for code in ("D01", "D02"):
            self.assertEqual((found[code]["approved"], found[code]["verdict"]), (None, None))
        for item in out["documents"]:
            self.assertNotIn("section_id", item)  # P6a-S2 Q4
        d03 = found["D03"]
        self.assertEqual(
            (d03["status"], d03["approved"]["attempt"], d03["verdict"], d03["correcting"]),
            ("approved", 1, "PASS", False),
        )
        self.assertEqual(by_type(services.docs_for_lot(89))["D03"]["verdict"], "FAIL")

    def test_tc021_only_approved_values(self):
        # 승인 전(작성완료): 검사 섹션에 PASS를 적어도 승인본이 없으므로 판정 없음
        row = DocSection.objects.get(document_id=self.d03, section_def=rules.D03_INSPECTION)
        DocSection.objects.filter(pk=row.pk).update(
            values_json={**row.values_json, "verdict": "PASS"}
        )
        set_status(self.d03, "completed")
        d03 = by_type(services.docs_for_lot(88))["D03"]
        self.assertEqual(
            (d03["status"], d03["approved"], d03["verdict"]), ("completed", None, None)
        )

    def test_tc022_errors_empty_and_sql_count(self):
        for lot_id, error in (
            (0, errors.ValidationFailed),
            (999, errors.LotNotFound),
            (90, errors.LotNotIncoming),
        ):
            with self.subTest(lot_id=lot_id), self.assertRaises(error):
                services.docs_for_lot(lot_id)
        DocumentRef.objects.filter(lot_id=89).delete()
        self.assertEqual(services.docs_for_lot(89)["documents"], [])
        approve_d03(self.d03, "PASS")
        with CaptureQueriesContext(connection) as queries:
            services.docs_for_lot(88)
        self.assertLessEqual(len(queries), 4, [q["sql"] for q in queries])


class DocsForBatchTests(TestCase):
    def setUp(self):
        setup_req()

    def test_tc023(self):
        batch(12)
        out = services.docs_for_batch(12)
        self.assertEqual(
            out["batch"],
            {
                "batch_number": "PB-1011-02",
                "item_name": "유자차",
                "process_type": "MANUFACTURE",
                "manufactured_date": DAY,
            },
        )
        self.assertEqual(
            [(d["type_code"], d["process_code"], d["status"]) for d in out["documents"]],
            [(f"CCP-{p}", p, "draft") for p in ("1P", "2B", "3P")],
        )
        with self.assertRaises(errors.BatchNotFound):
            services.docs_for_batch(999)


class LatestApprovedTests(TestCase):
    def setUp(self):
        setup_req()

    def test_tc024(self):
        ids = [by_type(lot(n))["D01"]["document_id"] for n in (88, 89)]
        d03 = by_type(lot(88))["D03"]["document_id"]
        common = {
            "document_version": 1,
            "work_date": DAY,
            "requested_by_id": 3,
            "requested_at": "2026-10-11T09:00:00Z",
        }
        tpl = Document.objects.get(pk=ids[0]).template_id
        for document_id, attempt, status in (
            (ids[0], 1, "approved"),
            (ids[0], 2, "rejected"),
            (ids[0], 3, "approved"),
            (ids[1], 1, "rejected"),
            (d03, 1, "in_progress"),
        ):
            ApprovalRequest.objects.create(
                document_id=document_id,
                attempt=attempt,
                status=status,
                template_id=tpl,
                snapshot_json={"attempt": attempt},
                closed_at=None if status == "in_progress" else "2026-10-11T10:00:00Z",
                **common,
            )
        out = apr.latest_approved([*ids, d03, 99999])
        self.assertEqual(
            {k: (v["attempt"], v["snapshot"]) for k, v in out.items()},
            {ids[0]: (3, {"attempt": 3})},
        )
        with CaptureQueriesContext(connection) as queries:
            self.assertEqual(apr.latest_approved([]), {})
        self.assertEqual(len(queries), 0)


class BoundaryTests(TestCase):
    """REQ-TC-030: 계층 경계(NFR-03)와 뷰 이름 위치(NFR-04)."""

    root = Path(__file__).resolve().parents[1]
    allowed = (
        "apps.documents.services",
        "apps.approvals.services",
        "apps.staff.services",
        "apps.core.",
        "django",
    )

    def _imports(self, path):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 0:
                yield from (f"{node.module}.{alias.name}" for alias in node.names)
            elif isinstance(node, ast.Import):
                yield from (alias.name for alias in node.names)

    def test_tc030(self):
        sources = [p for p in self.root.glob("*.py")]
        bad = [
            (p.name, m) for p in sources for m in self._imports(p) if not m.startswith(self.allowed)
        ]
        self.assertEqual(bad, [])
        apps_dir = self.root.parent
        for other in ("documents", "approvals", "document_workflow", "staff"):
            for p in (apps_dir / other).rglob("*.py"):
                found = [m for m in self._imports(p) if m.startswith("apps.doc_requirements")]
                self.assertEqual(found, [], p)
        views = [p.name for p in sources if "v_doc_" in p.read_text(encoding="utf-8")]
        self.assertEqual(views, ["sources.py"])


class TraceTests(TestCase):
    """REQ-TC-031: trace 단계 ID가 s2-flows와 같은 순서(NFR-06)."""

    def setUp(self):
        setup_req()

    def _steps(self, func, *args):
        current, token = tracing.start()
        try:
            func(*args)
        finally:
            tracing.stop(token)
        return [s.step_id for s in current.steps]

    def test_tc031(self):
        first = self._steps(in_tx, services.require_for_lot, 3, 88)
        self.assertTrue(flows.matches("REQ-LOT", first), first)
        self.assertIn("DOC-GOC-01", first)
        again = self._steps(in_tx, services.require_for_lot, 3, 88)
        self.assertTrue(flows.matches("REQ-LOT", again), again)
        # P6a REQ-TC-031: D03도 N1이라 05(N2 행 추가) 단계가 없다
        self.assertNotIn("REQ-LOT-05", first + again)
        batch_steps = self._steps(in_tx, services.require_for_batch, 3, 12)
        self.assertTrue(flows.matches("REQ-BAT", batch_steps), batch_steps)
        self.assertEqual(batch_steps.count("REQ-BAT-03"), 3)
        self.assertTrue(flows.matches("REQ-FND", self._steps(services.docs_for_lot, 88)))
        self.assertTrue(flows.matches("REQ-FND-B", self._steps(services.docs_for_batch, 12)))
        self.assertFalse(flows.matches("REQ-LOT", ["REQ-LOT-00", "REQ-LOT-02"]))
