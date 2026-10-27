"""PLG-A06~A08 API (PLG-TC-09 — 직원 없음, 상태 코드·오류 모양)."""

import json

from .base import PlgTestCase, builtin


class ApiTests(PlgTestCase):
    def call(self, method, path, body=None, staff=1):
        headers = {} if staff is None else {"HTTP_X_STAFF_ID": str(staff)}
        kwargs = {"content_type": "application/json"} if body is not None else {}
        data = json.dumps(body) if body is not None else None
        fn = getattr(self.client, method)
        return (
            fn(f"/api/v1/{path}", data, **kwargs, **headers)
            if data
            else fn(f"/api/v1/{path}", **headers)
        )

    def assertError(self, response, status, code):
        self.assertEqual(response.status_code, status, response.content)
        self.assertEqual(response.json()["code"], code)

    def test_tc09_staff_header(self):
        self.assertError(
            self.call("post", "processes", {"name": "분쇄", "mode": "JUDGE"}, staff=None),
            400,
            "STAFF_HEADER_MISSING",
        )
        self.assertError(
            self.call("post", "processes", {"name": "분쇄", "mode": "JUDGE"}, staff=99),
            403,
            "INVALID_STAFF",
        )
        self.assertEqual(
            self.call("get", "processes", staff=None).status_code, 200
        )  # 읽기는 헤더 없이

    def test_process_crud(self):
        r = self.call("post", "processes", {"name": "분쇄", "mode": "JUDGE"})
        self.assertEqual(r.status_code, 201, r.content)
        pid = r.json()["process_id"]
        self.assertError(
            self.call("post", "processes", {"name": "분쇄", "mode": "JUDGE"}), 409, "PLG_NAME_TAKEN"
        )
        r = self.call("patch", f"processes/{pid}", {"description": "곱게"})
        self.assertError(r, 400, "INVALID_REQUEST")  # expected_version 없음
        r = self.call("patch", f"processes/{pid}", {"description": "곱게", "expected_version": 1})
        self.assertEqual((r.status_code, r.json()["version"]), (200, 2))
        self.assertError(
            self.call("post", f"processes/{pid}/active", {"active": False, "expected_version": 1}),
            409,
            "VERSION_CONFLICT",
        )
        r = self.call("post", f"processes/{pid}/active", {"active": False, "expected_version": 2})
        self.assertFalse(r.json()["is_active"])
        self.assertEqual(
            self.call("get", "processes?status=inactive").json()["items"][0]["process_id"], pid
        )
        self.assertError(self.call("delete", f"processes/{pid}"), 400, "INVALID_REQUEST")
        self.assertEqual(
            self.call("delete", f"processes/{pid}?expected_version=3").status_code, 204
        )
        self.assertError(self.call("get", f"processes/{pid}"), 404, "PLG_PROCESS_NOT_FOUND")
        self.assertError(
            self.call(
                "post",
                f"processes/{builtin('OUTER').pk}/active",
                {"active": False, "expected_version": 1},
            ),
            409,
            "PLG_BUILTIN_LOCKED",
        )
        r = self.call("get", f"master-history?target=process&id={pid}", staff=None)
        self.assertEqual(
            [i["action"] for i in r.json()["items"]], ["delete", "deactivate", "update", "create"]
        )
        self.assertError(self.call("get", "processes?kind=x"), 400, "VALIDATION_ERROR")

    def test_template_crud(self):
        pid = self.call("post", "processes", {"name": "분쇄", "mode": "JUDGE"}).json()["process_id"]
        body = {
            "name": "효력환",
            "steps": [{"process_id": pid}, {"process_id": builtin("CCP-1P").pk}],
        }
        r = self.call("post", "process-templates", body)
        self.assertEqual(r.status_code, 201, r.content)
        tid = r.json()["process_template_id"]
        self.assertError(
            self.call("post", "process-templates", {"name": "x", "steps": []}),
            400,
            "PLG_TEMPLATE_INVALID",
        )
        r = self.call("get", f"process-templates/{tid}", staff=None)
        self.assertEqual([s["kind"] for s in r.json()["steps"]], ["GEN", "CCP-1P"])
        r = self.call(
            "patch", f"process-templates/{tid}", {"name": "효력환 기본", "expected_version": 1}
        )
        self.assertEqual(r.json()["name"], "효력환 기본")
        r = self.call("post", f"process-templates/{tid}/copy")
        self.assertEqual((r.status_code, r.json()["name"]), (201, "효력환 기본 (복사)"))
        self.assertEqual(len(self.call("get", "process-templates").json()["items"]), 2)
        r = self.call(
            "post", f"process-templates/{tid}/active", {"active": False, "expected_version": 2}
        )
        self.assertFalse(r.json()["is_active"])
        self.assertEqual(
            self.call("delete", f"process-templates/{tid}?expected_version=3").status_code, 204
        )
        self.assertError(
            self.call("get", f"process-templates/{tid}"), 404, "PLG_TEMPLATE_NOT_FOUND"
        )
        self.assertError(
            self.call("delete", f"processes/{pid}?expected_version=1"), 409, "PLG_IN_USE"
        )  # 복사본이 씀
