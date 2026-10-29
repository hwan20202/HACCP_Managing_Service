"""P14 역할 설정 모듈(apps/staff/roles.py) 테스트. 이름의 tcNN은 p14-s2-spec.md 7장 ROLE-TC ID."""

import ast
from pathlib import Path

from django.core.checks import Warning
from django.test import TestCase

from apps.document_workflow.checks import check_roles
from apps.documents.tests.base import setup_reference_data
from apps.staff import roles
from apps.staff.models import Staff
from apps.staff.tests.base import EMPTY, RolesFileMixin, default_roles

APPS = Path(__file__).resolve().parents[2]


class ConfigTests(RolesFileMixin, TestCase):
    """P16 묶음 ②: 역할 원본 = DB(ADM 문서 권한). 파일·보관본·형식 오류 경로 없음(Q5 a)."""

    @classmethod
    def setUpTestData(cls):
        setup_reference_data()

    def test_tc01_valid_roles(self):
        self.use_roles(default_roles())
        config = roles.load()
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
        # ROLE-TC-13: D10 칸 이름(양식 행 label_owner)
        self.assertEqual(roles.approval_line("D10")["slots"][0]["label"], "작성자")

    def test_tc02_file_format(self):
        """ADM-R41: 형식 검사는 가져오기(import_roles)만 — validate_file_data."""
        self.assertEqual(roles.validate_file_data(default_roles()), [])
        bad_slots = default_roles()
        bad_slots["forms"]["D01"]["slots"] = "everyone"
        bad_writers = default_roles()
        for name, data in (
            ("JSON 객체 아님", []),
            ("version", {**default_roles(), "version": 2}),
            ("slots", bad_slots),
        ):
            with self.subTest(name):
                self.assertTrue(roles.validate_file_data(data))
        for bad in ("DEV-004", ["DEV-004", "DEV-004"], [1]):
            with self.subTest(writers=bad):
                bad_writers["forms"]["CCP_MONITORING"]["writers"] = bad
                self.assertIn("writers", " ".join(roles.validate_file_data(bad_writers)))

    def test_tc03_inactive(self):
        data = default_roles()
        Staff.objects.filter(pk=2).update(is_active=False)
        self.use_roles(data)
        self.assertEqual(roles.owners("HYGIENE_CHECK"), {3})
        found = {(w["code"], w.get("staff_code")) for w in roles.load().warnings}
        self.assertIn(("R-W2", "DEV-002"), found)  # 행은 남고 효과만 빠짐(ADM-R24)

    def test_tc41_writers(self):
        """ROLE-TC-41(r11, D-198): writers — 후보 아님, R01만."""
        data = default_roles()
        data["forms"]["CCP_MONITORING"]["writers"] = ["DEV-004"]
        self.use_roles(data)
        self.assertEqual(roles.writers("CCP_MONITORING"), {4})
        self.assertEqual(roles.writers("D03"), set())  # 없음 = 0명(정상)
        self.assertTrue(roles.can_submit(4, "CCP_MONITORING"))
        self.assertEqual(roles.require_submitter(4, "CCP_MONITORING"), "writer")
        self.assertFalse(roles.can_submit(4, "HYGIENE_CHECK"))
        with self.assertRaises(roles.RoleRequired):  # 정정 시작(R04)은 담당자·팀장만
            roles.require_owner_or_leader(4, "CCP_MONITORING")
        line = roles.approval_line("CCP_MONITORING")
        self.assertNotIn(4, [sid for slot in line["slots"] for sid in slot["candidate_ids"]])

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

    def test_tc05_applies_immediately(self):
        """ADM-R36: 저장 즉시 다음 호출부터(재시작 없음)."""
        data = default_roles()
        self.use_roles(data)
        self.assertEqual(roles.owners("CCP_MONITORING"), {1, 3})
        data["forms"]["CCP_MONITORING"]["owners"] = ["DEV-004"]
        self.use_roles(data)
        self.assertEqual(roles.owners("CCP_MONITORING"), {4})

    def test_staff_changes_apply_immediately(self):
        """리뷰 A1(ROLE-C04): 직원 활성 변경은 다음 호출부터."""
        data = default_roles()
        data["haccp_leaders"] = ["DEV-001", "DEV-005", "DEV-006"]
        self.use_roles(data)  # DEV-006은 도우미가 먼저 만든다
        self.assertEqual(roles.leaders(), {1, 5, 6})
        Staff.objects.filter(pk=5).update(is_active=False)
        self.assertEqual(roles.leaders(), {1, 6})
        found = {(w["code"], w.get("staff_code")) for w in roles.load().warnings}
        self.assertIn(("R-W2", "DEV-005"), found)
        self.assertEqual(roles.approval_line("CCP_MONITORING")["slots"][1]["candidate_ids"], [1, 6])

    def test_scope_resolves_once(self):
        """scope 안에서는 문서 권한 읽기가 한 번(SQL 2 — ADM-TC-16)."""
        self.use_roles(default_roles())
        with self.assertNumQueries(2), roles.scope():
            roles.is_leader(1)
            roles.is_owner(3, "CCP_MONITORING")
            roles.approval_line("CCP_MONITORING")
            roles.require_owner_or_leader(3, "CCP_MONITORING")

    def test_tc06_system_check(self):
        """ADM-TC-15: 시스템 검사는 Warning만(E002 없음) — 빈 권한·팀장 0명·상신 불가 양식."""
        self.use_roles(default_roles())
        self.assertEqual(check_roles(None), [])  # 테스트 DB 활성 양식 = CCP_MONITORING·HYGIENE
        data = default_roles()
        data["forms"]["HYGIENE_CHECK"]["owners"] = []
        self.use_roles(data)
        warnings = check_roles(None)
        self.assertTrue(warnings)
        self.assertEqual({type(w) for w in warnings}, {Warning})
        self.assertEqual({w.id for w in warnings}, {"document_workflow.W002"})
        self.assertTrue(any("HYGIENE_CHECK" in w.msg for w in warnings))
        self.use_roles(EMPTY)
        messages = " ".join(w.msg for w in check_roles(None))
        self.assertIn("비어 있습니다", messages)
        self.assertIn("HACCP팀장이 0명", messages)
        Staff.objects.update(is_active=False)  # 직원(활성) 0명이어도 낸다(점검 P-5)
        self.assertTrue(check_roles(None))


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
            set(body), {"leaders", "forms", "warnings", "version", "setup", "reload"}
        )  # me는 헤더 있을 때만. P16: config_error 없앰, version·setup 추가(R38)
        self.assertEqual([p["id"] for p in body["leaders"]], [1, 5])
        self.assertEqual(body["reload"], "immediate")
        self.assertEqual(body["setup"], {"empty": False, "leaders": 2, "blocked_forms": []})
        forms = {f["type_code"]: f for f in body["forms"]}
        self.assertEqual(set(forms), {"CCP_MONITORING", "HYGIENE_CHECK"})  # 활성 양식만
        self.assertEqual(
            [(s["role"], s["label"]) for s in forms["CCP_MONITORING"]["slots"]],
            [("owner", "담당자"), ("leader", "HACCP팀장")],
        )
        self.assertEqual([p["id"] for p in forms["HYGIENE_CHECK"]["owners"]], [2, 3])
        self.assertTrue(forms["HYGIENE_CHECK"]["submittable"])
        # P16: 비활성 양식의 행은 보존이 정상(R-W3 없앰)
        self.assertNotIn("R-W3", {w["code"] for w in body["warnings"]})
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
    """ROLE-TC-34·37(NFR-01·02): roles 모듈은 staff·core·ADM 저장소만, APR은 roles를 모른다."""

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
            if m.startswith("apps.")
            and not m.startswith(("apps.core.", "apps.staff.", "apps.admin_settings.store"))
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
