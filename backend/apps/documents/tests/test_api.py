"""API 테스트 (수준 A): Django 테스트 Client로 /api/v1/ 을 호출한다."""

import json
import os
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, TestCase, override_settings

from apps.documents import flows
from apps.documents.models import Document
from apps.documents.tests.base import ccp_payload, make_document, setup_reference_data, snapshot

TRACE_MIDDLEWARE = "apps.devtools.middleware.TraceMiddleware"


class ApiTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.t = setup_reference_data()

    def send(self, method, path, body=None, staff=3, raw=None):
        headers = {} if staff is None else {"HTTP_X_STAFF_ID": str(staff)}
        data = raw if raw is not None else (json.dumps(body) if body is not None else None)
        return getattr(self.client, method)(
            f"/api/v1/{path}", data=data, content_type="application/json", **headers
        )

    def assertError(self, response, status, code):
        self.assertEqual(response.status_code, status, response.content)
        body = response.json()
        self.assertEqual(body["code"], code)
        self.assertEqual(set(body), {"code", "message", "details"})  # DOC-NFR-05


class ReadApiTests(ApiTestCase):
    def test_tc002_staff(self):
        response = self.client.get("/api/v1/staff")
        self.assertEqual(response.json(), {"items": [1, 2, 3, 4, 5]})

    def test_tc004_templates(self):
        self.assertEqual(len(self.client.get("/api/v1/templates").json()["items"]), 2)

    def test_tc006_template_detail(self):
        ok = self.client.get(f"/api/v1/templates/{self.t['ccp'].template_id}")
        self.assertEqual(ok.status_code, 200)
        self.assertIn("schema", ok.json())
        self.assertError(self.client.get("/api/v1/templates/9999"), 404, "TEMPLATE_NOT_FOUND")

    def test_tc032_invalid_filters(self):
        for query in (
            "from=2026-10-09&to=2026-10-01",
            "from=2025-01-01&to=2026-10-09",
            "page=0",
            "status=foo",
            "page=-1",
            "author_id=abc",
        ):
            with self.subTest(query):
                self.assertError(
                    self.client.get(f"/api/v1/documents?{query}"), 400, "INVALID_FILTER"
                )

    def test_tc041_deleted_and_missing(self):
        deleted, _ = make_document(self.t["ccp"], deleted=True)
        for document_id in (deleted.document_id, 99999):
            with self.subTest(document_id):
                self.assertError(
                    self.client.get(f"/api/v1/documents/{document_id}"), 404, "DOCUMENT_NOT_FOUND"
                )

    def test_reads_need_no_staff_header(self):
        doc, _ = make_document(self.t["ccp"])
        for path in ("staff", "templates", "documents", f"documents/{doc.document_id}"):
            with self.subTest(path):
                self.assertEqual(self.client.get(f"/api/v1/{path}").status_code, 200)


class CreateApiTests(ApiTestCase):
    def test_tc011_create(self):
        response = self.send("post", "documents", ccp_payload(self.t["ccp"]))
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual((body["status"], body["created_by"]), ("draft", 3))
        self.assertNotIn("trace", body)  # 테스트 설정 = 개발 콘솔 꺼짐

    def test_tc012_staff_header(self):
        payload = ccp_payload(self.t["ccp"])
        self.assertError(
            self.send("post", "documents", payload, staff=None), 400, "STAFF_HEADER_MISSING"
        )
        self.assertError(self.send("post", "documents", payload, staff=999), 403, "INVALID_STAFF")
        self.assertError(self.send("post", "documents", payload, staff="abc"), 403, "INVALID_STAFF")
        self.assertEqual(Document.objects.count(), 0)

    def test_tc020_bad_body(self):
        self.assertError(self.send("post", "documents", raw="{not json"), 400, "INVALID_REQUEST")
        self.assertError(self.send("post", "documents", raw="[1, 2]"), 400, "INVALID_REQUEST")
        payload = ccp_payload(self.t["ccp"], status="approved")
        self.assertError(self.send("post", "documents", payload), 400, "INVALID_REQUEST")
        response = self.client.post(
            "/api/v1/documents",
            data="a=1",
            content_type="application/x-www-form-urlencoded",
            HTTP_X_STAFF_ID="3",
        )
        self.assertError(response, 400, "INVALID_REQUEST")

    def test_validation_error_details(self):
        response = self.send("post", "documents", ccp_payload(self.t["ccp"], work_date="bad"))
        self.assertError(response, 400, "VALIDATION_ERROR")
        self.assertEqual(response.json()["details"][0]["path"], "work_date")


