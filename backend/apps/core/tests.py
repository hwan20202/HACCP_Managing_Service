import os
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path
from unittest.mock import patch

from django.db import OperationalError
from django.test import SimpleTestCase, TestCase, override_settings


class LiveTests(SimpleTestCase):
    def test_liveness_works_without_database_access(self):
        response = self.client.get("/health/live/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "service": "haccp"})
        self.assertIn("no-store", response["Cache-Control"])

    def test_system_test_page_references_status_assets(self):
        response = self.client.get("/test/")
        self.assertContains(response, "/static/system-test/app.js")
        self.assertContains(response, "/static/system-test/main.css")
        self.assertContains(response, 'id="live-status"')
        self.assertContains(response, 'id="ready-status"')
        self.assertNotContains(response, "/admin/")
        self.assertNotContains(response, "fonts.googleapis.com")
        self.assertNotContains(response, "fonts.gstatic.com")

    def test_health_only_accepts_read_requests(self):
        self.assertEqual(self.client.post("/health/live/").status_code, 405)
        self.assertEqual(self.client.post("/health/ready/").status_code, 405)

    def test_unknown_host_is_rejected(self):
        self.assertEqual(self.client.get("/", HTTP_HOST="untrusted.invalid").status_code, 400)

    def test_reference_and_environment_files_are_not_routed(self):
        for path in (
            "/data/reference/",
            "/.env",
            "/private-media/example.pdf",
            "/admin/",
            "/files/",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)


class PrototypeTests(SimpleTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.data_file = self.directory / "data.js"
        self.data_file.write_text("const HACCP_DATA = {};", encoding="utf-8")
        self.enterContext(
            override_settings(
                PROTOTYPE_DATA_FILE=self.data_file,
                PROTOTYPE_STANDARD_DIR=self.directory,
            )
        )

    def test_home_loads_legacy_screen_and_links_to_system_test(self):
        response = self.client.get("/")
        self.assertContains(response, 'id="pageContainer"')
        self.assertContains(response, "/static/prototype/js/app.js")
        self.assertContains(response, "/prototype/data.js")
        self.assertContains(response, 'href="/test/"')
        self.assertNotContains(response, 'class="user-info"')
        self.assertNotContains(response, "/admin/")
        self.assertNotContains(response, "fonts.googleapis.com")
        self.assertNotContains(response, "fonts.gstatic.com")

    def test_only_selected_data_file_is_served(self):
        response = self.client.get("/prototype/data.js")
        self.addCleanup(response.close)
        self.assertEqual(b"".join(response.streaming_content), self.data_file.read_bytes())
        self.assertIn("javascript", response["Content-Type"])
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(self.client.get("/prototype/data.js.bak").status_code, 404)

    def test_missing_data_has_clear_setup_page_and_working_test_page(self):
        self.data_file.unlink()
        response = self.client.get("/")
        self.assertContains(response, "시제품 데이터가")
        self.assertContains(response, 'href="/test/"')
        self.assertNotContains(response, "/static/prototype/js/app.js")
        self.assertEqual(self.client.get("/prototype/data.js").status_code, 404)
        self.assertEqual(self.client.get("/test/").status_code, 200)

    def test_standard_pdf_handles_mac_and_windows_filenames(self):
        filename = "기타가공품 기준서-250831.pdf"
        for normalization in ("NFC", "NFD"):
            with self.subTest(normalization=normalization):
                pdf = self.directory / unicodedata.normalize(normalization, filename)
                pdf.write_bytes(b"%PDF-1.7\n")
                response = self.client.get(f"/setup_standard/{filename}")
                try:
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(b"".join(response.streaming_content), pdf.read_bytes())
                    self.assertEqual(response["X-Frame-Options"], "SAMEORIGIN")
                finally:
                    response.close()
                    pdf.unlink()

    def test_unlisted_reference_files_and_traversal_are_not_served(self):
        (self.directory / "other.pdf").write_bytes(b"private")
        for path in ("other.pdf", "../data.js", "%2e%2e%2fdata.js", "..%5cdata.js"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(f"/setup_standard/{path}").status_code, 404)

    def test_missing_standard_returns_404(self):
        self.assertEqual(
            self.client.get("/setup_standard/기타가공품 기준서-250831.pdf").status_code, 404
        )


class ReadyTests(TestCase):
    def test_migrated_database_is_ready(self):
        response = self.client.get("/health/ready/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "database": "ok"})
        self.assertIn("no-store", response["Cache-Control"])

    @patch("apps.core.views.connection.cursor", side_effect=OperationalError("private DB path"))
    def test_unavailable_database_returns_503_without_details(self, cursor):
        response = self.client.get("/health/ready/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["database"], "unavailable")
        self.assertNotContains(response, "private DB path", status_code=503)

    @patch("apps.core.views.MigrationExecutor")
    def test_pending_migrations_are_not_ready(self, executor):
        executor.return_value.migration_plan.return_value = [object()]
        self.assertEqual(self.client.get("/health/ready/").status_code, 503)

    @patch("apps.core.views.connection.introspection.table_names", return_value=[])
    def test_missing_application_tables_are_not_ready(self, tables):
        self.assertEqual(self.client.get("/health/ready/").status_code, 503)


class ProductionSettingsTests(SimpleTestCase):
    def run_settings(self, overrides):
        env = os.environ.copy()
        env.update(
            {
                "HACCP_ENV_FILE": os.devnull,
                "DJANGO_SECRET_KEY": "test-only-secret-with-more-than-fifty-characters-123456789",
                "DJANGO_ALLOWED_HOSTS": "haccp.example.com",
                "DJANGO_HTTPS_ENABLED": "true",
            }
        )
        env.update(overrides)
        return subprocess.run(
            [sys.executable, "-c", "import config.settings.production"],
            cwd=Path(__file__).resolve().parents[2],
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
        )

    def test_valid_production_settings_load(self):
        result = self.run_settings({})
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_secret_is_rejected(self):
        result = self.run_settings({"DJANGO_SECRET_KEY": ""})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DJANGO_SECRET_KEY", result.stderr)

    def test_wildcard_host_is_rejected(self):
        result = self.run_settings({"DJANGO_ALLOWED_HOSTS": "*"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DJANGO_ALLOWED_HOSTS", result.stderr)

    def test_invalid_boolean_is_rejected(self):
        result = self.run_settings({"DJANGO_HTTPS_ENABLED": "not-a-boolean"})
        self.assertNotEqual(result.returncode, 0)
