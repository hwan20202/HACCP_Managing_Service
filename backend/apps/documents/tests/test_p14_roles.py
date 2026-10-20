"""P14 역할 — DOC 쪽 ROLE-TC (p14-s2-spec.md 7장): 상세 permissions·결재선(27),
개선조치 확인자 기본값(29), 목록 owner_id(32)."""

import json

from django.test import TestCase

from apps.documents import services
from apps.documents.tests.base import ccp_payload, make_document, setup_reference_data
from apps.documents.tests.p4 import filled_ccp1p, setup_p4
from apps.staff import services as staff_services
from apps.staff.tests.base import RolesFileMixin, default_roles


def perms(submit=False, start_correction=False, write=False, assign_inspector=False):
    """문서 상세 permissions(10.4 — r13 write·assign_inspector). CCP는 점검자 일괄 대상 아님."""
    return {
        "submit": submit,
        "start_correction": start_correction,
        "write": write,
        "assign_inspector": assign_inspector,
    }


class DetailPermissionTests(RolesFileMixin, TestCase):
    """ROLE-TC-27: 헤더 없음·담당자·역할 없음·결재선 없음."""

    @classmethod
    def setUpTestData(cls):
        cls.t = setup_reference_data()

    def setUp(self):
        created = services.create_document(3, ccp_payload(self.t["ccp"]))
        self.document_id = created["document_id"]
        services.complete_document(3, self.document_id, 1)

    def detail(self, staff=None):
        headers = {} if staff is None else {"HTTP_X_STAFF_ID": str(staff)}
        response = self.client.get(f"/api/v1/documents/{self.document_id}", **headers)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_tc27(self):
        anonymous = self.detail()
        self.assertEqual(anonymous["owner_ids"], [1, 3])
        self.assertTrue(anonymous["approval_line"]["ok"])
        self.assertEqual(anonymous["permissions"], perms())
        self.assertEqual(self.detail(3)["permissions"], perms(submit=True, write=True))
        self.assertEqual(self.detail(4)["permissions"], perms())
        data = default_roles()
        data["haccp_leaders"] = []
        self.use_roles(data)
        no_line = self.detail(3)
        self.assertEqual(
            (no_line["approval_line"]["ok"], no_line["approval_line"]["reason"]),
            (False, "no_candidates"),
        )
        self.assertFalse(no_line["permissions"]["submit"])

    def test_tc41_writer_permissions(self):
        """ROLE-TC-41(r11, DR-20): 작성 권한자는 submit만 true, 정정 시작은 false."""
        data = default_roles()
        data["forms"]["CCP_MONITORING"]["writers"] = ["DEV-004"]
        self.use_roles(data)
        self.assertEqual(self.detail(4)["permissions"], perms(submit=True, write=True))  # r13
        document, _ = make_document(self.t["ccp"], status="approved")
        self.document_id = document.document_id
        self.assertEqual(self.detail(4)["permissions"], perms(write=True))

    def test_tc27_approved_correction(self):
        document, _ = make_document(self.t["ccp"], status="approved")
        self.document_id = document.document_id
        self.assertEqual(self.detail(5)["permissions"], perms(start_correction=True, write=True))
        self.assertFalse(self.detail(4)["permissions"]["start_correction"])


class OwnerFilterTests(RolesFileMixin, TestCase):
    """ROLE-TC-32: 목록 owner_id — 내가 담당자인 양식 문서만."""

    @classmethod
    def setUpTestData(cls):
        cls.t = setup_reference_data()
        cls.ccp_doc, _ = make_document(cls.t["ccp"])
        cls.hygiene_doc, _ = make_document(cls.t["hygiene"])

    def ids(self, owner_id):
        response = self.client.get(f"/api/v1/documents?owner_id={owner_id}")
        self.assertEqual(response.status_code, 200, response.content)
        return {i["document_id"] for i in response.json()["items"]}

    def test_tc32(self):
        self.assertEqual(self.ids(2), {self.hygiene_doc.document_id})
        self.assertEqual(self.ids(3), {self.hygiene_doc.document_id, self.ccp_doc.document_id})
        self.assertEqual(self.ids(4), set())  # 역할 없음 → 빈 목록
        self.assertEqual(self.client.get("/api/v1/documents?owner_id=x").status_code, 400)


class DeviationDefaultTests(RolesFileMixin, TestCase):
    """ROLE-TC-29: checker_ids 키 없음 → 담당자 + 팀장 / 빈 목록 → 비움 / 11명 → 10명 + 표시."""

    @classmethod
    def setUpTestData(cls):
        cls.t = setup_p4()

    def setUp(self):
        self.doc = filled_ccp1p()  # CCP-1P: 담당자 {1, 3}, 팀장 {1, 5}

    def create(self, **data):
        body = {"description": "09:50 자력 9,800G", "actor_id": 4, **data}
        return services.create_deviation(4, self.doc, body)

    def test_tc29_default(self):
        result = self.create()
        self.assertEqual(result["checker_ids"], [1, 3, 5])  # 담당자 먼저, 겸직자는 한 번
        self.assertNotIn("checker_default_truncated", result)
        self.assertEqual(self.create(checker_ids=[])["checker_ids"], [])

    def test_tc29_truncated(self):
        staff_services.ensure_dev_staff(range(1, 12))
        data = default_roles()
        data["forms"]["CCP-1P"]["owners"] = [f"DEV-{n:03d}" for n in range(1, 11)]
        data["haccp_leaders"] = ["DEV-011"]
        self.use_roles(data)
        result = self.create()
        self.assertEqual(result["checker_ids"], list(range(1, 11)))
        self.assertTrue(result["checker_default_truncated"])


class AssigneeKeyTests(TestCase):
    """ROLE-TC-14(FR-16): 문서 쓰기 API에 assignee_id → 400 unknown_key."""

    @classmethod
    def setUpTestData(cls):
        cls.t = setup_reference_data()

    def test_tc14_create_and_patch(self):
        def post(body):
            return self.client.post(
                "/api/v1/documents",
                data=json.dumps(body),
                content_type="application/json",
                HTTP_X_STAFF_ID="3",
            )

        response = post({**ccp_payload(self.t["ccp"]), "assignee_id": 2})
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("unknown_key", {d["code"] for d in response.json()["details"]})
        document_id = post(ccp_payload(self.t["ccp"])).json()["document_id"]
        response = self.client.patch(
            f"/api/v1/documents/{document_id}",
            data=json.dumps({"expected_version": 1, "document": {"assignee_id": 2}}),
            content_type="application/json",
            HTTP_X_STAFF_ID="3",
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("unknown_key", {d["code"] for d in response.json()["details"]})
