"""P6 S4b 판정 연동 테스트. 이름의 tcNNN은 p6-s2-spec.md 7장의 P6-TC ID(P6a 변경은 p6-s4-basis 4장).

수준 M = 실제 DOC·WF·REQ·EFF + devstock 임시 판정 함수(대역 없음), A = API.
쓰기 테스트는 끝에 결합 상태 불변식(P6-TC-090)을 확인한다.
"""

import ast
import json
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.db import connection, transaction
from django.test import TestCase, override_settings

from apps.core import trace
from apps.devstock import inventory
from apps.doc_effects import adapter, checks, errors, receivers
from apps.doc_effects import flows as eff_flows
from apps.doc_requirements import errors as req_errors
from apps.doc_requirements import flows as req_flows
from apps.doc_requirements import services as req
from apps.doc_requirements.tests.base import DAY, by_type, setup_req
from apps.document_workflow import services as wf
from apps.document_workflow.tests.base import invariant_violations
from apps.documents import errors as doc_errors
from apps.documents import flows as doc_flows
from apps.documents import services as doc
from apps.documents.signals import document_transitioned

SLOTS = [
    {"slot_no": 1, "label": "담당", "approver_id": 3},
    {"slot_no": 2, "label": "HACCP팀장", "approver_id": 1},
]
PASS = {"appearance": "양호", "packaging": "양호", "labeling": "양호", "verdict": "PASS"}
FAIL = {**PASS, "packaging": "불량", "verdict": "FAIL"}


def lot_status(lot_id):
    with connection.cursor() as cursor:
        cursor.execute("SELECT status FROM lots WHERE id = %s", [lot_id])
        return cursor.fetchone()[0]


def set_lot_status(lot_id, status):
    with connection.cursor() as cursor:
        cursor.execute("UPDATE lots SET status = %s WHERE id = %s", [status, lot_id])


def boom(**kwargs):
    raise RuntimeError("인벤토리 내부 오류(시험)")


class EffTestCase(TestCase):
    def setUp(self):
        setup_req()

    def tearDown(self):
        self.assertEqual(invariant_violations(), [])

    # ---- 준비 (공개 함수만)
    def d03(self, lot_id=88, inspection=None):
        with transaction.atomic():
            out = req.require_for_lot(3, lot_id, inspection)
        return by_type(out)["D03"]["document_id"]

    def detail(self, document_id):
        return doc.get_document(document_id)

    def fill(self, document_id, values, inspector=True):
        sections = self.detail(document_id)["sections"]
        info = next(s for s in sections if s["section_def"] == "info")
        check = next(s for s in sections if s["section_def"] == "inspection")
        updates = [{"section_id": check["section_id"], "values": values}]
        if inspector:
            updates.append({"section_id": info["section_id"], "values": {"inspector": 4}})
        doc.update_document(
            3,
            document_id,
            {
                "expected_version": self.detail(document_id)["version"],
                "sections": {"update": updates},
            },
        )
        if values.get("verdict") == "FAIL" and not self.detail(document_id)["deviations"]:
            doc.create_deviation(
                4, document_id, {"description": "포장 파손", "action_result": "반품"}
            )

    def complete(self, document_id, note=None, actor=3):
        return doc.complete_document(actor, document_id, self.detail(document_id)["version"], note)

    def reopen(self, document_id):
        return doc.reopen_document(3, document_id, self.detail(document_id)["version"])

    def submit(self, document_id):
        version = self.detail(document_id)["version"]
        return wf.submit(3, document_id, version, [dict(s) for s in SLOTS])["request"]

    def approve(self, document_id):
        ids = {s["slot_no"]: s["approval_id"] for s in self.submit(document_id)["slots"]}
        wf.decide(3, ids[1], "approved")
        wf.decide(1, ids[2], "approved")

    def approved_pass(self, lot_id=88):
        d = self.d03(lot_id)
        self.fill(d, PASS)
        self.complete(d)
        self.approve(d)
        return d

    def capture(self):
        events = []

        def listener(sender, **kwargs):
            events.append((kwargs["event"], kwargs.get("note"), kwargs.get("actor_id")))

        document_transitioned.connect(listener, weak=False, dispatch_uid="test.capture")
        self.addCleanup(document_transitioned.disconnect, dispatch_uid="test.capture")
        return events


