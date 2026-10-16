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
        with override_settings(HACCP_TEMP_ENTRY=False, HACCP_DOC_MENU="dev"):
            response = self.client.get("/")
        self.assertContains(response, 'id="pageContainer"')
        self.assertNotContains(response, 'data-page="doc-box"')
        self.assertNotContains(response, "temp-entry/core.js")
        self.assertNotContains(response, "TEMP_ENTRY_CONFIG")

    def test_tab_shown_without_dev_console(self):
        with override_settings(HACCP_TEMP_ENTRY=True, DEBUG=False, HACCP_DEV_CONSOLE=False):
            response = self.client.get("/")
        self.assertContains(response, 'data-page="doc-box"')
        self.assertContains(response, 'data-page="approval-box"')
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
        # P5 REQ-SC-01: 개발 콘솔이 켜져 있을 때만 "작성 요구 [임시]"(C2부터 수불 앱 테이블 사용)
        self.assertContains(response, 'id="nav-temp-req"')
        with override_settings(HACCP_TEMP_ENTRY=True, DEBUG=False, HACCP_DEV_CONSOLE=False):
            self.assertNotContains(self.client.get("/"), 'id="nav-temp-req"')
        self.assertContains(response, "temp-entry/requirement/requirement.js")

    def test_temp_entry_scripts_load_before_app_js(self):
        with override_settings(HACCP_TEMP_ENTRY=True):
            html = self.client.get("/").content.decode()
        self.assertLess(html.index("temp-entry/core.js"), html.index("prototype/js/app.js"))

    def test_qa_banner_is_explicit_and_not_shown_in_production(self):
        with override_settings(HACCP_ENVIRONMENT="qa", DEBUG=False, HACCP_DOC_MENU="haccp"):
            response = self.client.get("/")
        self.assertContains(response, 'id="qaSiteBanner"')
        self.assertContains(response, "window.HACCP_SITE = {qa: true}")
        with override_settings(HACCP_ENVIRONMENT="production"):
            self.assertNotContains(self.client.get("/"), 'id="qaSiteBanner"')


class DocMenuSettingTests(SimpleTestCase):
    """P10-TC-030(서버 부분): HACCP_DOC_MENU 값 검사·화면 값. 메뉴 자리 HTML은 S5."""

    def test_env_choice(self):
        import os
        from unittest import mock

        from config.settings.base import env_choice
        from django.core.exceptions import ImproperlyConfigured

        cases = (("", "dev"), ("haccp", "haccp"), (" HACCP ", "haccp"), ("dev", "dev"))
        for raw, expected in cases:
            with self.subTest(raw=raw), mock.patch.dict(os.environ, {"HACCP_DOC_MENU": raw}):
                self.assertEqual(env_choice("HACCP_DOC_MENU", ("dev", "haccp"), "dev"), expected)
        with mock.patch.dict(os.environ, {"HACCP_DOC_MENU": "menu"}):
            with self.assertRaises(ImproperlyConfigured):
                env_choice("HACCP_DOC_MENU", ("dev", "haccp"), "dev")

    def test_context_value(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        data_file = Path(directory.name) / "data.js"
        data_file.write_text("const HACCP_DATA = {};", encoding="utf-8")
        for value in ("dev", "haccp"):
            with (
                self.subTest(value=value),
                override_settings(PROTOTYPE_DATA_FILE=data_file, HACCP_DOC_MENU=value),
            ):
                self.assertEqual(self.client.get("/").context["doc_menu"], value)


class DocMenuPlacementTests(SimpleTestCase):
    """P10-TC-030(화면 부분): HACCP_DOC_MENU에 따라 문서함·결재함 메뉴가 한 곳에만."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        data_file = Path(directory.name) / "data.js"
        data_file.write_text("const HACCP_DATA = {};", encoding="utf-8")
        self.enterContext(override_settings(PROTOTYPE_DATA_FILE=data_file))

    def html(self, **settings_):
        with override_settings(**settings_):
            return self.client.get("/").content.decode()

    def test_dev_menu_in_dev_section(self):
        html = self.html(HACCP_TEMP_ENTRY=True, HACCP_DOC_MENU="dev")
        self.assertEqual(html.count('data-page="doc-box"'), 1)
        self.assertLess(html.index("개발 검증"), html.index('id="nav-doc-box"'))
        self.assertIn('docMenu: "dev"', html)

    def test_haccp_menu_on_top_of_haccp_section(self):
        html = self.html(HACCP_TEMP_ENTRY=True, HACCP_DOC_MENU="haccp")
        self.assertEqual(html.count('data-page="doc-box"'), 1)
        start = html.index("HACCP 관리</span>")
        self.assertLess(start, html.index('id="nav-doc-box"'))
        self.assertLess(html.index('id="nav-approval-box"'), html.index('id="nav-ccp-monitoring"'))
        self.assertIn('docMenu: "haccp"', html)

    def test_haccp_menu_without_temp_entry(self):
        html = self.html(HACCP_TEMP_ENTRY=False, HACCP_DOC_MENU="haccp")
        self.assertIn('id="nav-doc-box"', html)
        self.assertIn("temp-entry/document/document.js", html)  # 스크립트는 로드
        self.assertNotIn("te-nav-section", html)  # 개발 검증 섹션은 없음

    def test_dev_menu_hidden_without_temp_entry(self):
        html = self.html(HACCP_TEMP_ENTRY=False, HACCP_DOC_MENU="dev")
        self.assertNotIn('id="nav-doc-box"', html)
        self.assertNotIn("temp-entry/core.js", html)