class UpdateDeleteApiTests(ApiTestCase):
    def setUp(self):
        self.doc, self.rows = make_document(self.t["ccp"])

    def test_tc051_patch(self):
        body = {
            "document": {"subject": "변경"},
            "sections": {
                "update": [{"section_id": self.rows["r1"].section_id, "values": {"temp": 90}}]
            },
        }
        response = self.send("patch", f"documents/{self.doc.document_id}", body)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["subject"], "변경")

    def test_tc058_patch_shape(self):
        path = f"documents/{self.doc.document_id}"
        self.assertError(self.send("patch", path, {}), 400, "NO_CHANGES")
        self.assertError(self.send("patch", path, {"sections": {"add": []}}), 400, "NO_CHANGES")
        self.assertError(
            self.send("patch", path, {"document": {"template_id": 2}}), 400, "INVALID_REQUEST"
        )
        self.assertError(
            self.send("patch", path, {"sections": {"update": [{"values": {}}]}}),
            400,
            "INVALID_REQUEST",
        )

    def test_tc059_patch_deleted(self):
        doc, _ = make_document(self.t["ccp"], deleted=True)
        self.assertError(
            self.send("patch", f"documents/{doc.document_id}", {"document": {"subject": "x"}}),
            404,
            "DOCUMENT_NOT_FOUND",
        )

    def test_patch_locked(self):
        doc, _ = make_document(self.t["ccp"], status="submitted")
        self.assertError(
            self.send("patch", f"documents/{doc.document_id}", {"document": {"subject": "x"}}),
            409,
            "DOCUMENT_LOCKED",
        )

    def test_tc071_delete_then_hidden(self):
        response = self.send("delete", f"documents/{self.doc.document_id}")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b"")
        self.assertEqual(
            self.client.get(f"/api/v1/documents/{self.doc.document_id}").status_code, 404
        )
        listed = [i["document_id"] for i in self.client.get("/api/v1/documents").json()["items"]]
        self.assertNotIn(self.doc.document_id, listed)

    def test_tc073_delete_twice(self):
        self.send("delete", f"documents/{self.doc.document_id}")
        self.assertError(
            self.send("delete", f"documents/{self.doc.document_id}"), 404, "DOCUMENT_NOT_FOUND"
        )

    def test_delete_not_deletable(self):
        doc, _ = make_document(self.t["ccp"], status="approved")
        self.assertError(
            self.send("delete", f"documents/{doc.document_id}"), 409, "DOCUMENT_NOT_DELETABLE"
        )

    def test_method_not_allowed(self):
        self.assertEqual(
            self.client.put(f"/api/v1/documents/{self.doc.document_id}").status_code, 405
        )


