"""개발 콘솔 화면(/dev/) 노출 조건."""

from django.conf import settings
from django.test import SimpleTestCase, override_settings


class DevConsolePageTests(SimpleTestCase):
    def test_not_routed_by_default(self):
        self.assertEqual(self.client.get("/dev/").status_code, 404)

    @override_settings(
        ROOT_URLCONF="apps.devtools.test_urls",
        MIDDLEWARE=[*settings.MIDDLEWARE, "apps.devtools.middleware.TraceMiddleware"],
    )
    def test_page_when_enabled(self):
        response = self.client.get("/dev/")
        self.assertContains(response, "dev-console/console.js")
        self.assertContains(response, "temp-entry/api-client.js")
        self.assertNotContains(response, "fonts.googleapis.com")