class SignalTests(EffTestCase):
    def test_tc070_completed_signal(self):
        events = self.capture()
        d = self.d03()
        with self.assertRaises(doc_errors.CompletionIncomplete):
            self.complete(d)  # 검사 미통과 → 신호 없음
        self.assertEqual(events, [])
        self.fill(d, PASS)
        self.complete(d, note="  메모 ")
        self.assertEqual(events, [("completed", "메모", 3)])

    def test_tc071_each_lifecycle_function(self):
        events = self.capture()
        d = self.d03()
        self.fill(d, PASS)
        self.complete(d)
        self.reopen(d)
        self.complete(d)
        ids = {s["slot_no"]: s["approval_id"] for s in self.submit(d)["slots"]}
        wf.decide(3, ids[1], "rejected", "확인 필요")
        self.complete(d)
        self.approve(d)
        doc.start_correction(3, d, self.detail(d)["version"], "판정 재확인")
        doc.cancel_correction(3, d, self.detail(d)["version"])
        self.assertEqual(
            [e[0] for e in events],
            [
                "completed",
                "reopened",
                "completed",
                "rejected",
                "completed",
                "approved",
                "correction_started",
                "correction_cancelled",
            ],
        )
        self.assertEqual([e[2] for e in events if e[0] in ("approved", "rejected")], [None, None])

    def test_tc071_receiver_error_rolls_back(self):
        d = self.d03()
        self.fill(d, PASS)
        self.complete(d)

        def fail(sender, **kwargs):
            raise RuntimeError("받는 쪽 실패")

        document_transitioned.connect(fail, weak=False, dispatch_uid="test.fail")
        self.addCleanup(document_transitioned.disconnect, dispatch_uid="test.fail")
        before = self.detail(d)["version"]
        with self.assertRaises(RuntimeError):
            self.reopen(d)
        self.assertEqual(
            (self.detail(d)["status"], self.detail(d)["version"]), ("completed", before)
        )


