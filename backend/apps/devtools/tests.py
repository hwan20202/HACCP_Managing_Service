"""개발 콘솔 화면(/dev/) 노출 조건."""

import datetime
import json

from django.conf import settings
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone


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
        self.assertIsNone(d03.assignee_id)  # P14: 문서별 담당자 대신 양식 담당자(roles.json)
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

    def lot_status(self, lot_id):
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("SELECT status FROM lots WHERE id = %s", [lot_id])
            return cursor.fetchone()[0]

    def test_states(self):
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
        self.assertEqual(self.lot_status(approved["lot_id"]), "AVAILABLE")

    def test_options(self):
        from django.db import connection

        from apps.documents import services as doc

        fail = self.post({"state": "completed", "verdict": "FAIL"}).json()
        self.assertEqual(len(doc.get_document(fail["document_id"])["deviations"]), 1)
        used = self.post({"state": "correcting", "used": True, "change_to": "FAIL"}).json()
        # 수불 기준 "사용된 LOT"(C2): 입고 외 이동이 있음, 상태는 판정대로(적합 → AVAILABLE)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT movement_type_code FROM stock_movements WHERE lot_id = %s ORDER BY id",
                [used["lot_id"]],
            )
            self.assertEqual([r[0] for r in cursor.fetchall()], ["RECEIPT", "ADJUST_OUT"])
        self.assertEqual(self.lot_status(used["lot_id"]), "AVAILABLE")
        self.assertEqual(used["correction"]["reason"], "콘솔 준비: 판정 재확인")
        edited = self.post({"state": "correcting", "edited": True}).json()
        self.assertEqual(doc.get_document(edited["document_id"])["subject"], "콘솔 준비: 정정 수정")
        for body in ({"state": "x"}, {"verdict": "OK"}, {"change_to": "?"}):
            with self.subTest(body=body):
                self.assertEqual(self.post(body).status_code, 400)

    def test_p7_tc102_count_and_date(self):
        res = self.post({"state": "completed", "count": 3, "received_date": "2026-10-01"})
        self.assertEqual(res.status_code, 201, res.content)
        items = res.json()["items"]
        self.assertEqual(len(items), 3)
        self.assertEqual({i["status"] for i in items}, {"completed"})
        # LOT 번호는 수불 규칙(C2): LOT 약어 + 입고일, 같은 날 -2, -3…
        self.assertEqual(
            [i["lot_number"] for i in items], ["AYJ261001", "AYJ261001-2", "AYJ261001-3"]
        )
        more = self.post({"received_date": "2026-10-01"}).json()  # 같은 날 이어서
        self.assertEqual(more["lot_number"], "AYJ261001-4")
        for body in (
            {"count": 11},
            {"count": 0},
            {"received_date": "2026-13-01"},
            {"inspector": "4"},
            {"state": "completed", "inspector": None},
            {"received_date": "2099-01-01"},  # 수불: 미래 입고일 거부(C2)
        ):
            with self.subTest(body=body):
                self.assertEqual(self.post(body).status_code, 400)

    def test_p7_s5_lot_only(self):
        """P7 S5: 작성 요구 없이 입고 LOT만(묶음 상세 "문서 없음" 줄)."""
        from apps.doc_requirements import services as req

        res = self.post({"lot_only": True, "received_date": "2026-10-02"})
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.json()["lot_number"], "AYJ261002")
        self.assertIsNone(res.json()["document_id"])
        bundle = req.incoming_bundle(3, datetime.date(2026, 10, 2))
        self.assertEqual(
            [(x["lot_number"], x["document"]) for x in bundle["lots"]], [("AYJ261002", None)]
        )
        self.assertEqual(self.post({"lot_only": "yes"}).status_code, 400)

    def test_p7_states_and_inspector(self):
        from apps.documents import services as doc

        partial = self.post({"state": "submitted_partial"}).json()
        self.assertEqual(partial["status"], "submitted")
        from apps.approvals import services as apr

        request = apr.list_requests(partial["document_id"])["items"][0]
        self.assertEqual(
            [(x["role"], x["approver_id"], x["state"]) for x in request["slots"]],
            [("owner", 3, "approved"), ("leader", None, "pending")],  # P14 역할 칸
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


@override_settings(ROOT_URLCONF="apps.devtools.test_urls")
class S3FixtureTests(TestCase):
    """C3 S5 프리셋 사전 조건: 파일 문서(D01·D02)·P8 점검표(D10·D12·D11)."""

    def setUp(self):
        import tempfile

        from apps.doc_requirements.tests.base import setup_req
        from apps.documents.seed import ensure_p8_templates

        setup_req()
        ensure_p8_templates()
        self.media = override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="haccp-media-"))
        self.media.enable()

    def tearDown(self):
        from apps.document_workflow.tests.base import invariant_violations

        self.media.disable()
        self.assertEqual(invariant_violations(), [])

    def post(self, path, body):
        import json

        return self.client.post(
            f"/api/dev/fixtures/{path}", data=json.dumps(body), content_type="application/json"
        )

    def test_file_doc(self):
        from apps.documents import services as doc

        draft = self.post("file-doc", {}).json()
        self.assertEqual((draft["status"], draft["files"]), ("draft", []))
        done = self.post("file-doc", {"type_code": "D02", "state": "submitted", "files": 2})
        self.assertEqual(done.status_code, 201, done.content)
        body = done.json()
        detail = doc.get_document(body["document_id"])
        self.assertEqual(detail["template"]["type_code"], "D02")
        self.assertEqual(body["status"], "submitted")
        self.assertEqual(
            [f["mime_type"] for f in detail["files"]], ["application/pdf", "image/png"]
        )
        self.assertEqual(self.post("file-doc", {"state": "completed"}).status_code, 400)

    def test_periodic(self):
        import datetime

        res = self.post(
            "periodic",
            {
                "type_code": "D10",
                "week_start": "2026-10-12",
                "days": [
                    {"weekday": 1, "state": "approved", "x": True},
                    {"weekday": 2, "state": "skipped"},
                    {"weekday": 3, "state": "submitted_partial"},
                    {"weekday": 4, "state": "filled"},
                    {"weekday": 5},
                ],
            },
        )
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(
            [i["status"] for i in res.json()["items"]],
            ["approved", "skipped", "submitted", "draft", "draft"],
        )
        free = self.post("periodic", {"type_code": "D10"}).json()
        start = datetime.date.fromisoformat(free["week_start"])
        self.assertEqual((start.isoweekday(), len(free["items"])), (1, 5))
        d11 = self.post("periodic", {"type_code": "D11", "days": [{"state": "completed"}]}).json()
        self.assertEqual(d11["items"][0]["status"], "completed")
        self.assertEqual(self.post("periodic", {"week_start": "2026-10-13"}).status_code, 400)
        self.assertEqual(self.post("periodic", {"type_code": "D03"}).status_code, 400)

    def test_seed_p8(self):
        from apps.devtools.seed_p4 import seed_p8
        from apps.documents.models import Document

        self.assertEqual(seed_p8("2026-10-14"), 7)  # 수요일: D10·D12 월~수 + D11
        self.assertEqual(seed_p8("2026-10-14"), 7)
        statuses = dict(
            Document.objects.filter(record_key__startswith="D10|").values_list(
                "work_date", "status"
            )
        )
        self.assertEqual(
            [statuses[day] for day in sorted(statuses)], ["completed", "skipped", "draft"]
        )


