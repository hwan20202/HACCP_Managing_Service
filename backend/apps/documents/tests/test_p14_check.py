"""P14 ROLE-R05(FR-13) — 개선조치 확인은 지정 확인자 또는 HACCP팀장 (ROLE-TC-30, p14-s2-spec r14).

P11 확인(F30·F31)이 main에 들어온 뒤 붙인다. 개발 역할: HACCP팀장 {1, 5}, CCP-1P 담당자 {1, 3}.
"""

from apps.documents import errors, services
from apps.documents.models import DeviationAction
from apps.documents.tests.p11 import ccp_doc, deviation
from apps.staff.tests.base import RolesFileMixin

from .test_p11 import P11TestCase

LEADER = 5  # 팀장만(담당자 아님)
NO_ROLE = 4


class LeaderCheckTests(RolesFileMixin, P11TestCase):
    def setUp(self):
        super().setUp()
        self.document_id = ccp_doc("CCP-1P", 12)
        self.x = deviation(self.document_id, checkers=(3,))
        self.loose = deviation(self.document_id, checkers=())  # 확인자 없음

    def test_tc30_leader_checks_unassigned(self):
        out = services.check_deviation(LEADER, self.x["deviation_id"], self.x["version"])
        self.assertEqual((out["checked_by"], out["version"]), (LEADER, 2))
        out = services.check_deviation(LEADER, self.loose["deviation_id"], self.loose["version"])
        self.assertEqual(out["checked_by"], LEADER)  # 확인자 없는 개선조치도 팀장이 확인

    def test_tc30_no_role_still_refused(self):
        with self.assertRaises(errors.NotChecker) as ctx:
            services.check_deviation(NO_ROLE, self.x["deviation_id"], 1)
        self.assertIn("HACCP팀장", ctx.exception.message)
        self.assertIsNone(DeviationAction.objects.get(pk=self.x["deviation_id"]).checked_at)

    def test_tc30_config_invalid_no_leader_exception(self):
        """ROLE-C07: 설정 파일 오류면 팀장 예외는 쓸 수 없고, 지정 확인자는 그대로 확인."""
        self.use_roles(raw="{")
        with self.assertRaises(errors.NotChecker):
            services.check_deviation(LEADER, self.x["deviation_id"], 1)
        out = services.check_deviation(3, self.x["deviation_id"], 1)
        self.assertEqual(out["checked_by"], 3)

    def test_tc30_pending_mine_and_badge(self):
        """[내 것]·사이드바 숫자: 팀장은 남이 지정된 것·확인자 없는 것도 셈."""
        out = self.pending(actor=LEADER, mine=True)
        self.assertEqual([r["deviation_id"] for r in out["rows"]], [self.x["deviation_id"]])
        self.assertEqual(out["counts"]["mine"], 2)
        self.assertTrue(out["no_checker"]["rows"][0]["can_check"])
        self.assertEqual(out["my_total"], 2)
        self.assertEqual(self.pending(actor=LEADER, summary=True), {"my_total": 2})
        other = self.pending(actor=NO_ROLE)
        self.assertEqual((other["counts"]["mine"], other["my_total"]), (0, 0))
        self.assertFalse(other["no_checker"]["rows"][0]["can_check"])

    def test_tc30_api(self):
        response = self.client.post(
            f"/api/v1/deviations/{self.x['deviation_id']}/check",
            {"expected_version": 1},
            content_type="application/json",
            HTTP_X_STAFF_ID=str(LEADER),
        )
        self.assertEqual(response.status_code, 200, response.content)
        response = self.client.post(
            f"/api/v1/deviations/{self.loose['deviation_id']}/check",
            {"expected_version": 1},
            content_type="application/json",
            HTTP_X_STAFF_ID=str(NO_ROLE),
        )
        self.assertEqual((response.status_code, response.json()["code"]), (403, "NOT_CHECKER"))


class SourceDeleteNotWriteTests(RolesFileMixin, P11TestCase):
    """명세 L-29: 입고 취소 연쇄 삭제(delete_source_documents)는 시스템 경로 — R07 검사 없음."""

    def test_no_role_actor(self):
        from django.db import transaction

        from apps.documents.models import Document

        document_id = ccp_doc("CCP-1P", 12)
        with transaction.atomic():
            out = services.delete_source_documents(NO_ROLE, [document_id])
        self.assertEqual(out["deleted"], [document_id])
        self.assertIsNotNone(Document.objects.get(pk=document_id).deleted_at)
