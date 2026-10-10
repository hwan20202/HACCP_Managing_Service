"""개발 콘솔 화면(/dev/) 노출 조건."""

from django.conf import settings
from django.test import SimpleTestCase, TestCase, override_settings


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


class SeedWorkflowTests(TestCase):
    """P3 개발 시드: 결재 데이터는 WF 함수로 만들어 결합 상태가 맞아야 한다(PS-05 1건만 예외)."""

    def test_seed_states_are_consistent(self):
        from apps.devtools.seed_workflow import seed_workflow
        from apps.document_workflow.tests.base import invariant_violations, sql

        made = seed_workflow()
        self.assertEqual((made["scenarios"], made["paging"], made["mismatch"]), (5, 21, 1))
        bad = invariant_violations()
        self.assertEqual(len(bad), 1, bad)
        subject = sql("SELECT subject FROM document WHERE document_id=%s", [bad[0][0]])[0][0]
        self.assertIn("PS-05", subject)
        pairs = dict(
            ((s, r), n)
            for s, r, n in sql(
                "SELECT d.status, (SELECT status FROM approval_request r WHERE"
                " r.document_id=d.document_id ORDER BY attempt DESC LIMIT 1), COUNT(*)"
                " FROM document d WHERE deleted_at IS NULL GROUP BY 1, 2"
            )
        )
        self.assertEqual(pairs[("approved", "approved")], 1)
        self.assertEqual(pairs[("rejected", "rejected")], 1)
        self.assertEqual(pairs[("submitted", "in_progress")], 24)