class SeedPrintTests(TestCase):
    """P12 S5 출력 확인용 시드: CCP-1P 승인(개선조치 확인), 2B 결재중, 3P 정정 중.

    다시 실행하면 그대로.
    """

    def test_states_and_print(self):
        from apps.devtools.seed_print import seed_print
        from apps.document_workflow import printing
        from apps.document_workflow.tests.base import invariant_violations
        from apps.documents import services as doc

        out = seed_print("2026-10-12")
        self.assertTrue(out.pop("created"))
        status = {code: doc.get_document(i)["status"] for code, i in out.items()}
        self.assertEqual(
            status, {"CCP-1P": "approved", "CCP-2B": "submitted", "CCP-3P": "correcting"}
        )
        self.assertEqual(invariant_violations(), [])
        p1 = printing.print_sheet(out["CCP-1P"])
        self.assertEqual([b["staff_id"] for b in p1["boxes"]], [3, 5])
        self.assertEqual(p1["document"]["deviations"][0]["checked_by"], 5)
        p2 = printing.print_sheet(out["CCP-2B"])
        self.assertEqual([b["staff_id"] for b in p2["boxes"]], [3, None])
        self.assertEqual(p2["document"]["measured_until"], "2026-10-13")
        p3 = printing.print_sheet(out["CCP-3P"])
        times = [r["values"]["passed_at"][11:] for r in p3["document"]["sections"]["checks"]]
        self.assertIn("12:40", times)  # 승인본(지금 값은 12:45)
        self.assertEqual(len(p3["document"]["deviations"]), 1)
        again = seed_print("2026-10-12")
        self.assertFalse(again.pop("created"))
        self.assertEqual(again, out)

    def test_receiving_seed_two_pages(self):
        """D03 입고일 묶음 시드: 10줄(LOT 번호 순, 상태 섞임) + 문서 없는 LOT은 줄 없음."""
        from apps.devtools.seed_print import seed_print_receiving
        from apps.document_workflow import printing
        from apps.document_workflow.tests.base import invariant_violations

        day = timezone.localdate().isoformat()
        out = seed_print_receiving(day)
        self.assertTrue(out["created"])
        self.assertEqual(invariant_violations(), [])
        data = printing.print_by_query({"kind": "receiving", "type": "D03", "date": day})
        lines = data["lines"]
        self.assertEqual(sorted(line["document_id"] for line in lines), sorted(out["documents"]))
        numbers = [line["lot"]["lot_number"] for line in lines]
        self.assertEqual(numbers, sorted(numbers))  # LOT 번호 순(품목 약어가 앞이라 품목별로 모임)
        by_id = {line["document_id"]: line for line in lines}
        line = [by_id[i] for i in out["documents"]]  # 시드 순서
        self.assertEqual(
            [x["state"] for x in line],
            ["ok", "ok", "ok", "ok", "ok", "draft", "rejected", "ok", "ok", "ok"],
        )
        self.assertEqual(data["printable_count"], 8)
        self.assertEqual({x["lot"]["material_kind"] for x in lines}, {"원료", "부자재"})
        self.assertEqual([b["staff_id"] for b in line[0]["approval"]], [3, 5])
        self.assertEqual([b["staff_id"] for b in line[3]["approval"]], [3, None])
        self.assertEqual(line[7]["values"]["verdict"], "PASS")  # 정정 중 → 승인본
        self.assertEqual(len(data["deviations"]), 2)  # 부적합 1(확인됨) + 정정 중 추가 1
        self.assertEqual(sorted(d["checked_by"] or 0 for d in data["deviations"]), [0, 5])
        again = seed_print_receiving(day)
        self.assertFalse(again["created"])

    def test_weekly_seed(self):
        """D10 주 시드: 월 정정 중 · 화 승인(부적합) · 수 결재중 · 목 작성 안 함 · 금 없음 · 토."""
        from apps.devtools.seed_print import seed_print_weekly
        from apps.document_workflow import printing
        from apps.document_workflow.tests.base import invariant_violations

        out = seed_print_weekly("2026-10-21")
        self.assertTrue(out["created"])
        self.assertEqual(out["week_start"], "2026-10-12")
        self.assertEqual(invariant_violations(), [])
        data = printing.print_by_query({"kind": "weekly", "type": "D10", "date": out["week_start"]})
        self.assertEqual([d["weekday"] for d in data["days"]], list("월화수목금토"))
        self.assertEqual(
            [d["state"] for d in data["days"]], ["ok", "ok", "ok", "skipped", "missing", "ok"]
        )
        self.assertEqual(data["days"][0]["values"]["d_hyg_clothes"], "O")  # 정정 중 → 승인본
        self.assertEqual(data["inspector_id"], 3)  # 토요일 문서
        self.assertEqual(
            [b["staff_id"] for b in data["boxes"]], [3, 1]
        )  # 작성자 = 수(3), 팀장 = 화(1)
        self.assertEqual(data["latest_dates"]["y_water_test_date"], "2026-10-12")
        self.assertEqual(len(data["deviations"]), 1)
        self.assertFalse(seed_print_weekly("2026-10-21")["created"])

    def test_weekly_d12_seed(self):
        """D12 주 시드: 요일마다 결재 칸·공정명, 정정 중 승인본, 토 작성 안 함."""
        from apps.devtools.seed_print import seed_print_weekly_d12
        from apps.document_workflow import printing
        from apps.document_workflow.tests.base import invariant_violations

        out = seed_print_weekly_d12("2026-10-21")
        self.assertTrue(out["created"])
        self.assertEqual(invariant_violations(), [])
        data = printing.print_by_query({"kind": "weekly", "type": "D12", "date": out["week_start"]})
        days = data["days"]
        self.assertEqual([d["weekday"] for d in days], list("월화수목금"))  # 토(작성 안 함) 칸 없음
        self.assertEqual([d["state"] for d in days], ["ok", "ok", "ok", "ok", "draft"])
        self.assertEqual(
            [d.get("process_name") for d in days[:4]], ["내포장", "외포장", "내포장", "농축"]
        )
        self.assertEqual([b["staff_id"] for b in days[1]["approval"]], [2, 1])
        self.assertEqual([b["staff_id"] for b in days[3]["approval"]], [3, None])
        self.assertEqual(days[2]["values"]["worker_hair"], "O")  # 정정 중 → 승인본
        self.assertEqual(len(data["deviations"]), 1)
        self.assertFalse(seed_print_weekly_d12("2026-10-21")["created"])

    def test_monthly_seed(self):
        """D11 월 시드(지난달 9월 — 월요일 4개): 승인·부적합·정정 중·작성 안 함."""
        from apps.devtools.seed_print import seed_print_monthly
        from apps.document_workflow import printing
        from apps.document_workflow.tests.base import invariant_violations

        out = seed_print_monthly("2026-10-15")
        self.assertTrue(out["created"])
        self.assertEqual(out["month"], "2026-09")
        self.assertEqual(invariant_violations(), [])
        data = printing.print_by_query({"kind": "monthly", "type": "D11", "month": "2026-09"})
        self.assertEqual([w["state"] for w in data["weeks"]], ["ok", "ok", "ok", "skipped"])
        self.assertEqual(data["weeks"][2]["values"]["food_trace"], "O")  # 정정 중 → 승인본
        self.assertEqual(data["weeks"][1]["values"]["fly_trap_lamp"], "X")
        self.assertEqual([r["week_no"] for r in data["remarks"]], [1, 2])
        self.assertEqual([b["staff_id"] for b in data["boxes"]], [3, 5])  # 3주 승인이 가장 최근
        self.assertFalse(seed_print_monthly("2026-10-15")["created"])


