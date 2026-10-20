"""P14 역할 기반 결재 상신 — WF·APR 쪽 ROLE-TC (p14-s2-spec.md 7장).

기본 설정(apps/staff/roles.json): CCP_MONITORING 담당자 {1, 3} → HACCP팀장 {1, 5},
HYGIENE_CHECK 담당자 {2, 3}(owner 칸만). 직원 1 = 겸직, 4 = 역할 없음.
"""

import json

from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.approvals import errors as apr_errors
from apps.core import trace
from apps.document_workflow import services as wf
from apps.document_workflow.tests.base import (
    DUAL,
    LEADER,
    NO_ROLE,
    OWNER,
    apr,
    complete_again,
    db_state,
    invariant_violations,
    new_document,
    reject_by_leader,
    setup_reference_data,
    slot_ids,
    sql,
    version_of,
)
from apps.document_workflow.tests.p7 import d03, setup_p7
from apps.documents.tests.base import make_document
from apps.staff import roles
from apps.staff.models import Staff
from apps.staff.tests.base import RolesFileMixin, default_roles


class RoleCase(RolesFileMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.t = setup_reference_data()

    def tearDown(self):
        self.assertEqual(invariant_violations(), [])

    def submit(self, document_id=None, actor=OWNER):
        document_id = document_id or new_document(self.t)
        return wf.submit(actor, document_id, version_of(document_id))

    def slots(self, request_id):
        return apr.get_request(request_id)["slots"]


class SubmitLineTests(RoleCase):
    def test_tc08_owner_submits_two_role_slots(self):
        out = self.submit()
        slots = self.slots(out["request"]["request_id"])
        self.assertEqual(
            [
                (
                    s["slot_no"],
                    s["role"],
                    s["label"],
                    s["approver_id"],
                    s["candidate_ids"],
                    s["state"],
                )
                for s in slots
            ],
            [
                (1, "owner", "담당자", None, [1, 3], "pending"),
                (2, "leader", "HACCP팀장", None, [1, 5], "pending"),
            ],
        )
        self.assertEqual(sql("SELECT COUNT(*) FROM approval_candidate")[0][0], 4)  # 후보 고정 저장

    def test_tc09_leader_submits_owner_form(self):
        document, _ = make_document(self.t["hygiene"], status="completed")
        out = wf.submit(LEADER, document.document_id, version_of(document.document_id))
        slots = self.slots(out["request"]["request_id"])
        self.assertEqual(
            [(s["role"], s["candidate_ids"]) for s in slots], [("owner", [2, 3])]
        )  # 칸 1개, 팀장(5)은 후보 아님

    def test_tc10_no_role(self):
        document_id = new_document(self.t)
        before = db_state(document_id)
        with self.assertRaises(roles.RoleRequired) as caught:
            wf.submit(NO_ROLE, document_id, version_of(document_id))
        self.assertEqual(caught.exception.status, 403)
        self.assertEqual(db_state(document_id), before)

    def test_tc11_no_line(self):
        data = default_roles()
        data["haccp_leaders"] = []
        self.use_roles(data)
        document_id = new_document(self.t)
        with self.assertRaises(roles.NoApprovalLine) as caught:
            wf.submit(OWNER, document_id, version_of(document_id))
        self.assertEqual(
            (caught.exception.status, caught.exception.details[0]["code"]), (409, "no_candidates")
        )
        del data["forms"]["CCP_MONITORING"]
        data["haccp_leaders"] = ["DEV-001"]
        self.use_roles(data)
        with self.assertRaises(roles.RoleRequired):  # 설정 없는 양식 = 담당자 없음, 팀장만 가능
            wf.submit(OWNER, document_id, version_of(document_id))
        with self.assertRaises(roles.NoApprovalLine) as caught:
            wf.submit(1, document_id, version_of(document_id))
        self.assertEqual(caught.exception.details[0]["code"], "no_config")

    def test_tc12_config_change_between_attempts(self):
        out = self.submit()
        document_id = out["document"]["document_id"]
        reject_by_leader(out["request"])
        complete_again(document_id)
        data = default_roles()
        data["forms"]["CCP_MONITORING"]["owners"] = ["DEV-003", "DEV-004"]
        self.use_roles(data)  # "재시작"
        second = self.submit(document_id)
        old, new = (
            apr.list_requests(document_id)["items"][-1],
            apr.list_requests(document_id)["items"][0],
        )
        if old["attempt"] > new["attempt"]:
            old, new = new, old
        self.assertEqual(old["slots"][0]["candidate_ids"], [1, 3])  # 예전 회차 그대로
        self.assertEqual(new["slots"][0]["candidate_ids"], [3, 4])
        self.assertEqual(new["request_id"], second["request"]["request_id"])

    def test_tc02_config_invalid(self):
        out = self.submit()
        other = new_document(self.t)
        self.use_roles(raw="{broken")
        for actor in (OWNER, NO_ROLE):  # 역할이 없어도 403이 아니라 409
            with self.assertRaises(roles.RoleConfigInvalid):
                wf.submit(actor, other, version_of(other))
        # 이미 상신된 칸 처리는 저장된 후보로 된다
        ids = slot_ids(out["request"])
        wf.decide(OWNER, ids[1], "approved")
        # 팀장 예외 취소는 막히고(ROLE-C07) 상신자 본인 취소는 된다
        with self.assertRaises(apr_errors.NotRequester):
            wf.cancel_submission(LEADER, out["request"]["request_id"])
        wf.cancel_submission(OWNER, out["request"]["request_id"])

    def test_tc35_trace_shows_role_failure(self):
        document_id = new_document(self.t)
        record, token = trace.start("TEST", "method")
        try:
            with self.assertRaises(roles.RoleRequired):
                wf.submit(NO_ROLE, document_id, version_of(document_id))
        finally:
            trace.stop(token)
        failed = [s for s in record.steps if s.result == "fail"]
        self.assertEqual([s.step_id for s in failed][:1], ["WF-SUB-03"])


class StaffChangeTests(RoleCase):
    """리뷰 A1: 서버 시작 뒤 비활성이 된 후보는 빠진다(전에는 상신·개선조치가 400)."""

    def setUp(self):
        self.use_cache()
        roles.load()  # 서버 시작 뒤 첫 사용(보관본)

    def test_inactive_leader_left_out(self):
        Staff.objects.filter(pk=LEADER).update(is_active=False)
        out = self.submit()
        self.assertEqual(self.slots(out["request"]["request_id"])[1]["candidate_ids"], [1])
        from apps.documents import services as doc

        detail = doc.create_deviation(OWNER, out["document"]["document_id"], {"description": "x"})
        self.assertEqual(detail["checker_ids"], [1, 3])  # 담당자 {1, 3} + 팀장 {1}

    def test_all_leaders_inactive_is_409(self):
        Staff.objects.filter(pk__in=(1, LEADER)).update(is_active=False)
        document_id = new_document(self.t)
        with self.assertRaises(roles.NoApprovalLine) as caught:
            wf.submit(OWNER, document_id, version_of(document_id))
        self.assertEqual(caught.exception.details[0]["reason"], "no_candidates")


class DecideTests(RoleCase):
    def test_tc17_dual_role_both_slots(self):
        out = self.submit()
        ids = slot_ids(out["request"])
        wf.decide(DUAL, ids[1], "approved")
        result = wf.decide(DUAL, ids[2], "approved")
        self.assertEqual(result["document"]["status"], "approved")
        self.assertEqual(
            [s["approver_id"] for s in self.slots(out["request"]["request_id"])], [DUAL, DUAL]
        )

    def test_tc18_not_candidate(self):
        out = self.submit()
        for actor, slot in ((NO_ROLE, 1), (LEADER, 1), (OWNER, 2)):
            with self.subTest(actor=actor, slot=slot), self.assertRaises(apr_errors.NotYourSlot):
                wf.decide(actor, slot_ids(out["request"])[slot], "approved")

    def test_tc22_legacy_direct_slot(self):
        out = self.submit()
        request_id = out["request"]["request_id"]
        ids = slot_ids(out["request"])
        # 옛 회차(v7.1 직접 지정)처럼 바꾼다: role NULL + 결재자 지정, 후보 없음
        sql("DELETE FROM approval_candidate WHERE approval_id IN (%s, %s)", [ids[1], ids[2]])
        sql("UPDATE approval SET role = NULL, approver_id = 3 WHERE approval_id = %s", [ids[1]])
        sql("UPDATE approval SET role = NULL, approver_id = 5 WHERE approval_id = %s", [ids[2]])
        with self.assertRaises(apr_errors.NotYourSlot):
            wf.decide(1, ids[1], "approved")  # 담당자 후보였어도 지정 결재자 아님
        wf.decide(3, ids[1], "approved")
        result = wf.decide(5, ids[2], "approved")
        self.assertEqual(result["request_status"], "approved")
        self.assertEqual([s["role"] for s in self.slots(request_id)], [None, None])

    def test_tc23_dual_role_inbox_and_progress(self):
        out = self.submit()
        document_id = out["document"]["document_id"]
        inbox = apr.list_inbox(DUAL)["items"]
        mine = [i for i in inbox if i["request"]["request_id"] == out["request"]["request_id"]]
        self.assertEqual(sorted(i["role"] for i in mine), ["leader", "owner"])
        progress = apr.document_progress([document_id], DUAL)["documents"]
        self.assertEqual([s["slot_no"] for s in progress[document_id]["my_slots"]], [1, 2])
        other = apr.document_progress([document_id], NO_ROLE)["documents"]
        self.assertEqual(other[document_id]["my_slots"], [])

    def test_tc25_cancel_by_other_leader(self):
        out = self.submit()
        with self.assertRaises(apr_errors.NotRequester):
            wf.cancel_submission(2, out["request"]["request_id"])  # 역할 없음(이 양식)
        result = wf.cancel_submission(LEADER, out["request"]["request_id"])  # 다른 팀장
        self.assertEqual(result["request"]["status"], "cancelled")


class CorrectionRoleTests(RoleCase):
    """ROLE-TC-26: 정정 시작 — 담당자·팀장 성공, 역할 없음 403."""

    def approved(self):
        out = self.submit()
        ids = slot_ids(out["request"])
        wf.decide(OWNER, ids[1], "approved")
        wf.decide(LEADER, ids[2], "approved")
        return out["document"]["document_id"]

    def test_tc26(self):
        from apps.documents import services as doc

        document_id = self.approved()
        before = db_state(document_id)
        with self.assertRaises(roles.RoleRequired):
            doc.start_correction(NO_ROLE, document_id, version_of(document_id), "온도 재확인")
        self.assertEqual(db_state(document_id), before)
        for actor in (OWNER, LEADER):
            with self.subTest(actor=actor):
                with transaction.atomic():
                    result = doc.start_correction(
                        actor, document_id, version_of(document_id), "온도 재확인"
                    )
                    self.assertEqual(result["status"], "correcting")
                    transaction.set_rollback(True)
        # ROLE-TC-02·C07: 설정 파일 오류면 역할 없는 사람도 403이 아니라 409
        self.use_roles(raw="{broken")
        for actor in (OWNER, NO_ROLE):
            with self.subTest(config="invalid", actor=actor):
                with self.assertRaises(roles.RoleConfigInvalid):
                    doc.start_correction(actor, document_id, version_of(document_id), "재확인")
        self.assertEqual(db_state(document_id), before)


class SchemaTests(RoleCase):
    """ROLE-TC-36(일부): 직접 지정 칸은 결재자 필수, 역할 칸은 처리 전 결재자 없음."""

    def test_tc36_constraints(self):
        out = self.submit()
        ids = slot_ids(out["request"])
        with self.assertRaises(IntegrityError), transaction.atomic():
            sql("UPDATE approval SET role = NULL WHERE approval_id = %s", [ids[1]])
        with self.assertRaises(IntegrityError), transaction.atomic():
            sql("UPDATE approval SET approver_id = 3 WHERE approval_id = %s", [ids[1]])


class BatchDualTests(RolesFileMixin, TestCase):
    """ROLE-TC-24: 일괄 승인에 같은 문서의 두 칸(겸직자)."""

    def setUp(self):
        data = default_roles()
        data["haccp_leaders"] = ["DEV-003", "DEV-005"]
        self.use_roles(data)
        self.t = setup_p7()

    def tearDown(self):
        self.assertEqual(invariant_violations(), [])

    def test_tc24(self):
        made = d03("submitted")
        body = wf.batch_approve(3, [made["slots"][1], made["slots"][2]])
        self.assertEqual(body["succeeded"], 2, json.dumps(body, ensure_ascii=False, default=str))
        self.assertEqual(body["results"][-1]["result"]["document"]["status"], "approved")


class ApiGuardTests(RoleCase):
    """ROLE-TC-38(NFR-03): 화면을 거치지 않고 API를 직접 불러도 서버가 403."""

    def post(self, path, body, staff):
        return self.client.post(
            f"/api/v1/{path}",
            data=json.dumps(body) if body is not None else "",
            content_type="application/json",
            HTTP_X_STAFF_ID=str(staff),
        )

    def assertError(self, response, status, code):
        self.assertEqual(response.status_code, status, response.content)
        self.assertEqual(response.json()["code"], code)

    def test_tc38(self):
        document_id = new_document(self.t)
        self.assertError(
            self.post(
                f"documents/{document_id}/submit",
                {"expected_version": version_of(document_id)},
                NO_ROLE,
            ),
            403,
            "ROLE_REQUIRED",
        )
        out = self.submit(document_id)
        ids = slot_ids(out["request"])
        self.assertError(
            self.post(f"approvals/{ids[1]}/decision", {"result": "approved"}, NO_ROLE),
            403,
            "NOT_YOUR_SLOT",
        )
        self.assertError(
            self.post(f"approval-requests/{out['request']['request_id']}/cancel", None, 2),
            403,
            "NOT_REQUESTER",
        )
        wf.decide(OWNER, ids[1], "approved")
        wf.decide(LEADER, ids[2], "approved")
        self.assertError(
            self.post(
                f"documents/{document_id}/correction",
                {"expected_version": version_of(document_id), "reason": "온도 재확인"},
                NO_ROLE,
            ),
            403,
            "ROLE_REQUIRED",
        )
        # ROLE-TC-14: 상신 본문에 slots → 400 unknown_key
        other = new_document(self.t)
        response = self.post(
            f"documents/{other}/submit",
            {"expected_version": version_of(other), "slots": []},
            OWNER,
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("unknown_key", {d["code"] for d in response.json()["details"]})


class WriterTests(RoleCase):
    """ROLE-TC-39·40(r11, DR-20): 작성 권한자는 상신·재상신만.

    결재 후보 아님, 정정·남의 취소 안 됨.

    이 테스트의 설정: CCP_MONITORING·HYGIENE_CHECK 작성 권한자 = DEV-004(기본 설정에서는 역할 없음).
    """

    WRITER = NO_ROLE  # 4

    def setUp(self):
        data = default_roles()
        for type_code in ("CCP_MONITORING", "HYGIENE_CHECK"):
            data["forms"][type_code]["writers"] = ["DEV-004"]
        self.use_roles(data)

    def test_tc39_writer_submits_not_candidate(self):
        out = self.submit(actor=self.WRITER)
        slots = self.slots(out["request"]["request_id"])
        self.assertEqual(
            [(s["role"], s["candidate_ids"]) for s in slots],
            [("owner", [1, 3]), ("leader", [1, 5])],
        )  # 작성 권한자(4)는 후보 아님
        self.assertEqual(out["request"]["requested_by"], self.WRITER)
        document, _ = make_document(self.t["hygiene"], status="completed")
        hygiene = wf.submit(self.WRITER, document.document_id, version_of(document.document_id))
        self.assertEqual(
            [(s["role"], s["candidate_ids"]) for s in self.slots(hygiene["request"]["request_id"])],
            [("owner", [2, 3])],
        )
        # 재상신(자기 상신 취소 = 상신자라서 R02 → 작성완료 → 다시 상신)
        wf.cancel_submission(self.WRITER, out["request"]["request_id"])
        document_id = out["document"]["document_id"]
        again = wf.submit(self.WRITER, document_id, version_of(document_id))
        self.assertEqual(again["request"]["attempt"], 2)
        with self.assertRaises(apr_errors.NotYourSlot):
            wf.decide(self.WRITER, slot_ids(again["request"])[1], "approved")

    def test_tc40_writer_cannot_correct_or_cancel_others(self):
        out = self.submit()  # 담당자(3)가 상신
        with self.assertRaises(apr_errors.NotRequester):
            wf.cancel_submission(self.WRITER, out["request"]["request_id"])
        ids = slot_ids(out["request"])
        wf.decide(OWNER, ids[1], "approved")
        wf.decide(LEADER, ids[2], "approved")
        from apps.documents import services as doc

        document_id = out["document"]["document_id"]
        before = db_state(document_id)
        with self.assertRaises(roles.RoleRequired) as caught:
            doc.start_correction(self.WRITER, document_id, version_of(document_id), "재확인")
        self.assertEqual(caught.exception.details[0]["required"], ["owner", "leader"])
        self.assertEqual(db_state(document_id), before)

    def test_tc41_required_lists_writer(self):
        self.use_roles(default_roles())  # 4 = 역할 없음
        document_id = new_document(self.t)
        with self.assertRaises(roles.RoleRequired) as caught:
            wf.submit(NO_ROLE, document_id, version_of(document_id))
        self.assertEqual(caught.exception.details[0]["required"], ["owner", "writer", "leader"])
        self.assertIn("작성 권한자", caught.exception.message)
