"""P14 r13·r14 작성 권한 — DOC 쪽 ROLE-TC-42~45·47~49 (p14-s2-spec.md 2.2 R07·R08, 2.5, 11장).

기본 개발 역할(apps/staff/roles.json): D03 담당자 {2, 3}, D01 담당자 {2, 3}·작성 권한자 {4},
HACCP팀장 {1, 5}. 직원 4는 D03에 역할이 없다(점검자로 지정되면 그 문서만 쓴다).
"""

from django.test import TestCase
from django.utils import timezone

from apps.documents import errors, files, services
from apps.documents.models import DeviationAction, Document
from apps.documents.tests.base import ccp_payload, setup_reference_data
from apps.documents.tests.p4 import (
    goc,
    lot_ref,
    new_d01,
    new_d03,
    patch,
    rows_of,
    set_info,
    setup_p4,
    version_of,
)
from apps.documents.tests.test_files import pdf
from apps.staff import roles
from apps.staff.tests.base import RolesFileMixin, default_roles

WRITE = ["owner", "writer", "leader", "inspector"]
NO_ROLE = 4  # D03에 역할 없음


def doc_id(result):
    return result["document"]["document_id"]


def required(ctx):
    return ctx.exception.details[0]["required"]


class WriteCase(RolesFileMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.t = setup_p4()

    def setUp(self):
        self.d03 = doc_id(new_d03(88))

    def subject(self, document_id, actor, text="수정"):
        return services.update_document(
            actor,
            document_id,
            {"expected_version": version_of(document_id), "document": {"subject": text}},
        )


class R07DeniedTests(WriteCase):
    """ROLE-TC-42: 역할도 점검자도 아닌 사람 — 쓰기 전부 403, DB 변화 없음, 404 → 403 → 409."""

    def assert_denied(self, call, document_id=None):
        document_id = document_id or self.d03
        before = version_of(document_id)
        with self.assertRaises(roles.RoleRequired) as ctx:
            call()
        self.assertEqual(required(ctx), WRITE)
        self.assertEqual(version_of(document_id), before)

    def test_tc42_each_write(self):
        d, v = self.d03, version_of(self.d03)
        cases = {
            "수정": lambda: self.subject(d, NO_ROLE),
            "작성완료": lambda: services.complete_document(NO_ROLE, d, v),
            "작성 재개": lambda: services.reopen_document(NO_ROLE, d, v),  # 409보다 403
            "삭제": lambda: services.delete_document(NO_ROLE, d),  # 입고 문서 409보다 403
            "되돌리기": lambda: services.unskip_document(NO_ROLE, d, v),
            "정정 취소": lambda: services.cancel_correction(NO_ROLE, d, v),
            "파일 올리기": lambda: files.attach_file(NO_ROLE, d, v, pdf()),
            "파일 연결": lambda: files.link_file(NO_ROLE, d, v, 1),
            "파일 끊기": lambda: files.detach_file(NO_ROLE, d, v, 1),
            "개선조치 쓰기": lambda: services.create_deviation(NO_ROLE, d, {"description": "x"}),
        }
        for name, call in cases.items():
            with self.subTest(name):
                self.assert_denied(call)
        self.assertFalse(Document.objects.filter(pk=d, deleted_at__isnull=False).exists())
        self.assertFalse(DeviationAction.objects.filter(document_id=d).exists())

    def test_tc42_batch_skip_item(self):
        body = services.skip_documents(
            NO_ROLE, [{"document_id": self.d03, "expected_version": 1}], "휴무"
        )
        self.assertEqual(body["failed"], 1)
        error = body["results"][0]["error"]
        self.assertEqual((error["code"], error["details"][0]["required"]), ("ROLE_REQUIRED", WRITE))

    def test_tc42_order(self):
        with self.assertRaises(errors.DocumentNotFound):  # 404가 403보다 먼저
            services.update_document(
                NO_ROLE, 99999, {"expected_version": 1, "document": {"subject": "x"}}
            )
        with self.assertRaises(errors.DocumentNotFound):
            services.complete_document(NO_ROLE, 99999, 1)
        Document.objects.filter(pk=self.d03).update(
            status="completed", completed_at=timezone.now(), completed_by_id=3
        )
        with self.assertRaises(roles.RoleRequired):  # 403이 409(잠김)보다 먼저
            self.subject(self.d03, NO_ROLE)
        with self.assertRaises(errors.DocumentLocked):  # 담당자는 상태 검사까지
            self.subject(self.d03, 2)

    def test_tc38_api(self):
        """ROLE-TC-38(NFR-03): 화면을 거치지 않은 API 호출도 서버가 403."""
        response = self.client.patch(
            f"/api/v1/documents/{self.d03}",
            {"expected_version": 1, "document": {"subject": "x"}},
            content_type="application/json",
            HTTP_X_STAFF_ID=str(NO_ROLE),
        )
        self.assertEqual(response.status_code, 403, response.content)
        self.assertEqual(response.json()["code"], "ROLE_REQUIRED")


class CreateDocumentTests(RolesFileMixin, TestCase):
    """ROLE-TC-42·43: 새 문서(POST /documents) — 본문 양식의 역할만(점검자 없음)."""

    @classmethod
    def setUpTestData(cls):
        cls.t = setup_reference_data()  # CCP_MONITORING: 담당자 {1, 3}, 팀장 {1, 5}

    def test_create(self):
        for actor in (2, 4):
            with self.subTest(actor), self.assertRaises(roles.RoleRequired):
                services.create_document(actor, ccp_payload(self.t["ccp"]))
        self.assertFalse(Document.objects.exists())
        for actor in (3, 5):
            with self.subTest(actor):
                services.create_document(actor, ccp_payload(self.t["ccp"]))
        with self.assertRaises(errors.TemplateNotFound):  # 양식 없음 = 404(권한 검사 없음)
            services.create_document(4, {**ccp_payload(self.t["ccp"]), "template_id": 999})


class R07AllowedTests(WriteCase):
    """ROLE-TC-43: 담당자·작성 권한자·팀장 / 역할 없는 점검자는 그 문서만."""

    def test_roles(self):
        data = default_roles()
        data["forms"]["D03"]["writers"] = ["DEV-004"]
        self.use_roles(data)
        for actor in (2, 4, 5):  # 담당자·작성 권한자·팀장
            with self.subTest(actor):
                self.subject(self.d03, actor, f"by {actor}")

    def test_inspector_only_that_document(self):
        other = doc_id(new_d03(89))
        set_info(self.d03, {"inspector": NO_ROLE}, actor=2)  # 담당자가 지정(R08)
        self.subject(self.d03, NO_ROLE)
        services.create_deviation(NO_ROLE, self.d03, {"description": "점검자 개선조치"})
        with self.assertRaises(roles.RoleRequired):
            self.subject(other, NO_ROLE)

    def test_d01_writer_default(self):
        d01 = doc_id(new_d01(88))  # 기본 설정: D01 작성 권한자 = 4
        self.subject(d01, 4)


class DeviationWriteTests(WriteCase):
    """ROLE-TC-44(r14): 개선조치 만들기·수정·삭제 — 역할 없음·점검자·작성 권한자·지정 확인자."""

    def make(self, actor=2, **data):
        return services.create_deviation(actor, self.d03, {"description": "외포장 파손", **data})

    def test_no_role(self):
        made = self.make()
        with self.assertRaises(roles.RoleRequired):
            services.update_deviation(NO_ROLE, made["deviation_id"], 1, {"action_result": "x"})
        with self.assertRaises(roles.RoleRequired) as ctx:
            services.delete_deviation(NO_ROLE, made["deviation_id"], 1)
        self.assertEqual(required(ctx), WRITE)

    def test_inspector_and_writer(self):
        set_info(self.d03, {"inspector": NO_ROLE}, actor=2)
        made = self.make(actor=NO_ROLE)
        services.update_deviation(NO_ROLE, made["deviation_id"], 1, {"action_result": "반품"})
        services.delete_deviation(NO_ROLE, made["deviation_id"], 2)
        data = default_roles()
        data["forms"]["D03"]["writers"] = ["DEV-005"]
        data["haccp_leaders"] = ["DEV-001"]  # 5는 작성 권한자만
        self.use_roles(data)
        made = self.make(actor=5)
        services.update_deviation(5, made["deviation_id"], 1, {"action_result": "반품"})
        services.delete_deviation(5, made["deviation_id"], 2)

    def test_checker_update_only(self):
        """지정 확인자(역할 없음)는 그 개선조치 수정만 — 만들기·삭제·다른 개선조치는 403."""
        mine = self.make(checker_ids=[NO_ROLE])
        other = self.make(checker_ids=[3])
        result = services.update_deviation(
            NO_ROLE, mine["deviation_id"], 1, {"action_result": "확인자가 고침"}
        )
        self.assertEqual(result["version"], 2)
        with self.assertRaises(roles.RoleRequired) as ctx:
            services.update_deviation(NO_ROLE, other["deviation_id"], 1, {"action_result": "x"})
        self.assertEqual(required(ctx), [*WRITE, "checker"])
        with self.assertRaises(roles.RoleRequired):
            services.delete_deviation(NO_ROLE, mine["deviation_id"], 2)
        with self.assertRaises(roles.RoleRequired):
            self.make(actor=NO_ROLE)

    def test_not_found_first(self):
        with self.assertRaises(errors.DeviationNotFound):
            services.update_deviation(NO_ROLE, 99999, 1, {"action_result": "x"})
        with self.assertRaises(errors.DeviationNotFound):
            services.delete_deviation(NO_ROLE, 99999, 1)


class InspectorRoleTests(WriteCase):
    """ROLE-TC-45: 점검자 바꾸기(R08) — 작성 권한자·점검자 403, 담당자·팀장 성공, 같은 값 통과."""

    def info_patch(self, actor, inspector):
        info = rows_of(self.d03, "info")[0]
        return patch(
            self.d03,
            {"update": [{"section_id": info["section_id"], "values": {"inspector": inspector}}]},
            actor=actor,
        )

    def test_patch(self):
        data = default_roles()
        data["forms"]["D03"]["writers"] = ["DEV-004"]
        self.use_roles(data)
        with self.assertRaises(roles.RoleRequired) as ctx:  # 작성 권한자
            self.info_patch(4, 4)
        self.assertEqual(required(ctx), ["owner", "leader"])
        self.info_patch(2, 4)  # 담당자
        self.info_patch(4, 4)  # 같은 값 = R08 안 봄
        self.info_patch(5, 3)  # 팀장
        self.use_roles(default_roles())
        self.info_patch(2, NO_ROLE)
        with self.assertRaises(roles.RoleRequired):  # 점검자가 다른 사람으로 바꾸기
            self.info_patch(NO_ROLE, 3)

    def test_batch(self):
        items = [{"document_id": self.d03, "expected_version": version_of(self.d03)}]
        body = services.batch_set_inspector(NO_ROLE, items, NO_ROLE)
        self.assertEqual(body["results"][0]["error"]["code"], "ROLE_REQUIRED")
        body = services.batch_set_inspector(5, items, NO_ROLE)
        self.assertEqual(body["succeeded"], 1, body)


class ConfigInvalidTests(WriteCase):
    """ROLE-TC-47: 설정 파일 형식 오류 — 작성은 검사 안 함, 점검자 지정은 409."""

    def test_config_invalid(self):
        self.use_roles(raw="{")
        self.subject(self.d03, NO_ROLE)
        made = services.create_deviation(NO_ROLE, self.d03, {"description": "x"})
        self.assertEqual((made["checker_ids"], made["checker_warning"]), ([], "config_invalid"))
        info = rows_of(self.d03, "info")[0]
        with self.assertRaises(roles.RoleConfigInvalid):
            patch(
                self.d03,
                {"update": [{"section_id": info["section_id"], "values": {"inspector": 2}}]},
                actor=2,
            )
        items = [{"document_id": self.d03, "expected_version": version_of(self.d03)}]
        body = services.batch_set_inspector(1, items, 2)
        self.assertEqual(body["results"][0]["error"]["code"], "ROLE_CONFIG_INVALID")


class CheckerWarningTests(WriteCase):
    """ROLE-TC-49(r14 DR-24 Q5 a): 확인자 기본값 0명이면 저장 + checker_warning."""

    def test_no_holders(self):
        set_info(self.d03, {"inspector": 2}, actor=2)  # 역할이 0명이 돼도 점검자로 쓸 수 있게
        data = default_roles()
        data["forms"]["D03"]["owners"] = ["DEV-404"]  # 없는 코드(R-W1) → 담당자 0명
        data["haccp_leaders"] = []  # 팀장 0명
        self.use_roles(data)
        made = services.create_deviation(2, self.d03, {"description": "x"})
        self.assertEqual((made["checker_ids"], made["checker_warning"]), ([], "no_holders"))
        self.assertEqual(DeviationAction.objects.filter(document_id=self.d03).count(), 1)

    def test_normal_and_sent(self):
        made = services.create_deviation(2, self.d03, {"description": "x"})
        self.assertNotIn("checker_warning", made)
        made = services.create_deviation(2, self.d03, {"description": "x", "checker_ids": []})
        self.assertNotIn("checker_warning", made)


class EntryPointTests(RolesFileMixin, TestCase):
    """ROLE-TC-46(R06): 작성 요구 진입점(N1)은 검사 없음 — 부른 사람이 작성자, 수정은 403."""

    @classmethod
    def setUpTestData(cls):
        cls.t = setup_p4()

    def test_entry_point(self):
        made = goc("D03", "D03|lot:88", lot_ref(88), actor=NO_ROLE)
        document_id = doc_id(made)
        self.assertEqual(Document.objects.get(pk=document_id).created_by_id, NO_ROLE)
        with self.assertRaises(roles.RoleRequired):
            services.update_document(
                NO_ROLE,
                document_id,
                {"expected_version": version_of(document_id), "document": {"subject": "x"}},
            )


class OptionalStepTests(TestCase):
    """r13: 점검자를 바꾸는 수정의 DOC-WRT-03은 조건부 — 도식(DOC-UPD) 비교에서 뺌(콘솔과 같음)."""

    def test_wrt03_optional(self):
        from apps.documents import flows

        steps = list(flows.FLOWS["DOC-UPD"])
        with_r08 = [*steps[:4], "DOC-WRT-03", *steps[4:]]
        self.assertTrue(flows.matches("DOC-UPD", with_r08))
        self.assertTrue(flows.matches("DOC-UPD", steps))
