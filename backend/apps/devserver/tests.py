"""DEV-TC-001/002: 개발 서버 정적 파일 no-cache (ISS-001 보완 사이클 R2)."""

import os
import subprocess
import sys
from pathlib import Path

from django.core.handlers.wsgi import WSGIHandler
from django.test import RequestFactory, SimpleTestCase, override_settings

from apps.devserver.handlers import NoCacheStaticFilesHandler


class NoCacheStaticTests(SimpleTestCase):
    @override_settings(DEBUG=True)
    def test_dev_tc001_static_response_is_no_cache(self):
        handler = NoCacheStaticFilesHandler(WSGIHandler())
        request = RequestFactory().get("/static/prototype/js/app.js")
        response = handler.get_response(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "no-cache")
        self.assertIn("Last-Modified", response)  # 304 재검증에 쓰인다

    def test_dev_tc002_development_runserver_uses_devserver(self):
        env = os.environ.copy()
        env.update(
            {"HACCP_ENV_FILE": os.devnull, "DJANGO_SETTINGS_MODULE": "config.settings.development"}
        )
        code = (
            "import django; django.setup(); "
            "from django.core.management import get_commands; "
            "print(get_commands()['runserver'])"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=Path(__file__).resolve().parents[2],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "apps.devserver")

    def test_dev_tc002_not_installed_outside_development(self):
        from django.conf import settings

        self.assertNotIn("apps.devserver", settings.INSTALLED_APPS)
