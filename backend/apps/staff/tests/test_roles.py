"""P14 역할 설정 모듈(apps/staff/roles.py) 테스트. 이름의 tcNN은 p14-s2-spec.md 7장 ROLE-TC ID."""

import ast
import json
from pathlib import Path

from django.core.checks import Error
from django.test import TestCase

from apps.document_workflow.checks import check_roles
from apps.documents.tests.base import setup_reference_data
from apps.staff import roles
from apps.staff.models import Staff
from apps.staff.tests.base import RolesFileMixin, default_roles

APPS = Path(__file__).resolve().parents[2]


class ConfigTests(RolesFileMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        setup_reference_data()

    def test_tc01_valid_file(self):
        self.use_roles(default_roles())
        config = roles.load()
        self.assertIsNone(config.error)
        self.assertEqual(config.warnings, [])
        self.assertEqual(roles.leaders(), {1, 5})
        self.assertEqual(roles.owners("CCP_MONITORING"), {1, 3})
        self.assertEqual(roles.forms_of(2), sorted(roles.forms_of(2)))
        self.assertIn("HYGIENE_CHECK", roles.forms_of(2))
        self.assertEqual(
            roles.approval_line("CCP_MONITORING"),
            {
                "ok": True,
                "reason": None,
                "slots": [
                    {"slot_no": 1, "role": "owner", "label": "담당자", "candidate_ids": [1, 3]},
                    {"slot_no": 2, "role": "leader", "label": "HACCP팀장", "candidate_ids": [1, 5]},
                ],
            },
        )
        # ROLE-TC-13: D10 칸 이름
        self.assertEqual(roles.approval_line("D10")["slots"][0]["label"], "작성자")

    def test_tc02_invalid_file(self):
        bad_slots = default_roles()
        bad_slots["forms"]["D01"]["slots"] = "everyone"
        bad_version = {**default_roles(), "version": 2}
        for name, kwargs in (
            ("JSON 아님", {"raw": "{broken"}),
            ("version", {"data": bad_version}),
            ("slots", {"data": bad_slots}),
        ):
            with self.subTest(name):
                self.use_roles(**kwargs)
                self.assertIsNotNone(roles.config_error())
                # ROLE-C07: 설정 오류가 역할 검사보다 먼저 — 역할 없는 사람도 409
                for staff_id in (3, 4):
                    with self.assertRaises(roles.RoleConfigInvalid) as caught:
                        roles.require_owner_or_leader(staff_id, "CCP_MONITORING")
                    self.assertEqual(caught.exception.status, 409)
                self.assertEqual(roles.leaders(), set())

    def test_tc03_unknown_and_inactive(self):
        data = default_roles()
        data["forms"]["HYGIENE_CHECK"]["owners"] = ["DEV-002", "DEV-003", "DEV-099"]
        Staff.objects.filter(pk=2).update(is_active=False)
        self.use_roles(data)
        self.assertEqual(roles.owners("HYGIENE_CHECK"), {3})
        found = {(w["code"], w.get("staff_code")) for w in roles.load().warnings}
        self.assertIn(("R-W1", "DEV-099"), found)
        self.assertIn(("R-W2", "DEV-002"), found)
        self.assertIsNone(roles.config_error())  # 경고일 뿐 — 나머지는 그대로 쓴다

    def test_tc41_writers_file(self):
        """ROLE-TC-41(r11, DR-20): writers — 형식 검사, 없는 코드 경고, 후보 아님, R01만."""
        data = default_roles()
        data["forms"]["CCP_MONITORING"]["writers"] = ["DEV-004", "DEV-098"]
        self.use_roles(data)
        self.assertEqual(roles.writers("CCP_MONITORING"), {4})
        self.assertEqual(roles.writers("D03"), set())  # 키 없음 = 0명(정상)
        found = {(w["code"], w.get("staff_code"), w.get("where")) for w in roles.load().warnings}
        self.assertIn(("R-W1", "DEV-098", "forms.CCP_MONITORING.writers"), found)
        self.assertTrue(roles.can_submit(4, "CCP_MONITORING"))
        self.assertEqual(roles.require_submitter(4, "CCP_MONITORING"), "writer")
        self.assertFalse(roles.can_submit(4, "HYGIENE_CHECK"))
        with self.assertRaises(roles.RoleRequired):  # 정정 시작(R04)은 담당자·팀장만
            roles.require_owner_or_leader(4, "CCP_MONITORING")
        line = roles.approval_line("CCP_MONITORING")
        self.assertNotIn(4, [sid for slot in line["slots"] for sid in slot["candidate_ids"]])
        for bad in ("DEV-004", ["DEV-004", "DEV-004"], [1]):
            with self.subTest(bad=bad):
                data["forms"]["CCP_MONITORING"]["writers"] = bad
                self.use_roles(data)
                self.assertIn("writers", roles.config_error() or "")

    def test_tc04_no_leaders(self):
        data = default_roles()
        data["haccp_leaders"] = []
        self.use_roles(data)
        self.assertTrue(roles.approval_line("HYGIENE_CHECK")["ok"])  # owner 양식은 상신 가능
        line = roles.approval_line("CCP_MONITORING")
        self.assertEqual((line["ok"], line["reason"]), (False, "no_candidates"))
        with self.assertRaises(roles.NoApprovalLine) as caught:
            roles.require_approval_line("CCP_MONITORING")
        self.assertEqual(caught.exception.status, 409)
        self.assertIn("R-W5", {w["code"] for w in roles.load().warnings})
        # 팀장 0명이면 담당자 아닌 사람은 아무도 상신 못 함(B안)
        with self.assertRaises(roles.RoleRequired):
            roles.require_owner_or_leader(4, "CCP_MONITORING")

    def test_tc11_no_config(self):
        self.use_roles(default_roles())
        line = roles.approval_line("NOT_A_FORM")
        self.assertEqual((line["ok"], line["reason"], line["slots"]), (False, "no_config", []))

    def test_tc05_restart_to_apply(self):
        self.use_cache()
        data = default_roles()
        path = self.use_roles(data)
        self.assertEqual(roles.owners("CCP_MONITORING"), {1, 3})
        data["forms"]["CCP_MONITORING"]["owners"] = ["DEV-004"]
        path.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(roles.owners("CCP_MONITORING"), {1, 3})  # 재시작 전: 예전 내용
        roles.reset()  # 재시작
        self.assertEqual(roles.owners("CCP_MONITORING"), {4})

    def test_staff_changes_apply_without_restart(self):
        """리뷰 A1(ROLE-C04): 파일은 보관본이지만 직원 활성·등록은 쓸 때 본다."""
        self.use_cache()
        data = default_roles()
        data["haccp_leaders"] = ["DEV-001", "DEV-005", "DEV-006"]
        self.use_roles(data)
        self.assertEqual(roles.leaders(), {1, 5})  # DEV-006은 아직 없음(R-W1)
        Staff.objects.filter(pk=5).update(is_active=False)  # 서버 시작 뒤 비활성
        Staff.objects.create(id=6, staff_code="DEV-006", name="개발직원6")  # 시작 뒤 등록
        self.assertEqual(roles.leaders(), {1, 6})
        found = {(w["code"], w.get("staff_code")) for w in roles.load().warnings}
        self.assertIn(("R-W2", "DEV-005"), found)
        self.assertNotIn(("R-W1", "DEV-006"), found)
        self.assertEqual(roles.approval_line("CCP_MONITORING")["slots"][1]["candidate_ids"], [1, 6])

    def test_scope_resolves_once(self):
        """scope 안에서는 직원 조회가 한 번(여러 함수를 불러도)."""
        self.use_roles(default_roles())
        with self.assertNumQueries(1), roles.scope():
            roles.is_leader(1)
            roles.is_owner(3, "CCP_MONITORING")
            roles.approval_line("CCP_MONITORING")
            roles.require_owner_or_leader(3, "CCP_MONITORING")

    def test_tc06_system_check(self):
        data = default_roles()
        data["forms"] = {k: data["forms"][k] for k in ("CCP_MONITORING", "HYGIENE_CHECK")}
        self.use_roles(data)
        self.assertEqual(check_roles(None), [])  # 테스트 DB 활성 양식 = 이 둘
        data["forms"]["HYGIENE_CHECK"]["owners"] = ["DEV-099"]
        self.use_roles(data)
        warnings = check_roles(None)
        self.assertTrue(warnings)
        self.assertEqual({w.id for w in warnings}, {"document_workflow.W002"})
        Staff.objects.all().delete()
        self.assertEqual(check_roles(None), [])  # 직원 등록 전: 형식 검사만
        self.use_roles(raw="{broken")
        errors = check_roles(None)
        self.assertEqual([(type(e), e.id) for e in errors], [(Error, "document_workflow.E002")])


class ApiTests(RolesFileMixin, TestCase):
    """ROLE-TC-07: GET /roles(헤더 있음·없음), GET /staff."""

    @classmethod
    def setUpTestData(cls):
        setup_reference_data()

    def setUp(self):
        self.use_roles(default_roles())

    def test_tc07_roles(self):
        body = self.client.get("/api/v1/roles").json()
        self.assertEqual(
            set(body), {"leaders", "forms", "warnings", "config_error", "reload"}
        )  # me는 헤더 있을 때만
        self.assertEqual([p["id"] for p in body["leaders"]], [1, 5])
        self.assertEqual(body["reload"], "restart")
        forms = {f["type_code"]: f for f in body["forms"]}
        self.assertEqual(set(forms), {"CCP_MONITORING", "HYGIENE_CHECK"})  # 활성 양식만
        self.assertEqual(
            [(s["role"], s["label"]) for s in forms["CCP_MONITORING"]["slots"]],
            [("owner", "담당자"), ("leader", "HACCP팀장")],
        )
        self.assertEqual([p["id"] for p in forms["HYGIENE_CHECK"]["owners"]], [2, 3])
        self.assertTrue(forms["HYGIENE_CHECK"]["submittable"])
        # 활성 양식이 아닌 설정은 R-W3
        self.assertIn("R-W3", {w["code"] for w in body["warnings"]})
        me = self.client.get("/api/v1/roles", HTTP_X_STAFF_ID="1").json()["me"]
        self.assertEqual(me["is_leader"], True)
        self.assertIn("CCP_MONITORING", me["owner_of"])
        # ROLE-TC-41(r11): 작성 권한자 — 개발 기본 파일은 D01·D02에 DEV-004
        # (이 테스트의 활성 양식 밖)
        self.assertEqual(forms["HYGIENE_CHECK"]["writers"], [])
        me4 = self.client.get("/api/v1/roles", HTTP_X_STAFF_ID="4").json()["me"]
        self.assertEqual(
            (me4["is_leader"], me4["owner_of"], me4["writer_of"]), (False, [], ["D01", "D02"])
        )

    def test_roles_flow(self):
        """P14 S5: 역할 보기 trace가 DOC-ROL 도식과 같다(개발 콘솔 ROLE-PS-01)."""
        from apps.core import trace
        from apps.documents import flows
        from apps.documents import services as doc

        record, token = trace.start("TEST", "roles")
        try:
            doc.roles_summary(1)
        finally:
            trace.stop(token)
        self.assertTrue(flows.matches("DOC-ROL", [s.step_id for s in record.steps]))

    def test_tc07_staff(self):
        Staff.objects.filter(pk=4).update(is_active=False)
        items = self.client.get("/api/v1/staff").json()["items"]
        self.assertEqual([i["id"] for i in items], [1, 2, 3, 5])  # 활성만
        self.assertEqual(set(items[0]), {"id", "staff_code", "name"})
        # S5 r1(Q1 b): 비활성 포함 — 지난 기록의 사람 표시용
        every = self.client.get("/api/v1/staff?include_inactive=1").json()["items"]
        self.assertEqual(
            [(i["id"], i["is_active"]) for i in every],
            [(1, True), (2, True), (3, True), (4, False), (5, True)],
        )
        self.assertEqual(self.client.get("/api/v1/staff?include_inactive=yes").status_code, 400)


class BoundaryTests(TestCase):
    """ROLE-TC-34·37(NFR-01·02): roles 모듈은 staff·core만, APR은 roles를 모른다."""

    def _imports(self, path):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.level:
                    yield f".{node.module or ''}"
                else:
                    yield from (f"{node.module}.{a.name}" for a in node.names)
            elif isinstance(node, ast.Import):
                yield from (a.name for a in node.names)

    def test_tc34_roles_imports(self):
        bad = [
            m
            for m in self._imports(APPS / "staff" / "roles.py")
            if m.startswith("apps.") and not m.startswith(("apps.core.", "apps.staff."))
        ]
        self.assertEqual(bad, [])

    def test_tc37_approvals_do_not_know_roles(self):
        found = [
            (p.name, m)
            for p in (APPS / "approvals").rglob("*.py")
            if "tests" not in p.relative_to(APPS / "approvals").parts
            for m in self._imports(p)
            if "roles" in m
        ]
        self.assertEqual(found, [])