@override_settings(
    ROOT_URLCONF="apps.devtools.test_urls",
    MIDDLEWARE=[*settings.MIDDLEWARE, TRACE_MIDDLEWARE],
)
class TraceApiTests(ApiTestCase):
    """DOC-TC-091: 개발 콘솔이 켜졌을 때 trace 단계 순서가 설계 흐름과 같다."""

    def step_ids(self, trace):
        return [s["step_id"] for s in trace["steps"]]

    def test_tc091_create_trace_matches_flow(self):
        response = self.send("post", "documents", ccp_payload(self.t["ccp"]))
        trace = response.json()["trace"]
        self.assertTrue(flows.matches("DOC-CRT", self.step_ids(trace)), self.step_ids(trace))
        self.assertEqual(response["X-Trace-Id"], trace["trace_id"])
        lock_sql = [
            q["sql"] for s in trace["steps"] if s["step_id"] == "DOC-CRT-07" for q in s["sql"]
        ]
        self.assertTrue(any(sql.startswith('INSERT INTO "document"') for sql in lock_sql))

    def test_tc091_update_trace_matches_flow(self):
        doc, rows = make_document(self.t["ccp"])
        body = {
            "document": {"subject": "B"},
            "sections": {
                "add": [
                    {
                        "section_def": "rounds",
                        "values": {"round": "11:00", "temp": 86, "hold_sec": 15, "measured_by": 3},
                    }
                ],
                "update": [{"section_id": rows["r1"].section_id, "values": {"temp": 85.5}}],
                "delete": [rows["r2"].section_id],
            },
        }
        trace = self.send("patch", f"documents/{doc.document_id}", body).json()["trace"]
        ids = self.step_ids(trace)
        self.assertTrue(flows.matches("DOC-UPD", ids), ids)
        lock = next(s for s in trace["steps"] if s["step_id"] == "DOC-UPD-03")
        self.assertIn('UPDATE "document"', lock["sql"][0]["sql"])
        self.assertIn("status", lock["sql"][0]["sql"])

    def test_tc091_delete_trace_via_header(self):
        doc, _ = make_document(self.t["ccp"])
        response = self.send("delete", f"documents/{doc.document_id}")
        self.assertEqual(response.status_code, 204)
        trace = self.client.get(f"/api/dev/traces/{response['X-Trace-Id']}").json()
        self.assertTrue(flows.matches("DOC-DEL", self.step_ids(trace)))

    def test_failed_step_is_marked(self):
        doc, _ = make_document(self.t["ccp"], status="submitted")
        trace = self.send(
            "patch", f"documents/{doc.document_id}", {"document": {"subject": "x"}}
        ).json()["trace"]
        last = trace["steps"][-1]
        self.assertEqual((last["step_id"], last["result"]), ("DOC-UPD-03a", "fail"))

    def test_snapshot_includes_deleted_document(self):
        doc, _ = make_document(self.t["ccp"])
        self.send("delete", f"documents/{doc.document_id}")
        data = self.client.get(f"/api/dev/snapshot?document_id={doc.document_id}").json()
        self.assertTrue(data["deleted"])
        self.assertEqual(len(data["tables"]["doc_section"]), 3)
        self.assertEqual(data["tables"]["document"][0]["deleted_by_id"], 3)

    def test_flows_endpoint(self):
        self.assertEqual(
            self.client.get("/api/dev/flows/DOC-DEL").json()["steps"], flows.FLOWS["DOC-DEL"]
        )
        self.assertEqual(self.client.get("/api/dev/flows/NOPE").status_code, 404)


class TraceDisabledTests(ApiTestCase):
    """DOC-TC-092: 개발 콘솔이 꺼진 설정(테스트·운영)에서는 trace와 /api/dev/가 없다."""

    def test_tc092_no_trace_and_no_dev_routes(self):
        doc, _ = make_document(self.t["ccp"])
        response = self.send(
            "patch", f"documents/{doc.document_id}", {"document": {"subject": "x"}}
        )
        self.assertNotIn("trace", response.json())
        self.assertNotIn("X-Trace-Id", response)
        for path in ("/api/dev/snapshot?document_id=1", "/api/dev/flows", "/api/dev/traces/x"):
            with self.subTest(path):
                self.assertEqual(self.client.get(path).status_code, 404)
        self.assertEqual(snapshot(doc.document_id)[0]["subject"], "x")


class ProductionDevConsoleTests(SimpleTestCase):
    def test_tc092_production_cannot_enable_dev_console(self):
        env = os.environ.copy()
        env.update(
            {
                "HACCP_ENV_FILE": os.devnull,
                "DJANGO_SECRET_KEY": "test-only-secret-with-more-than-fifty-characters-123456789",
                "DJANGO_ALLOWED_HOSTS": "haccp.example.com",
                "HACCP_DEV_CONSOLE": "true",
                "DJANGO_SETTINGS_MODULE": "config.settings.production",
            }
        )
        code = (
            "import django; django.setup(); from django.conf import settings; "
            "import config.urls as u; "
            "print(settings.HACCP_DEV_CONSOLE, "
            "any('devtools' in m for m in settings.MIDDLEWARE), "
            "'apps.devtools' in settings.INSTALLED_APPS, "
            "any(str(p.pattern).startswith('api/dev/') for p in u.urlpatterns))"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=Path(__file__).resolve().parents[3],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.split(), ["False", "False", "False", "False"])