class JudgmentTests(EffTestCase):
    def test_tc072_two_d03(self):
        a, b = self.d03(88), self.d03(89)
        self.fill(a, PASS)
        self.fill(b, FAIL)
        self.assertEqual(self.complete(a)["status"], "completed")
        self.assertEqual(self.complete(b)["status"], "completed")
        self.assertEqual((lot_status(88), lot_status(89)), ("AVAILABLE", "REJECTED"))

    def test_tc074_same_verdict_again(self):
        d = self.d03()
        self.fill(d, PASS)
        self.complete(d)
        self.reopen(d)
        self.assertEqual(self.complete(d)["status"], "completed")
        self.assertEqual(lot_status(88), "AVAILABLE")

    def test_tc075_change_without_reason(self):
        d = self.d03()
        self.fill(d, PASS)
        self.complete(d)
        self.reopen(d)
        self.fill(d, FAIL)
        version = self.detail(d)["version"]
        with self.assertRaises(errors.InventoryRejected) as ctx:
            self.complete(d)
        self.assertIn("사유", ctx.exception.message)
        self.assertEqual((self.detail(d)["status"], self.detail(d)["version"]), ("draft", version))
        self.assertEqual(lot_status(88), "AVAILABLE")

    def test_tc076_change_with_note(self):
        d = self.d03()
        self.fill(d, PASS)
        self.complete(d)
        self.reopen(d)
        self.fill(d, FAIL)
        self.assertEqual(self.complete(d, note="포장 재확인 결과 불량")["status"], "completed")
        self.assertEqual(lot_status(88), "REJECTED")

    def test_tc077_correction_reason_is_used(self):
        d = self.approved_pass()
        self.assertEqual(lot_status(88), "AVAILABLE")
        doc.start_correction(3, d, self.detail(d)["version"], "외포장 판정 오기")
        self.fill(d, FAIL)
        self.assertEqual(self.complete(d)["status"], "completed")  # note 없음 → 정정 사유
        self.assertEqual(lot_status(88), "REJECTED")

    def test_tc078_used_lot_rejects(self):
        d = self.approved_pass()
        set_lot_status(88, "CONSUMED")  # 개발용 "사용됨" 흉내
        doc.start_correction(3, d, self.detail(d)["version"], "판정 오기")
        self.fill(d, FAIL)
        version = self.detail(d)["version"]
        with self.assertRaises(errors.InventoryRejected) as ctx:
            self.complete(d)
        detail = ctx.exception.details[0]
        self.assertEqual((detail["lot_id"], detail["lot_number"]), (88, "RM-1011-01"))
        self.assertIn("판정을 바꿀 수 없습니다", detail["message"])
        self.assertEqual(
            (self.detail(d)["status"], self.detail(d)["version"]), ("correcting", version)
        )
        self.assertEqual(lot_status(88), "CONSUMED")

    @override_settings(HACCP_INVENTORY_JUDGMENT="apps.doc_effects.tests.test_effects.boom")
    def test_tc079_other_error_propagates(self):
        d = self.d03()
        self.fill(d, PASS)
        with self.assertRaises(RuntimeError):
            self.complete(d)
        self.assertEqual(self.detail(d)["status"], "draft")
        self.assertEqual(lot_status(88), "QUARANTINE")

    @override_settings(HACCP_INVENTORY_JUDGMENT="")
    def test_not_configured(self):
        d = self.d03()
        self.fill(d, PASS)
        with self.assertRaises(errors.InventoryNotConfigured):
            self.complete(d)
        self.assertEqual(self.detail(d)["status"], "draft")


class NoCallTests(EffTestCase):
    def test_tc080_lifecycle_without_inventory_calls(self):
        """작성 재개·반려·승인·정정 시작·정정 취소는 인벤토리를 부르지 않는다(FR-21)."""
        d = self.d03()
        self.fill(d, PASS)
        self.complete(d)
        with mock.patch.object(receivers.adapter, "judge_incoming_lot") as judge:
            self.reopen(d)
            judge.assert_not_called()
        self.complete(d)
        with mock.patch.object(receivers.adapter, "judge_incoming_lot") as judge:
            ids = {s["slot_no"]: s["approval_id"] for s in self.submit(d)["slots"]}
            wf.decide(3, ids[1], "rejected", "확인")
            judge.assert_not_called()
        self.complete(d)
        with mock.patch.object(receivers.adapter, "judge_incoming_lot") as judge:
            self.approve(d)
            doc.start_correction(3, d, self.detail(d)["version"], "재확인")
            doc.cancel_correction(3, d, self.detail(d)["version"])
            judge.assert_not_called()
        self.assertEqual(lot_status(88), "AVAILABLE")


class CcpNotJudgedTests(TestCase):
    def test_tc073_non_d03(self):
        from apps.documents.tests.p4 import filled_ccp1p, setup_p4, version_of

        setup_p4()
        document_id = filled_ccp1p()
        with mock.patch.object(receivers.adapter, "judge_incoming_lot") as judge:
            doc.complete_document(3, document_id, version_of(document_id))
        judge.assert_not_called()


