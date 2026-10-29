"""P16 묶음 ② 직원·문서 권한·처음 설정·가져오기 (p16-s2-spec 9장 TC-06·07·10~18·21·22·24)."""

import json
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext

from apps.admin_settings import flows, services, store
from apps.admin_settings.errors import StaffNotFound, ValidationFailed, VersionConflict
from apps.admin_settings.models import AdminChangeLog, RoleForm, RoleFormMember, RoleLeader
from apps.core import trace
from apps.documents.models import DocumentTemplate
from apps.documents.seed import (
    ensure_p4_templates,
    ensure_p8_templates,
    ensure_p15_templates,
    ensure_staff,
)
from apps.inventory import staff_admin
from apps.staff import roles
from apps.staff.models import Staff
from apps.staff.tests.base import EMPTY, RolesFileMixin, default_roles

DEV_ROLES = Path(__file__).resolve().parents[2] / "staff" / "roles.json"


def codes(detail_list):
    return [d["code"] for d in detail_list]


def raises_codes(test, fn, *args):
    with test.assertRaises(ValidationFailed) as caught:
        fn(*args)
    return codes(caught.exception.details)


class SetupCase(RolesFileMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_staff(5)
        ensure_p4_templates()
        ensure_p8_templates()

    def api(self, method, path, body=None, staff=1):
        headers = {"HTTP_X_STAFF_ID": str(staff)} if staff else {}
        data = json.dumps(body) if body is not None else None
        call = getattr(self.client, method)
        if data is None:
            return call(f"/api/v1/{path}", **headers)
        return call(f"/api/v1/{path}", data, content_type="application/json", **headers)


class StaffCodeTests(SetupCase):
    """ADM-TC-06(R21)."""

    def test_tc06_suggest(self):
        self.assertEqual(services.suggest_staff_code(), {"code": "DEV-006"})
        Staff.objects.create(staff_code="QA-09", name="x")
        Staff.objects.create(staff_code="QA-10", name="y")
        self.assertEqual(staff_admin.next_code(), "DEV-006")  # 가장 많은 접두어(DEV 5개)
        for sid in range(1, 6):
            Staff.objects.filter(pk=sid).update(staff_code=f"old{sid}")
        self.assertEqual(staff_admin.next_code(), "QA-11")  # 자릿수 유지

    def test_tc06_fallback(self):
        for sid in range(1, 6):
            Staff.objects.filter(pk=sid).update(staff_code=f"S00{sid}x")
        self.assertEqual(staff_admin.next_code(), "S-001")
        Staff.objects.create(staff_code="S-001", name="z")
        self.assertEqual(staff_admin.next_code(), "S-002")

    def test_a04(self):
        self.assertEqual(
            self.api("get", "admin/staff/next-code", staff=None).json(), {"code": "DEV-006"}
        )


class StaffWriteTests(SetupCase):
    """ADM-TC-07(R20·R22·R26)·09 일부(R25·R65)."""

    def test_tc07_create(self):
        r = self.api("post", "admin/staff", {"name": " 김직원 ", "staff_code": " DEV-006 "})
        self.assertEqual(r.status_code, 201, r.content)
        body = r.json()["staff"]
        self.assertEqual(
            (body["staff_code"], body["name"], body["is_active"]), ("DEV-006", "김직원", True)
        )
        log = AdminChangeLog.objects.get(target="staff", target_id=body["id"])
        self.assertEqual((log.action, log.actor_id), ("create", 1))
        for bad, code in (
            ({"name": "a", "staff_code": "DEV-006"}, "duplicate_code"),
            ({"name": "", "staff_code": "N-1"}, "invalid"),
            ({"name": "가" * 41, "staff_code": "N-1"}, "invalid"),
            ({"name": "a", "staff_code": "C" * 21}, "invalid"),
            ({"name": "a", "staff_code": "N-1", "is_active": False}, "unknown_key"),
        ):
            with self.subTest(code=code, bad=bad):
                r = self.api("post", "admin/staff", bad)
                self.assertEqual(r.status_code, 400)
                self.assertIn(code, codes(r.json()["details"]))
        self.assertEqual(Staff.objects.count(), 6)  # 실패는 아무것도 안 넣음

    def test_tc07_rename_and_code_locked(self):
        r = self.api("patch", "admin/staff/2", {"name": "새이름"})
        self.assertEqual((r.status_code, r.json()["changed"]), (200, True))
        self.assertEqual(Staff.objects.get(pk=2).name, "새이름")
        log = AdminChangeLog.objects.get(target="staff", action="rename")
        self.assertEqual(
            (log.before_json, log.after_json), ({"name": "개발직원2"}, {"name": "새이름"})
        )
        r = self.api("patch", "admin/staff/2", {"name": "새이름"})
        self.assertEqual(r.json()["changed"], False)  # 같은 이름 — 이력 없음
        self.assertEqual(AdminChangeLog.objects.filter(action="rename").count(), 1)
        r = self.api("patch", "admin/staff/2", {"staff_code": "X-1"})
        self.assertEqual(codes(r.json()["details"]), ["unknown_key"])  # R22
        self.assertEqual(self.api("patch", "admin/staff/999", {"name": "a"}).status_code, 404)
        # 수불 /staff/ PATCH의 코드 readonly는 그대로(C1)
        r = self.client.patch(
            "/api/v1/inventory/staff/2/",
            json.dumps({"staff_code": "X-1"}),
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 400)

    def test_tc09_deactivate_rules(self):
        r = self.api("post", "admin/staff/4/active", {"active": False})
        self.assertIn("confirm_required", codes(r.json()["details"]))  # R25
        r = self.api("post", "admin/staff/4/active", {"active": False, "confirm_impact": True})
        self.assertEqual((r.status_code, r.json()["staff"]["is_active"]), (200, False))
        self.assertEqual(r.json()["staff"]["roles"]["writer_of"], ["D01", "D02"])  # 행은 남음(R24)
        self.assertNotIn(4, roles.writers("D01"))  # 효과만 빠짐
        r = self.api("post", "admin/staff/4/active", {"active": True})
        self.assertEqual(r.status_code, 200)
        self.assertIn(4, roles.writers("D01"))  # 다시 활성 → 되살아남
        actions = list(
            AdminChangeLog.objects.filter(target_id=4)
            .order_by("log_id")
            .values_list("action", flat=True)
        )
        self.assertEqual(actions, ["deactivate", "activate"])
        Staff.objects.exclude(pk=1).update(is_active=False)
        r = self.api("post", "admin/staff/1/active", {"active": False, "confirm_impact": True})
        self.assertIn("last_active_staff", codes(r.json()["details"]))  # R65

    def test_list(self):
        Staff.objects.filter(pk=4).update(is_active=False)
        body = self.api("get", "admin/staff?state=inactive", staff=None).json()
        self.assertEqual(body["setup"], {"no_active_staff": False})
        self.assertEqual([i["id"] for i in body["items"]], [4])
        self.assertEqual(
            body["items"][0]["roles"],
            {"is_leader": False, "owner_of": [], "writer_of": ["D01", "D02"]},
        )
        one = self.api("get", "admin/staff?q=DEV-001", staff=None).json()["items"]
        self.assertEqual(one[0]["roles"]["is_leader"], True)
        self.assertEqual(self.api("get", "admin/staff?state=x", staff=None).status_code, 400)


class FirstSetupTests(SetupCase):
    """ADM-TC-17(R60~R65·R71)."""

    def setUp(self):
        Staff.objects.update(
            is_active=False
        )  # 활성 직원 0명(CSV·수불 API로 전원 비활성된 것과 같음)

    def test_tc17_bootstrap_create(self):
        r = self.api("post", "admin/staff", {"name": "설치자", "staff_code": "S-001"}, staff=None)
        self.assertEqual(r.status_code, 201, r.content)
        new = r.json()["staff"]["id"]
        log = AdminChangeLog.objects.get(target="staff", target_id=new)
        self.assertEqual((log.action, log.actor_id), ("bootstrap_create", new))  # R63
        # 이제 활성 1명 — 헤더 없는(또는 비활성 id) 등록은 400 setup_finished(R62)
        for staff in (None, 2):
            r = self.api(
                "post", "admin/staff", {"name": "두번째", "staff_code": "S-002"}, staff=staff
            )
            self.assertEqual(codes(r.json()["details"]), ["setup_finished"])
        r = self.api("post", "admin/staff", {"name": "두번째", "staff_code": "S-002"}, staff=new)
        self.assertEqual(r.status_code, 201)  # 평소 규칙(R27)

    def test_tc17_bootstrap_activate(self):
        r = self.api("post", "admin/staff/2/active", {"active": True}, staff=None)
        self.assertEqual(r.status_code, 200, r.content)
        log = AdminChangeLog.objects.get(target="staff", target_id=2)
        self.assertEqual(
            (log.action, log.actor_id, log.before_json, log.after_json),
            ("bootstrap_activate", 2, {"is_active": False}, {"is_active": True}),
        )
        r = self.api("post", "admin/staff/3/active", {"active": True}, staff=None)
        self.assertEqual(codes(r.json()["details"]), ["setup_finished"])
        r = self.api(
            "post", "admin/staff/2/active", {"active": False, "confirm_impact": True}, staff=None
        )
        self.assertEqual(r.json()["code"], "STAFF_HEADER_MISSING")  # 비활성은 현재 사용자 필요

    def test_tc17_list_without_header(self):
        body = self.api("get", "admin/staff?state=inactive", staff=None).json()
        self.assertEqual(body["setup"], {"no_active_staff": True})
        self.assertEqual(self.client.get("/api/v1/staff").json()["items"], [])  # 0명 판정(R69)

    def test_tc17_csrf(self):
        client = Client(enforce_csrf_checks=True)
        body = json.dumps({"name": "설치자", "staff_code": "S-001"})
        r = client.post("/api/v1/admin/staff", body, content_type="application/json")
        self.assertEqual(r.status_code, 403)  # 토큰 없음(R71)
        client.get("/")
        token = client.cookies["csrftoken"].value
        r = client.post(
            "/api/v1/admin/staff", body, content_type="application/json", HTTP_X_CSRFTOKEN=token
        )
        self.assertEqual(r.status_code, 201, r.content)
        r = client.post(
            "/api/v1/admin/staff/3/active",
            json.dumps({"active": True}),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(codes(r.json()["details"]), ["setup_finished"])  # 이미 1명


class RoleSaveTests(SetupCase):
    """ADM-TC-10~13·15·16(R31~R38)."""

    def body(self, **forms):
        version = store.role_rows()["version"]
        return {"expected_version": version, "forms": forms}

    def test_tc10_save(self):
        before_d01 = sorted(roles.owners("D01"))
        out = services.save_roles(
            1, {**self.body(D03={"owners": [2, 4], "writers": [4]}), "leaders": [1, 5]}
        )
        self.assertEqual(
            [(c["role"], c["type_code"]) for c in out["changes"]],
            [("owner", "D03"), ("writer", "D03")],
        )  # 팀장은 같아서 바뀐 곳 아님
        self.assertEqual((roles.owners("D03"), roles.writers("D03")), ({2, 4}, {4}))  # 겹침 허용
        self.assertEqual(sorted(roles.owners("D01")), before_d01)  # 안 보낸 양식 그대로
        self.assertEqual(out["version"], store.role_rows()["version"])
        Staff.objects.filter(pk=4).update(is_active=False)
        # 이미 들어 있던 비활성은 그대로 둘 수 있음, 새로 넣는 비활성은 거부(R33)
        services.save_roles(1, self.body(D03={"owners": [2, 4, 3], "writers": [4]}))
        got = raises_codes(self, services.save_roles, 1, self.body(D02={"owners": [4]}))
        self.assertEqual(got, ["inactive_staff"])

    def test_tc11_errors(self):
        version = store.role_rows()["version"]
        for body, code in (
            ({"expected_version": version, "forms": {"D01": {"slots": "owner"}}}, "unknown_key"),
            ({"expected_version": version, "forms": {"NOPE": {"owners": []}}}, "unknown_form"),
            ({"expected_version": version, "leaders": [1, 1]}, "duplicate"),
            ({"expected_version": version, "leaders": [999]}, "unknown_staff"),
            ({"expected_version": version, "labels": {}}, "unknown_key"),
        ):
            with self.subTest(code=code):
                self.assertIn(code, raises_codes(self, services.save_roles, 1, body))
        with self.assertRaises(VersionConflict):
            services.save_roles(1, {"expected_version": version + 5, "leaders": [1]})

    def test_tc12_immediate_and_same_values(self):
        with roles.scope():
            self.assertIn(5, roles.leaders())
            services.save_roles(1, {**self.body(), "leaders": [1]})
        self.assertEqual(roles.leaders(), {1})  # 다음 요청부터(R36)
        version = store.role_rows()["version"]
        out = services.save_roles(1, {**self.body(), "leaders": [1]})
        self.assertEqual(
            (out["changes"], out["version"]), ([], version)
        )  # 같은 값 — 버전·이력 없음

    def test_tc13_history(self):
        services.save_roles(2, {**self.body(D03={"owners": [3]}), "leaders": [1]})
        self.api("patch", "admin/staff/3", {"name": "바뀐이름"}, staff=2)
        items = self.api("get", "admin/history?target=roles", staff=None).json()["items"]
        self.assertEqual(
            {(i["target"], i["label"]) for i in items},
            {("role_leader", "HACCP팀장"), ("role_form", "D03")},
        )
        self.assertEqual({i["actor"]["name"] for i in items}, {"개발직원2"})
        form = next(i for i in items if i["target"] == "role_form")
        self.assertEqual(form["before"], {"role": "owner", "staff_ids": [2, 3]})
        self.assertEqual(form["after"], {"role": "owner", "staff_ids": [3]})
        staff = self.api("get", "admin/history?target=staff", staff=None).json()["items"]
        self.assertEqual(staff[0]["label"], "바뀐이름(DEV-003)")

    def test_api_and_flows(self):
        r = self.api("get", "admin/roles", staff=None)
        body = r.json()
        self.assertEqual(set(body), {"version", "setup", "leaders", "forms", "warnings"})
        d10 = next(f for f in body["forms"] if f["type_code"] == "D10")
        self.assertEqual((d10["slots"], d10["labels"]["owner"]), ("owner_leader", "작성자"))
        self.assertEqual(body["setup"]["blocked_forms"], [])
        record, token = trace.start("TEST", "save")
        try:
            r = self.api(
                "put", "admin/roles", {"expected_version": body["version"], "leaders": [1]}
            )
        finally:
            trace.stop(token)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(flows.matches("ADM-ROL-SAV", [s.step_id for s in record.steps]))
        self.assertEqual(
            self.api("put", "admin/roles", {"expected_version": 1}, staff=None).status_code, 400
        )

    def test_tc15_empty_setup(self):
        self.use_roles(EMPTY)
        setup = services.roles_for_edit()["setup"]
        self.assertTrue(setup["empty"])
        self.assertEqual(setup["leaders"], 0)
        self.assertIn("D03", setup["blocked_forms"])  # 담당자 칸 0명
        self.assertNotIn("PROD-LOG", setup["blocked_forms"])  # 결재 없음은 막힌 것 아님

    def test_tc16_sql(self):
        with CaptureQueriesContext(connection) as ctx:
            services.roles_for_edit()
        self.assertLessEqual(len(ctx), 3)  # F02 2 + 활성 양식 1


class ImportTests(TestCase):
    """ADM-TC-14·22·24(R41~R44)."""

    @classmethod
    def setUpTestData(cls):
        ensure_staff(5)
        ensure_p4_templates()
        RoleLeader.objects.all().delete()
        RoleFormMember.objects.all().delete()  # 새로 옮기는 서버처럼 사람 0명
        # 이 서버에 설치 안 된 양식(개발 시드가 만든 행)은 없앰 — 가져오기가 건너뛰어야 함(R43)
        RoleForm.objects.filter(type_code__in=["CCP_MONITORING", "HYGIENE_CHECK"]).delete()

    def run_import(self, data, *args):
        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(data if isinstance(data, str) else json.dumps(data, ensure_ascii=False))
        self.addCleanup(Path(tmp.name).unlink, missing_ok=True)
        out = StringIO()
        call_command("import_roles", "--file", tmp.name, *args, stdout=out)
        return out.getvalue()

    def assertFails(self, data, *args):
        before = (
            RoleLeader.objects.count(),
            RoleFormMember.objects.count(),
            store.role_rows()["version"],
        )
        with self.assertRaises(CommandError) as caught:
            self.run_import(data, *args)
        self.assertEqual(caught.exception.returncode, 2)
        after = (
            RoleLeader.objects.count(),
            RoleFormMember.objects.count(),
            store.role_rows()["version"],
        )
        self.assertEqual(after, before)  # 아무것도 안 넣음
        return str(caught.exception)

    def test_tc14_import(self):
        version = store.role_rows()["version"]
        out = self.run_import(default_roles(), "--actor", "DEV-001")
        self.assertIn("건너뜀", out)  # CCP_MONITORING·HYGIENE_CHECK — 이 DB에 양식 행 없음(R43)
        self.assertEqual(roles.leaders(), {1, 5})
        self.assertEqual(roles.writers("D01"), {4})
        self.assertEqual(store.role_rows()["version"], version + 1)
        log = AdminChangeLog.objects.get(target="roles_import")
        self.assertEqual((log.action, log.actor_id), ("import", 1))
        self.assertIn("CCP_MONITORING", log.after_json["skipped"])
        self.assertIn("이미 사람", self.assertFails(default_roles(), "--actor", "DEV-001"))
        data = default_roles()
        data["haccp_leaders"] = ["DEV-002"]
        self.run_import(data, "--actor", "DEV-001", "--replace")
        self.assertEqual(roles.leaders(), {2})

    def test_tc14_replace_keeps_other_forms(self):
        """--replace는 파일에 없는 양식의 사람을 지우지 않음(R43 — D-270 B1)."""
        self.run_import(default_roles(), "--actor", "DEV-001")
        d02 = set(
            RoleFormMember.objects.filter(role_form__type_code="D02").values_list(
                "role", "staff_id"
            )
        )
        self.assertTrue(d02)
        data = default_roles()
        data["forms"] = {"D01": data["forms"]["D01"]}
        data["forms"]["D01"]["owners"] = ["DEV-003"]
        self.run_import(data, "--actor", "DEV-001", "--replace")
        self.assertEqual(roles.owners("D01"), {3})
        after = set(
            RoleFormMember.objects.filter(role_form__type_code="D02").values_list(
                "role", "staff_id"
            )
        )
        self.assertEqual(after, d02)

    def test_tc14_failures(self):
        missing = default_roles()
        missing["forms"]["D03"]["owners"] = ["DEV-002", "NOBODY-1"]
        self.assertIn("NOBODY-1", self.assertFails(missing, "--actor", "DEV-001"))  # R42
        self.assertIn("형식", self.assertFails({"version": 2}, "--actor", "DEV-001"))
        self.assertIn("읽지 못했습니다", self.assertFails("{broken", "--actor", "DEV-001"))
        Staff.objects.filter(pk=3).update(is_active=False)
        self.run_import(default_roles(), "--actor", "DEV-001")  # 비활성 직원 코드는 넣음
        self.assertTrue(RoleFormMember.objects.filter(staff_id=3).exists())
        self.assertNotIn(3, roles.owners("D03"))

    def test_tc22_actor(self):
        self.assertIn("--actor", self.assertFails(default_roles(), "--actor", "NOBODY"))
        Staff.objects.filter(pk=1).update(is_active=False)
        self.assertIn("--actor", self.assertFails(default_roles(), "--actor", "DEV-001"))
        with self.assertRaises(CommandError):  # 빠짐 — argparse 필수
            self.run_import(default_roles())

    def test_tc24_slots_labels(self):
        data = default_roles()
        data["forms"]["D03"]["slots"] = "leader"
        data["forms"]["D10"]["labels"] = {"owner": "기록자", "leader": "책임자"}
        self.run_import(data, "--actor", "DEV-001")
        form = RoleForm.objects.get(type_code="D10")
        self.assertEqual((form.label_owner, form.label_leader), ("기록자", "책임자"))
        line = roles.approval_line("D03")
        self.assertEqual([s["role"] for s in line["slots"]], ["leader"])


class FormRowTests(TestCase):
    """ADM-TC-21(R31·F22)."""

    def test_tc21_install(self):
        self.assertFalse(DocumentTemplate.objects.exists())  # 테스트 DB = 양식 0 → 0004가 행 0
        self.assertFalse(RoleForm.objects.exists())
        call_command("install_document_templates", "--production-log", stdout=StringIO())
        rows = {f.type_code: (f.slots, f.label_owner) for f in RoleForm.objects.all()}
        self.assertEqual(rows["D10"], ("owner_leader", "작성자"))
        self.assertEqual(rows["PROD-LOG"], ("none", None))
        self.assertEqual(rows["D01"], ("owner", None))
        self.assertEqual(rows["CCP-1P"], ("owner_leader", None))
        count = RoleForm.objects.count()
        ensure_p15_templates()
        self.assertEqual(RoleForm.objects.count(), count)  # 있으면 그대로
        self.assertEqual(store.ensure_form_rows(["D01", "NEW-X"]), ["NEW-X"])


class StaffNotFoundTests(SetupCase):
    def test_404(self):
        with self.assertRaises(StaffNotFound):
            services.set_staff_active(1, 999, {"active": True})


class NoConfigInvalidTests(TestCase):
    """ADM-TC-18: config_invalid 경로가 코드에 남지 않음(테스트 제외)."""

    def test_tc18(self):
        root = Path(__file__).resolve().parents[3]
        found = []
        for path in list((root / "backend" / "apps").rglob("*.py")) + list(
            (root / "frontend" / "static" / "temp-entry").rglob("*.js")
        ):
            if "tests" in path.parts or path.name.startswith("test_"):
                continue
            text = path.read_text(encoding="utf-8")
            for word in (
                "RoleConfigInvalid",
                "ROLE_CONFIG_INVALID",
                "config_error",
                "HACCP_ROLES_FILE",
            ):
                if word in text:
                    found.append(f"{path.name}: {word}")
        self.assertEqual(found, [])


class StartCheckPageTests(TestCase):
    """ADM-TC-19(서버 쪽): 시작 확인 부품은 문서 화면 스위치와 무관하게 늘 실림(R51·R69)."""

    def test_always_loaded(self):
        from django.test import override_settings

        for temp_entry, menu in ((False, "dev"), (True, "dev"), (False, "haccp")):
            with self.subTest(temp_entry=temp_entry, menu=menu):
                with override_settings(HACCP_TEMP_ENTRY=temp_entry, HACCP_DOC_MENU=menu):
                    html = self.client.get("/").content.decode()
                self.assertIn("start-check/start-check.css", html)
                self.assertLess(
                    html.index("start-check/start-check.js"), html.index("prototype/js/app.js")
                )
        self.assertEqual(self.client.get("/api/v1/staff").status_code, 200)  # 0명 판정 경로(R51)
