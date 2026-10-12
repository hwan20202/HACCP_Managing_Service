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


class SeedP4Tests(TestCase):
    """P4 개발 시드(REQ-TC-032): P5부터 REQ F01·F02로 만들고(REQ-S2-Q11), 다시 실행해도 늘지 않으며,
    결재 결합 상태가 맞아야 한다."""

    def test_seed_is_idempotent_and_consistent(self):
        from apps.devtools.seed_p4 import seed_p4
        from apps.document_workflow.tests.base import invariant_violations
        from apps.documents.models import Document

        # 입고 LOT 5개(오늘 3·전날 2) × D01·D02·D03 + 배치 2개 × CCP 3(P6a — D03도 LOT마다)
        self.assertEqual(seed_p4("2026-10-11"), {"documents": 21})
        keys = set(Document.objects.values_list("record_key", flat=True))
        lots = [f"lot:{n}" for n in range(1, 6)]
        expected = {f"{c}|{lot}" for c in ("D01", "D02", "D03") for lot in lots}
        expected |= {f"CCP-{p}|batch:{b}" for p in ("1P", "2B", "3P") for b in (1, 2)}
        self.assertEqual(keys, expected)
        self.assertEqual(seed_p4("2026-10-11"), {"documents": 0})
        self.assertEqual(seed_p4("2026-10-12"), {"documents": 0})
        self.assertEqual(invariant_violations(), [])
        statuses = set(Document.objects.values_list("status", flat=True))
        self.assertEqual(
            statuses, {"draft", "completed", "submitted", "approved", "rejected", "correcting"}
        )
        d03 = Document.objects.get(record_key="D03|lot:1")
        self.assertEqual(d03.assignee_id, 2)  # P4 시드와 같게 D03·CCP는 담당자 2
        d03_status = dict(
            Document.objects.filter(
                record_key__in=[f"D03|lot:{n}" for n in (1, 2, 3, 4)]
            ).values_list("record_key", "status")
        )
        self.assertEqual(  # 오늘 LOT 1 승인, LOT 2 작성완료, LOT 3 작성중(P6a-S1 7장)
            d03_status,
            {
                "D03|lot:1": "approved",
                "D03|lot:2": "completed",
                "D03|lot:3": "draft",
                "D03|lot:4": "correcting",  # P6 정정 중
            },
        )
        self.assertEqual(
            set(
                Document.objects.filter(record_key__startswith="D03|").values_list(
                    "template__version", flat=True
                )
            ),
            {2},
        )