class CheckTests(TestCase):
    def test_tc081_checks(self):
        self.assertEqual(checks.check_inventory_adapter(None), [])
        with override_settings(HACCP_INVENTORY_JUDGMENT="apps.nowhere.judge"):
            self.assertEqual(
                [p.id for p in checks.check_inventory_adapter(None)], ["doc_effects.E001"]
            )
        with override_settings(HACCP_INVENTORY_ERRORS=["apps.nowhere.Error"]):
            self.assertEqual(
                [p.id for p in checks.check_inventory_adapter(None)], ["doc_effects.E001"]
            )
        with override_settings(HACCP_INVENTORY_JUDGMENT=""):
            self.assertEqual(
                [p.id for p in checks.check_inventory_adapter(None)], ["doc_effects.W001"]
            )
        document_transitioned.disconnect(dispatch_uid=checks.DISPATCH_UID)
        try:
            ids = [p.id for p in checks.check_inventory_adapter(None)]
        finally:
            document_transitioned.connect(
                receivers.on_document_transitioned, dispatch_uid=checks.DISPATCH_UID
            )
        self.assertEqual(ids, ["doc_effects.E001"])

    def test_tc082_no_imports_of_eff(self):
        root = Path(__file__).resolve().parents[2]
        offenders = []
        for app in ("documents", "approvals", "document_workflow", "doc_requirements"):
            for path in (root / app).rglob("*.py"):
                if "tests" in path.parts:
                    continue
                for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                    names = []
                    if isinstance(node, ast.ImportFrom) and node.module:
                        names = [node.module]
                    elif isinstance(node, ast.Import):
                        names = [a.name for a in node.names]
                    if any(n.startswith("apps.doc_effects") for n in names):
                        offenders.append(str(path))
        self.assertEqual(offenders, [])

    def test_adapter_path_only(self):
        """NFR-07: 코드에 인벤토리 앱 이름을 박지 않는다(설정 경로로만)."""
        source = (Path(adapter.__file__)).read_text(encoding="utf-8")
        self.assertNotIn("import apps.inventory", source)
        self.assertEqual(
            settings.HACCP_INVENTORY_JUDGMENT, "apps.devstock.inventory.apply_incoming_judgment"
        )


