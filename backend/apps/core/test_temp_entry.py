"""임시 진입점(사이드 탭) 표시 조건 — dev-notes/common/temp-entry.md, DOC S5."""

import tempfile
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, override_settings

TRACE = "apps.devtools.middleware.TraceMiddleware"


class TempEntryTabTests(SimpleTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        data_file = Path(directory.name) / "data.js"
        data_file.write_text("const HACCP_DATA = {};", encoding="utf-8")
        self.enterContext(override_settings(PROTOTYPE_DATA_FILE=data_file))

    def test_tab_hidden_when_disabled(self):
        with override_settings(HACCP_TEMP_ENTRY=False):
            response = self.client.get("/")
        self.assertContains(response, 'id="pageContainer"')
        self.assertNotContains(response, 'data-page="temp-doc"')
        self.assertNotContains(response, "temp-entry/core.js")
        self.assertNotContains(response, "TEMP_ENTRY_CONFIG")

    def test_tab_shown_without_dev_console(self):
        with override_settings(HACCP_TEMP_ENTRY=True, DEBUG=False, HACCP_DEV_CONSOLE=False):
            response = self.client.get("/")
        self.assertContains(response, 'data-page="temp-doc"')
        self.assertContains(response, "temp-entry/document/document.js")
        self.assertContains(response, "devConsole: false")
        self.assertNotContains(response, 'id="nav-dev-console"')
        # 시제품 스크립트는 그대로 로드된다.
        self.assertContains(response, "/static/prototype/js/app.js")

    @override_settings(
        ROOT_URLCONF="apps.devtools.test_urls", MIDDLEWARE=[*settings.MIDDLEWARE, TRACE]
    )
    def test_dev_console_link_only_when_enabled(self):
        with override_settings(HACCP_TEMP_ENTRY=True, DEBUG=True, HACCP_DEV_CONSOLE=True):
            response = self.client.get("/")
        self.assertContains(response, 'id="nav-dev-console"')
        self.assertContains(response, 'devConsole: true, devConsoleUrl: "/dev/"')
        # P5 REQ-SC-01: 개발 콘솔 + devstock(테스트 설정에 설치됨)일 때만 "작성 요구 [임시]"
        self.assertContains(response, 'id="nav-temp-req"')
        with override_settings(HACCP_TEMP_ENTRY=True, DEBUG=False, HACCP_DEV_CONSOLE=False):
            self.assertNotContains(self.client.get("/"), 'id="nav-temp-req"')
        self.assertContains(response, "temp-entry/requirement/requirement.js")

    def test_temp_entry_scripts_load_before_app_js(self):
        with override_settings(HACCP_TEMP_ENTRY=True):
            html = self.client.get("/").content.decode()
        self.assertLess(html.index("temp-entry/core.js"), html.index("prototype/js/app.js"))