class SeedProdLogTests(TestCase):
    """P15 S5a: 개발 생산일지 시드 — 수불 공개 서비스로 배치·투입·산출, 생산 시작 때 생산일지."""

    def test_scenarios(self):
        from apps.devtools import prodlog_dev
        from apps.production_log import logbook
        from apps.staff import services as staff_services

        staff_services.ensure_dev_staff(range(1, 6))
        used = prodlog_dev.make("used", 1)
        self.assertEqual(
            [d["type_code"] for d in used["documents"]], ["PROD-LOG", "CCP-1P", "CCP-2B", "CCP-3P"]
        )
        linked = logbook.linked_data(used["prod_log_id"])["linked"]
        first = linked["materials"][0]
        self.assertEqual((first["used_e6"], first["origin"]), (9_000000, "뉴질랜드 → 러시아(대체)"))
        self.assertEqual(linked["batch"]["output"], "98 kg")
        cancelled = prodlog_dev.make("cancelled", 1)
        self.assertEqual(
            logbook.linked_data(cancelled["prod_log_id"])["linked"]["batch"]["status"], "CANCELLED"
        )


@override_settings(ROOT_URLCONF="apps.devtools.test_urls")
class ProdLogFixtureTests(TestCase):
    """P15 S5b: 생산일지 프리셋 사전 조건·연동 오류 스위치·기준정보 스냅샷·콘솔 흐름."""

    def setUp(self):
        from apps.staff import services as staff_services

        staff_services.ensure_dev_staff(range(1, 6))

    def post(self, path, body):
        return self.client.post(path, data=json.dumps(body), content_type="application/json")

    def test_fixture_fill_complete_changed(self):
        r = self.post(
            "/api/dev/fixtures/prodlog",
            {
                "scenario": "partial",
                "template": "효력환",
                "fill": True,
                "complete": True,
                "output_after_kg": 40,
            },
        )
        self.assertEqual(r.status_code, 201, r.content)
        log = r.json()["prod_log_id"]
        linked = self.client.get(f"/api/v1/production-logs/{log}/linked").json()
        self.assertEqual((linked["status"], linked["changed"]), ("completed", True))
        self.assertEqual(
            len(self.client.get(f"/api/v1/documents/{log}").json()["sections"]) > 7, True
        )

    def test_link_fail_switch(self):
        from apps.devtools import fixtures_p15

        made = self.post("/api/dev/fixtures/prodlog", {"scenario": "used"}).json()
        other = self.post("/api/dev/fixtures/prodlog", {"scenario": "started"}).json()
        log = made["prod_log_id"]

        def linked_of(doc_id):
            return self.client.get(f"/api/v1/production-logs/{doc_id}/linked").json()

        self.assertEqual(self.post("/api/dev/prodlog/link-fail", {"on": True}).status_code, 400)
        try:
            on = self.post(
                "/api/dev/prodlog/link-fail", {"on": True, "batch_id": made["batch_id"]}
            ).json()
            self.assertEqual((on["on"], on["batch_id"]), (True, made["batch_id"]))
            self.assertGreater(on["seconds_left"], 0)
            linked = linked_of(log)
            self.assertEqual((linked["linked"], linked["error"]), (None, "SOURCE_UNAVAILABLE"))
            # r1 A3: 다른 배치는 정상 연동
            self.assertIsNotNone(linked_of(other["prod_log_id"])["linked"])
            # TTL이 지나면 스스로 꺼짐
            fixtures_p15.set_link_fail(True, made["batch_id"], ttl=0)
            self.assertIsNotNone(linked_of(log)["linked"])
            self.assertEqual(self.client.get("/api/dev/prodlog/link-fail").json(), {"on": False})
        finally:
            fixtures_p15.set_link_fail(False)
        self.assertEqual(self.client.get("/api/dev/prodlog/link-fail").json(), {"on": False})
        self.assertIsNotNone(linked_of(log)["linked"])

    def test_nobom_drop_ccp_and_master_snapshot(self):
        r = self.post("/api/dev/fixtures/prodlog", {"scenario": "nobom", "drop_ccp": "CCP-2B"})
        self.assertEqual(r.status_code, 201, r.content)
        linked = self.client.get(f"/api/v1/production-logs/{r.json()['prod_log_id']}/linked").json()
        self.assertEqual(linked["linked"]["materials"], [])
        self.assertIsNone(linked["linked"]["batch"]["food_type"])
        self.assertNotIn("CCP-2B", linked["ccp_documents"])
        from apps.production_log.models import Process

        pid = Process.objects.get(kind="OUTER").pk
        snap = self.client.get(f"/api/dev/snapshot?process_id={pid}").json()
        self.assertTrue(snap["exists"])
        self.assertEqual(
            set(snap["tables"]), {"process", "process_template_step", "master_change_log"}
        )
        flows = self.client.get("/api/dev/flows").json()
        self.assertIn("PLG-SAV", flows["flows"])
        self.assertEqual(flows["optional"]["PLG-LNK"], ["PLG-LNK-02", "DOC-BRF-01"])
        # 다른 단위 흐름엔 없음
        self.assertTrue(all(k.startswith("PLG-") for k in flows["optional"]))
        self.assertNotIn("DOC-BRF", flows["optional"])

    def test_console_flows_match_service_traces(self):
        """콘솔 흐름(CONSOLE)에서 API 단계를 뺀 것 = 서비스 trace(ROLE-CFG·테스트 준비 조회 뺌)."""
        from apps.core import trace
        from apps.production_log import flows

        made = self.post(
            "/api/dev/fixtures/prodlog", {"scenario": "used", "template": "효력환"}
        ).json()
        log = made["prod_log_id"]
        api_steps = {"DOC-UPD-01", "DOC-UPD-02", "DOC-CMP-01", "DOC-ROP-01"}

        def run(flow, method, path, body=None):
            state, token = trace.start()
            try:
                if method == "get":
                    self.client.get(path)
                else:
                    getattr(self.client, method)(
                        path,
                        data=json.dumps(body or {}),
                        content_type="application/json",
                        HTTP_X_STAFF_ID="1",
                    )
            finally:
                trace.stop(token)
            # ROLE-CFG(설정 읽기)·EFF-(신호 안쪽 — 콘솔이 안쪽 단계로 따로 셈)는 비교 밖
            got = [s.step_id for s in state.steps if not s.step_id.startswith(("ROLE-CFG", "EFF-"))]
            want = [
                s
                for s in flows.CONSOLE[flow]
                if not s.endswith(("-00", "-00b")) and s not in api_steps
            ]
            got = [s for s in got if not s.endswith(("-00", "-00b")) and s not in api_steps]
            want = [s for s in want if s in got or s not in flows.OPTIONAL.get(flow, ())]  # 조건부
            self.assertEqual(got, want, flow)

        made = self.post(
            "/api/dev/fixtures/prodlog", {"scenario": "used", "template": "효력환", "fill": True}
        ).json()
        log = made["prod_log_id"]
        from apps.production_log.models import ProcessTemplate

        tid = ProcessTemplate.objects.get(name="효력환").pk
        run(
            "PLG-TPL",
            "post",
            f"/api/v1/production-logs/{log}/template-rows",
            {"template_id": tid, "mode": "append"},
        )
        steps = [
            s["values"]
            for s in self.client.get(f"/api/v1/documents/{log}").json()["sections"]
            if s["section_def"] == "steps"
        ]
        run(
            "PLG-TSV",
            "post",
            f"/api/v1/production-logs/{log}/save-template",
            {"name": "콘솔 흐름", "steps": steps},
        )
        run(
            "PLG-REG",
            "post",
            f"/api/v1/production-logs/{log}/register-process",
            {"name": "콘솔 공정", "mode": "QTY"},
        )
        version = self.client.get(f"/api/v1/documents/{log}").json()["version"]
        run("PLG-CMP", "post", f"/api/v1/documents/{log}/complete", {"expected_version": version})
        version = self.client.get(f"/api/v1/documents/{log}").json()["version"]
        run("PLG-ROP", "post", f"/api/v1/documents/{log}/reopen", {"expected_version": version})
        run("PLG-LNK", "get", f"/api/v1/production-logs/{log}/linked")
        run("PLG-CCP", "get", f"/api/v1/production-logs/{log}/ccp-values?kind=CCP-1P")
        version = self.client.get(f"/api/v1/documents/{log}").json()["version"]
        d = self.client.get(f"/api/v1/documents/{log}").json()
        info = next(s for s in d["sections"] if s["section_def"] == "info")
        run(
            "PLG-SAV",
            "patch",
            f"/api/v1/documents/{log}",
            {
                "expected_version": version,
                "sections": {
                    "update": [{"section_id": info["section_id"], "values": {"pre_lot": "적합"}}]
                },
            },
        )