class DevInventoryRuleTests(EffTestCase):
    """P6-TC-083: 개발용 임시 함수가 수불 규칙(4.6 규칙표)과 같다."""

    def call(self, lot_id=88, result="PASS", reason=None, staff_id=3):
        return inventory.apply_incoming_judgment(
            lot_id=lot_id, result=result, staff_id=staff_id, reason=reason
        )

    def test_tc083_rules(self):
        cases = [
            # (준비 상태, 판정, 사유, 기대 상태 또는 오류 문구)
            ("QUARANTINE", "PASS", None, "AVAILABLE"),
            ("QUARANTINE", "FAIL", None, "REJECTED"),
            ("AVAILABLE", "PASS", None, "AVAILABLE"),  # 같은 판정 → 변화 없음
            ("AVAILABLE", "FAIL", None, "사유"),
            ("AVAILABLE", "FAIL", "재검사", "REJECTED"),
            ("REJECTED", "PASS", "재검사", "AVAILABLE"),
            ("CONSUMED", "PASS", None, "CONSUMED"),  # 사용됨(=적합) → 같은 판정
            ("CONSUMED", "FAIL", "재검사", "판정을 바꿀 수 없습니다"),
            ("DISPOSED", "FAIL", "재검사", "판정을 바꿀 수 없습니다"),
        ]
        for start, result, reason, expected in cases:
            with self.subTest(start=start, result=result, reason=reason):
                set_lot_status(88, start)
                if expected.isupper():
                    self.call(result=result, reason=reason)
                    self.assertEqual(lot_status(88), expected)
                else:
                    with self.assertRaises(inventory.InventoryError) as ctx:
                        self.call(result=result, reason=reason)
                    self.assertIn(expected, str(ctx.exception))
                    self.assertEqual(lot_status(88), start)
        set_lot_status(88, "QUARANTINE")
        for kwargs, error in (
            ({"lot_id": 999}, inventory.NotFound),
            ({"lot_id": 90}, inventory.InventoryError),  # 제품 LOT
            ({"lot_id": 91}, inventory.InventoryError),  # 입고 기록 없음
            ({"staff_id": 99}, inventory.NotFound),
            ({"result": "OK"}, inventory.InventoryError),
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(error):
                self.call(**kwargs)


class NoteBoundaryTests(EffTestCase):
    def test_tc084_note_200_passes(self):
        d = self.d03()
        self.fill(d, PASS)
        self.assertEqual(self.complete(d, note="가" * 200)["status"], "completed")


class InspectionInputTests(EffTestCase):
    def test_tc091_inspection_fills_new_d03(self):
        with transaction.atomic():
            out = req.require_for_lot(3, 88, PASS)
        d03 = by_type(out)["D03"]
        self.assertTrue(d03["inspection_applied"])
        detail = self.detail(d03["document_id"])
        values = next(s for s in detail["sections"] if s["section_def"] == "inspection")["values"]
        self.assertEqual({k: values[k] for k in PASS}, PASS)
        self.assertEqual(detail["status"], "draft")
        self.assertEqual(lot_status(88), "QUARANTINE")  # REQ는 인벤토리를 부르지 않는다
        self.assertNotIn("inspection_applied", by_type(out)["D01"])

    def test_tc092_recall_does_not_overwrite(self):
        d = self.d03(88, PASS)
        before = self.detail(d)
        with transaction.atomic():
            out = req.require_for_lot(3, 88, FAIL)
        d03 = by_type(out)["D03"]
        self.assertEqual((d03["result"], d03["inspection_applied"]), ("existing", False))
        after = self.detail(d)
        self.assertEqual(
            (after["version"], after["sections"]), (before["version"], before["sections"])
        )

    def test_tc093_invalid_inspection(self):
        for inspection, error in (
            ({**PASS, "note": "x"}, req_errors.ValidationFailed),
            ({k: v for k, v in PASS.items() if k != "verdict"}, req_errors.ValidationFailed),
            ("PASS", req_errors.ValidationFailed),
            ({**PASS, "verdict": "OK"}, doc_errors.ValidationFailed),
        ):
            with self.subTest(inspection=inspection), self.assertRaises(error) as ctx:
                with transaction.atomic():
                    req.require_for_lot(3, 88, inspection)
            self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")
        self.assertEqual(doc.list_documents({})["total"], 0)  # D01·D02·D03 모두 롤백

    def test_req_lot_inspection_trace(self):
        record, token = trace.start("TEST", "method")
        try:
            with transaction.atomic():
                req.require_for_lot(3, 88, PASS)
        finally:
            trace.stop(token)
        ids = [s.step_id for s in record.steps]
        self.assertTrue(req_flows.matches("REQ-LOT-INSP", ids), ids)


DEV = override_settings(
    ROOT_URLCONF="apps.devtools.test_urls",
    MIDDLEWARE=[*settings.MIDDLEWARE, "apps.devtools.middleware.TraceMiddleware"],
)
LOT_BODY = {
    "item_id": 1,
    "material_kind": "원료",
    "supplier_name": "고흥농협",
    "received_date": DAY,
    "quantity": 450,
    "unit": "kg",
}


class EffApiTests(EffTestCase):
    def post(self, path, body=None, staff="3"):
        headers = {"HTTP_X_STAFF_ID": staff} if staff else {}
        return self.client.post(
            path, data=json.dumps(body or {}), content_type="application/json", **headers
        )

    def test_tc084_note(self):
        d = self.d03()
        self.fill(d, PASS)
        path = f"/api/v1/documents/{d}/complete"
        version = self.detail(d)["version"]
        res = self.post(path, {"expected_version": version, "note": "가" * 201})
        self.assertEqual((res.status_code, res.json()["code"]), (400, "VALIDATION_ERROR"))
        self.assertEqual(res.json()["details"][0]["path"], "note")
        res = self.post(path, {"expected_version": version, "note": 1})
        self.assertEqual((res.status_code, res.json()["code"]), (400, "VALIDATION_ERROR"))
        res = self.post(path, {"expected_version": version, "note": "   "})
        self.assertEqual(res.status_code, 200, res.content)
        self.assertNotIn("note", res.json())  # 저장하지 않는다(Q10)

    def test_tc085_rejected_response(self):
        d = self.d03()
        self.fill(d, PASS)
        self.complete(d)
        self.reopen(d)
        self.fill(d, FAIL)
        res = self.post(
            f"/api/v1/documents/{d}/complete", {"expected_version": self.detail(d)["version"]}
        )
        self.assertEqual((res.status_code, res.json()["code"]), (409, "INVENTORY_REJECTED"))
        details = res.json()["details"]
        self.assertEqual(len(details), 1)
        self.assertEqual((details[0]["lot_id"], details[0]["lot_number"]), (88, "RM-1011-01"))
        self.assertEqual(res.json()["message"], details[0]["message"])

    @DEV
    def test_tc086_trace(self):
        d = self.d03()
        self.fill(d, PASS)
        res = self.post(
            f"/api/v1/documents/{d}/complete", {"expected_version": self.detail(d)["version"]}
        )
        ids = [s["step_id"] for s in res.json()["trace"]["steps"]]
        self.assertTrue(doc_flows.matches("DOC-CMP", ids), ids)
        self.assertTrue(eff_flows.matches("EFF-JDG", ids), ids)
        sig = ids.index("DOC-SIG-01")
        self.assertEqual(ids[sig + 1], "EFF-JDG-01")
        self.assertLess(ids.index("EFF-JDG-04"), ids.index("DOC-CMP-04"))

    @DEV
    def test_tc095_dev_receipt_with_inspection(self):
        res = self.post("/api/dev/req/lots", {**LOT_BODY, "inspection": PASS})
        self.assertEqual(res.status_code, 201, res.content)
        body = res.json()
        lot_id = body["lot"]["lot_id"]
        self.assertEqual(lot_status(lot_id), "AVAILABLE")  # 수불 흉내가 입고 때 판정 반영
        ids = [s["step_id"] for s in body["trace"]["steps"]]
        self.assertTrue(req_flows.matches("REQ-DEV-LOT-INSP", ids), ids)
        d = by_type(body["result"])["D03"]["document_id"]
        self.assertEqual(self.detail(d)["status"], "draft")
        self.fill(d, {}, inspector=True)  # 점검자만 채움(검사 값은 입고 때 들어옴)
        self.assertEqual(self.complete(d)["status"], "completed")  # 같은 판정 → 변화 없음
        self.assertEqual(lot_status(lot_id), "AVAILABLE")

    @DEV
    def test_tc096_dev_receipt_invalid_inspection(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM lots")
            before = cursor.fetchone()[0]
        res = self.post("/api/dev/req/lots", {**LOT_BODY, "inspection": {**PASS, "x": 1}})
        self.assertEqual((res.status_code, res.json()["code"]), (400, "VALIDATION_ERROR"))
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM lots")
            self.assertEqual(cursor.fetchone()[0], before)


class FlowMatchTests(TestCase):
    """S4b 검토 B1: 신호 안의 단계만 건너뛰고, 그 밖에 끼어든 다른 묶음 단계는 불일치."""

    def test_signal_window_only(self):
        base = ["DOC-CMP-01", "DOC-CMP-02", "DOC-CMP-03", "DOC-SIG-01"]
        nested = ["EFF-JDG-01", "EFF-JDG-02", "DOC-GET-01", "DOC-GET-02", "EFF-JDG-04"]
        self.assertTrue(doc_flows.matches("DOC-CMP", [*base, *nested, "DOC-CMP-04"]))
        self.assertFalse(
            doc_flows.matches("DOC-CMP", ["DOC-CMP-01", "DOC-GET-01", *base[1:], "DOC-CMP-04"])
        )
        self.assertFalse(doc_flows.matches("DOC-CMP", [*base, *nested]))  # 결과 단계 빠짐
