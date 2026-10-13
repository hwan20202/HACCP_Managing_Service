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


@override_settings(ROOT_URLCONF="apps.devtools.test_urls")
class D03FixtureTests(TestCase):
    """P6 S5 프리셋 사전 조건(ISS-019): 새 LOT·D03을 실제 함수로 원하는 상태까지 만든다."""

    def setUp(self):
        from apps.doc_requirements.tests.base import setup_req

        setup_req()

    def tearDown(self):
        from apps.document_workflow.tests.base import invariant_violations

        self.assertEqual(invariant_violations(), [])

    def post(self, body):
        import json

        return self.client.post(
            "/api/dev/fixtures/d03", data=json.dumps(body), content_type="application/json"
        )

    def test_states(self):
        from apps.devstock.models import Lot
        from apps.documents import services as doc

        expected = {
            "draft": "draft",
            "completed": "completed",
            "submitted": "submitted",
            "approved": "approved",
            "correcting": "correcting",
            "correction_completed": "completed",
            "correction_submitted": "submitted",
        }
        lots = set()
        for state, status in expected.items():
            with self.subTest(state=state):
                res = self.post({"state": state})
                self.assertEqual(res.status_code, 201, res.content)
                body = res.json()
                self.assertEqual(body["status"], status)
                self.assertEqual(doc.get_document(body["document_id"])["version"], body["version"])
                lots.add(body["lot_id"])
        self.assertEqual(len(lots), len(expected))  # 매번 새 LOT
        # 승인(적합)이면 판정이 전달돼 LOT이 사용 가능
        approved = self.post({"state": "approved"}).json()
        self.assertEqual(Lot.objects.get(pk=approved["lot_id"]).status, "AVAILABLE")

    def test_options(self):
        from apps.devstock.models import Lot
        from apps.documents import services as doc

        fail = self.post({"state": "completed", "verdict": "FAIL"}).json()
        self.assertEqual(len(doc.get_document(fail["document_id"])["deviations"]), 1)
        used = self.post({"state": "correcting", "used": True, "change_to": "FAIL"}).json()
        self.assertEqual(Lot.objects.get(pk=used["lot_id"]).status, "CONSUMED")
        self.assertEqual(used["correction"]["reason"], "콘솔 준비: 판정 재확인")
        edited = self.post({"state": "correcting", "edited": True}).json()
        self.assertEqual(doc.get_document(edited["document_id"])["assignee_id"], 2)
        for body in ({"state": "x"}, {"verdict": "OK"}, {"change_to": "?"}):
            with self.subTest(body=body):
                self.assertEqual(self.post(body).status_code, 400)

    def test_p7_tc102_count_and_date(self):
        res = self.post({"state": "completed", "count": 3, "received_date": "2026-10-21"})
        self.assertEqual(res.status_code, 201, res.content)
        items = res.json()["items"]
        self.assertEqual(len(items), 3)
        self.assertEqual({i["status"] for i in items}, {"completed"})
        self.assertEqual(
            [i["lot_number"] for i in items], ["RM-1021-01", "RM-1021-02", "RM-1021-03"]
        )
        more = self.post({"received_date": "2026-10-21"}).json()  # 같은 날 이어서
        self.assertEqual(more["lot_number"], "RM-1021-04")
        for body in (
            {"count": 11},
            {"count": 0},
            {"received_date": "2026-13-01"},
            {"inspector": "4"},
            {"state": "completed", "inspector": None},
        ):
            with self.subTest(body=body):
                self.assertEqual(self.post(body).status_code, 400)

    def test_p7_states_and_inspector(self):
        from apps.documents import services as doc

        partial = self.post({"state": "submitted_partial"}).json()
        self.assertEqual(partial["status"], "submitted")
        from apps.approvals import services as apr

        request = apr.list_requests(partial["document_id"])["items"][0]
        self.assertEqual(
            [(x["approver_id"], x["state"]) for x in request["slots"]],
            [(3, "approved"), (1, "pending")],
        )
        rejected = self.post({"state": "rejected"}).json()
        self.assertEqual(rejected["status"], "rejected")
        empty = self.post({"inspector": None}).json()
        info = next(
            s["values"]
            for s in doc.get_document(empty["document_id"])["sections"]
            if s["section_def"] == "info"
        )
        self.assertNotIn("inspector", info)

    def test_snapshot_lots(self):
        made = self.post({"state": "approved"}).json()
        snap = self.client.get(f"/api/dev/snapshot?document_id={made['document_id']}").json()
        self.assertEqual(
            [(r["id"], r["status"]) for r in snap["tables"]["lots"]],
            [(made["lot_id"], "AVAILABLE")],
        )
