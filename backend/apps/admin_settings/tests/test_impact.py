"""P16 묶음 ③ 비활성 영향·멈춘 결재 복구 (p16-s2-spec 3.4·9장 TC-08·09·25, R61·R67).

기본 문서 권한(개발 roles.json): CCP_MONITORING 담당자 {1, 3} → HACCP팀장 {1, 5},
HYGIENE_CHECK 담당자 {2, 3}(담당자 칸만), D03 담당자 {2, 3} → 팀장 {1, 5}.
"""

import json

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.admin_settings import flows, services, store
from apps.admin_settings.errors import ValidationFailed
from apps.approvals import errors as apr_errors
from apps.core import trace
from apps.document_workflow import services as wf
from apps.document_workflow.tests.base import new_document, version_of
from apps.document_workflow.tests.p7 import d03, setup_p7
from apps.documents import services as doc
from apps.staff import roles
from apps.staff.models import Staff
from apps.staff.tests.base import RolesFileMixin, default_roles


class ImpactCase(RolesFileMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.t = setup_p7()

    def submit(self, actor=3):
        document_id = new_document(self.t)
        return wf.submit(actor, document_id, version_of(document_id))

    def off(self, *ids):
        Staff.objects.filter(pk__in=ids).update(is_active=False)

    def impact(self, staff_id, staff=None):
        headers = {"HTTP_X_STAFF_ID": str(staff)} if staff else {}
        r = self.client.get(f"/api/v1/admin/staff/{staff_id}/impact", **headers)
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()


class ImpactTests(ImpactCase):
    """ADM-TC-08."""

    def test_roles_and_nothing(self):
        out = self.impact(4)  # 역할 없음
        self.assertEqual((out["roles"]["is_leader"], out["roles"]["owner_of"]), (False, []))
        for key in ("pending_approvals", "pending_checks", "inspector_docs"):
            self.assertEqual(out[key], 0, key)
        self.assertEqual((out["sole_approvals"], out["orphaned"]), ([], []))
        self.assertFalse(out["is_current_user"])
        self.assertTrue(self.impact(4, staff=4)["is_current_user"])  # R61 — 헤더 없이도 읽음
        self.assertEqual(self.impact(5)["active_leaders"], 2)

    def test_orphaned(self):
        data = default_roles()
        data["haccp_leaders"] = ["DEV-005"]
        data["forms"]["HYGIENE_CHECK"]["owners"] = ["DEV-002"]
        data["forms"]["PROD-LOG"] = {"owners": ["DEV-002"], "slots": "none"}
        self.use_roles(data)
        rows = {(o["type_code"], o["role"]): o for o in self.impact(5)["orphaned"]}
        leader = rows[(None, "leader")]
        self.assertEqual(leader["effect"], "submit_blocked")
        self.assertIn("CCP_MONITORING", leader["forms"])
        self.assertNotIn("HYGIENE_CHECK", leader["forms"])  # 담당자 칸만
        two = {o["type_code"]: o["effect"] for o in self.impact(2)["orphaned"]}
        self.assertEqual(two["HYGIENE_CHECK"], "submit_blocked")
        if "PROD-LOG" in two:  # 이 DB에 생산일지 양식이 설치돼 있으면
            self.assertEqual(two["PROD-LOG"], "write_leader_only")
        self.assertNotIn("CCP_MONITORING", two)  # 담당자 {1, 3}은 남음
        self.off(2)
        self.assertEqual(self.impact(2)["orphaned"], [])  # 이미 비활성 — 효과 없음

    def test_pending_and_sole(self):
        out = self.submit()  # 칸 1 담당자 후보 {1, 3}, 칸 2 팀장 후보 {1, 5}
        five = self.impact(5)
        self.assertEqual((five["pending_approvals"], five["sole_approvals"]), (1, []))
        self.off(1)
        five = self.impact(5)
        self.assertEqual(len(five["sole_approvals"]), 1)
        sole = five["sole_approvals"][0]
        self.assertEqual(sole["request_id"], out["request"]["request_id"])
        self.assertEqual((sole["type_code"], sole["role"]), ("CCP_MONITORING", "leader"))
        self.assertEqual((sole["requested_by"], sole["requester_active"]), (3, True))
        self.assertEqual(self.impact(3)["sole_approvals"][0]["role"], "owner")
        wf.decide(5, sole["approval_id"], "approved")
        self.assertEqual(self.impact(5)["pending_approvals"], 0)  # 처리한 칸은 빠짐

    def test_checks_and_inspector(self):
        out = self.submit()
        doc.create_deviation(3, out["document"]["document_id"], {"description": "x"})
        self.assertEqual(self.impact(3)["pending_checks"], 1)  # 확인자 기본값 {1, 3, 5}
        self.assertEqual(self.impact(4)["pending_checks"], 0)
        d03(state="draft", inspector=4)
        self.assertEqual(self.impact(4)["inspector_docs"], 1)

    def test_last_active_and_404(self):
        self.assertFalse(self.impact(1)["last_active"])
        self.off(2, 3, 4, 5)
        self.assertTrue(self.impact(1)["last_active"])
        r = self.client.get("/api/v1/admin/staff/999/impact")
        self.assertEqual((r.status_code, r.json()["code"]), (404, "ADM_STAFF_NOT_FOUND"))

    def test_sql_and_flow(self):
        self.submit()
        with CaptureQueriesContext(connection) as queries:
            services.staff_impact(5)
        self.assertLessEqual(len(queries), 10)
        state, token = trace.start()
        try:
            services.staff_impact(5)
        finally:
            trace.stop(token)
        ids = [s.step_id for s in state.steps]
        self.assertTrue(flows.matches("ADM-STF-IMP", ids), ids)


class ImpactEdgeTests(ImpactCase):
    """D-272 C1: 옛 직접 지정 칸·끝난 회차·다른 후보가 비활성인 칸."""

    def test_legacy_direct_slot_is_sole(self):
        out = self.submit()  # 칸 1 후보 {1, 3}, 칸 2 후보 {1, 5}
        slot = out["request"]["slots"][1]["approval_id"]
        with connection.cursor() as cursor:  # v7.1 직접 지정 칸처럼: role NULL + 결재자, 후보 없음
            cursor.execute("DELETE FROM approval_candidate WHERE approval_id = %s", [slot])
            cursor.execute(
                "UPDATE approval SET role = NULL, approver_id = 5 WHERE approval_id = %s", [slot]
            )
        five = self.impact(5)
        self.assertEqual(five["pending_approvals"], 1)
        self.assertEqual([s["approval_id"] for s in five["sole_approvals"]], [slot])
        self.assertIsNone(five["sole_approvals"][0]["role"])

    def test_finished_requests_not_counted(self):
        out = self.submit()
        wf.cancel_submission(3, out["request"]["request_id"])  # 회차 취소 → 대기 칸 skipped
        for sid in (1, 3, 5):
            self.assertEqual(self.impact(sid)["pending_approvals"], 0, sid)
        document_id = out["document"]["document_id"]
        again = wf.submit(3, document_id, version_of(document_id))
        ids = {s["slot_no"]: s["approval_id"] for s in again["request"]["slots"]}
        wf.decide(3, ids[1], "approved")
        wf.decide(5, ids[2], "approved")  # 승인으로 끝남
        self.assertEqual(self.impact(1)["pending_approvals"], 0)

    def test_only_inactive_other_candidate_is_sole(self):
        self.submit()  # 칸 2 후보 {1, 5}
        self.assertEqual(self.impact(5)["sole_approvals"], [])
        self.off(1)  # 다른 후보 1이 비활성 → 5만 처리 가능
        roles_of = {s["role"] for s in self.impact(5)["sole_approvals"]}
        self.assertEqual(roles_of, {"leader"})
        Staff.objects.filter(pk=1).update(is_active=True)
        self.assertEqual(self.impact(5)["sole_approvals"], [])


class DeactivateTests(ImpactCase):
    """ADM-TC-09: 확인 없음 400, 효과 빠짐·다시 활성 되살아남(R24·R25)."""

    def test_confirm_and_effect(self):
        with self.assertRaises(ValidationFailed) as caught:
            services.set_staff_active(1, 3, {"active": False})
        self.assertEqual(caught.exception.details[0]["code"], "confirm_required")
        services.set_staff_active(1, 3, {"active": False, "confirm_impact": True})
        self.assertNotIn(3, roles.owners("CCP_MONITORING"))
        self.assertIn("CCP_MONITORING", self.impact(3)["roles"]["owner_of"])  # 행은 남음
        services.set_staff_active(1, 3, {"active": True})
        self.assertIn(3, roles.owners("CCP_MONITORING"))


class StuckApprovalTests(ImpactCase):
    """ADM-TC-25(R67): 유일 후보·상신자 비활성 + 팀장 0명 → 팀장 지정 → 그 팀장으로 취소
    → 재상신."""

    def test_recovery(self):
        data = default_roles()
        data["haccp_leaders"] = ["DEV-005"]
        data["forms"]["CCP_MONITORING"]["owners"] = ["DEV-003"]
        self.use_roles(data)
        out = self.submit(actor=3)  # 칸 1 후보 {3}, 칸 2 후보 {5}
        request_id = out["request"]["request_id"]
        document_id = out["document"]["document_id"]
        impact = self.impact(3)
        self.assertEqual([s["role"] for s in impact["sole_approvals"]], ["owner"])
        self.assertEqual([o["type_code"] for o in impact["orphaned"]], ["CCP_MONITORING"])
        services.set_staff_active(1, 3, {"active": False, "confirm_impact": True})
        services.set_staff_active(1, 5, {"active": False, "confirm_impact": True})
        self.assertEqual(self.impact(1)["active_leaders"], 0)
        with self.assertRaises(apr_errors.NotRequester):
            wf.cancel_submission(1, request_id)  # 아직 팀장 아님 — ① 먼저
        # ① 활성 직원 1을 팀장으로 ② 현재 사용자 = 1 ③ 상신 취소
        version = store.role_rows()["version"]
        # 5는 이미 들어 있던 비활성(R33 — 그대로 둘 수 있음)
        services.save_roles(2, {"expected_version": version, "leaders": [5, 1]})
        self.assertEqual(wf.cancel_submission(1, request_id)["request"]["status"], "cancelled")
        # ④ 새 담당자 ⑤ 재상신
        version = store.role_rows()["version"]
        services.save_roles(
            1, {"expected_version": version, "forms": {"CCP_MONITORING": {"owners": [3, 2]}}}
        )
        again = wf.submit(2, document_id, version_of(document_id))
        slots = again["request"]["slots"]
        self.assertEqual([s["candidate_ids"] for s in slots], [[2], [1]])
        self.assertEqual(self.impact(2)["pending_approvals"], 1)


class ApiShapeTests(ImpactCase):
    def test_get_only(self):
        r = self.client.post(
            "/api/v1/admin/staff/1/impact", json.dumps({}), content_type="application/json"
        )
        self.assertEqual(r.status_code, 405)
