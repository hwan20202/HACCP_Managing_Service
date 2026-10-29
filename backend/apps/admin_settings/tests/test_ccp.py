"""P16 묶음 ① 품목별 CCP·배치 적용 기록·이력 (p16-s2-spec 9장 TC-01~05·16·20, R71)."""

import json
import types

from django.db import IntegrityError, connection, transaction
from django.test import Client, TestCase
from django.utils import timezone

from apps.admin_settings import services, store
from apps.admin_settings.errors import ItemNotFound, ValidationFailed, VersionConflict
from apps.admin_settings.models import AdminChangeLog, BatchCcpApplied, ItemCcp
from apps.admin_settings.testing import ensure_ccp_defaults
from apps.doc_requirements import services as req
from apps.documents.models import Document
from apps.documents.seed import ensure_p4_templates, ensure_staff
from apps.documents.tests.p4 import stub

NOW = "2026-10-29 09:00:00"


def setup_items():
    ensure_staff(3)
    ensure_ccp_defaults()
    stub("items", id=201, name="유자환", item_type="SEMI", item_code="3201")
    stub("items", id=202, name="녹용환", item_type="SEMI", item_code="3202")
    stub("items", id=203, name="사용중지환", item_type="SEMI", item_code="3203", is_active=0)
    stub("items", id=204, name="원료", item_type="RAW", item_code="1204")


def batch(batch_id, item_id, status="IN_PROGRESS", started=True):
    stub(
        "production_batches",
        id=batch_id,
        batch_number=f"PB-{batch_id}",
        process_type="MANUFACTURE",
        item_id=item_id,
        status=status,
        started_at=NOW if started else None,
    )


def save(item_id, mode, processes=(), version=0, reason=None, actor=1):
    body = {"mode": mode, "processes": list(processes), "expected_version": version}
    if reason is not None:
        body["reason"] = reason
    return services.save_item_ccp(actor, item_id, body)


def codes(error):
    return [d["code"] for d in error.exception.details]


class SaveItemCcpTests(TestCase):
    """ADM-TC-01·02: 저장·기본 따름(행 유지)·CCP 없음·순서·검사·버전."""

    def setUp(self):
        setup_items()

    def test_tc01_save_default_keep_row(self):
        out = save(201, "own", ["3P", "1P"], reason="  품질팀 요청 ")
        self.assertTrue(out["changed"])
        self.assertEqual((out["item"]["processes"], out["item"]["version"]), (["1P", "3P"], 1))
        out = save(201, "default", version=1)
        self.assertEqual((out["item"]["mode"], out["item"]["version"]), ("default", 2))
        self.assertEqual(out["item"]["effective"], ["1P", "2B", "3P"])
        row = ItemCcp.objects.get(item_id=201)  # 되돌려도 행 유지(R01 — ABA 막음)
        self.assertEqual((row.mode, row.processes, row.version), ("default", [], 2))
        logs = list(AdminChangeLog.objects.order_by("pk").values_list("action", "reason"))
        self.assertEqual(logs, [("set", "품질팀 요청"), ("default", None)])
        out = save(202, "own", [])  # CCP 없음
        self.assertEqual((out["item"]["processes"], out["item"]["effective"]), ([], []))

    def test_tc01_checks(self):
        cases = [
            ({"mode": "own", "processes": ["1P", "1P"]}, "invalid_process"),
            ({"mode": "own", "processes": ["4P"]}, "invalid_process"),
            ({"mode": "own", "processes": "1P"}, "invalid_process"),
            ({"mode": "default", "processes": ["1P"]}, "invalid_process"),
            ({"mode": "x", "processes": []}, "invalid"),
            ({"mode": "own", "processes": [], "reason": "가" * 101}, "too_long"),
            ({"mode": "own", "processes": [], "extra": 1}, "unknown_key"),
            ({"mode": "own", "processes": []}, "required"),  # expected_version 없음
        ]
        for body, code in cases:
            if code != "required":
                body = {**body, "expected_version": 0}
            with self.subTest(body=body), self.assertRaises(ValidationFailed) as e:
                services.save_item_ccp(1, 201, body)
            self.assertIn(code, codes(e))
        with self.assertRaises(ValidationFailed) as e:
            save(204, "own", ["1P"])
        self.assertEqual(codes(e), ["not_producible"])
        with self.assertRaises(ItemNotFound):
            save(999, "own", ["1P"])
        self.assertFalse(ItemCcp.objects.exists() or AdminChangeLog.objects.exists())

    def test_tc02_version_aba_same(self):
        save(201, "own", ["1P"])
        with self.assertRaises(VersionConflict):
            save(201, "own", ["2B"], version=0)
        save(201, "default", version=1)
        save(201, "own", ["1P"], version=2)
        with self.assertRaises(VersionConflict):  # 기본 → 설정 → 기본 뒤 옛 버전(ABA)
            save(201, "own", ["3P"], version=1)
        out = save(201, "own", ["1P"], version=3)  # 같은 값: 저장·이력 없음
        self.assertEqual((out["changed"], out["item"]["version"]), (False, 3))
        self.assertEqual(AdminChangeLog.objects.count(), 3)
        out = save(203, "default")  # 행 없음 + 기본 따름 = 같은 값
        self.assertFalse(out["changed"])
        self.assertFalse(ItemCcp.objects.filter(item_id=203).exists())


class ListItemCcpTests(TestCase):
    """A01: 반제품만, 사용 중지·검색·설정한 것만, 배치 수, 적용 공정."""

    def setUp(self):
        setup_items()
        save(202, "own", ["2B"])
        batch(301, 201, status="PLANNED", started=False)
        batch(302, 201, status="PLANNED", started=False)
        batch(303, 201)

    def test_list(self):
        out = services.list_item_ccp()
        self.assertEqual(out["default"], {"MANUFACTURE": ["1P", "2B", "3P"], "PACKAGING": []})
        rows = {r["item_id"]: r for r in out["items"]}
        self.assertEqual(sorted(rows), [201, 202])
        self.assertEqual((rows[201]["planned_batches"], rows[201]["running_batches"]), (2, 1))
        self.assertEqual((rows[201]["mode"], rows[201]["version"]), ("default", 0))
        self.assertEqual(rows[202]["effective"], ["2B"])
        ids = [r["item_id"] for r in services.list_item_ccp(include_inactive=True)["items"]]
        self.assertEqual(ids, [201, 202, 203])
        self.assertEqual([r["item_id"] for r in services.list_item_ccp(q="녹용")["items"]], [202])
        self.assertEqual(
            [r["item_id"] for r in services.list_item_ccp(only_own=True)["items"]], [202]
        )

    def test_tc16_sql_count(self):
        with self.assertNumQueries(4):
            services.list_item_ccp()


class BatchCcpTests(TestCase):
    """ADM-TC-03·04·20: 생산 시작 = 적용 기록, [다시 호출] = 기록대로, 이전 배치 이관."""

    def setUp(self):
        setup_items()
        ensure_p4_templates()

    def call(self, batch_id):
        return [d["type_code"] for d in req.require_for_batch(1, batch_id)["documents"]]

    def test_tc03_start(self):
        save(202, "own", ["1P"])
        save(203, "own", [])
        for b, item in ((401, 201), (402, 202), (403, 203)):
            batch(b, item)
        self.assertEqual(self.call(401), ["CCP-1P", "CCP-2B", "CCP-3P"])
        self.assertEqual(self.call(402), ["CCP-1P"])
        self.assertEqual(self.call(403), [])
        self.assertEqual(
            store.batch_ccp([401, 402, 403, 404]),
            {401: ["1P", "2B", "3P"], 402: ["1P"], 403: [], 404: None},
        )

    def test_tc04_recall_keeps_record(self):
        batch(401, 201)
        self.call(401)
        save(201, "own", ["2B"])  # 설정을 바꿔도
        self.assertEqual(self.call(401), ["CCP-1P", "CCP-2B", "CCP-3P"])  # 기록대로, 새 공정 없음
        self.assertEqual(Document.objects.count(), 3)
        self.assertEqual(BatchCcpApplied.objects.get(batch_id=401).processes, ["1P", "2B", "3P"])

    def test_tc20_migration_backfill(self):
        from importlib import import_module

        from django.apps import apps

        forward = import_module("apps.admin_settings.migrations.0002_ccp_data").forward
        batch(501, 201)  # P16 이전에 시작한 제조 배치(기록 없음)
        batch(502, 201, status="PLANNED", started=False)
        forward(apps, types.SimpleNamespace(connection=connection))
        self.assertEqual(store.batch_ccp([501, 502]), {501: ["1P", "2B", "3P"], 502: None})
        decided = BatchCcpApplied.objects.get(batch_id=501).decided_at
        self.assertLess(abs((timezone.now() - decided).total_seconds()), 60)  # 실행 시각(D-267)
        save(201, "own", ["3P"])
        self.assertEqual(self.call(501), ["CCP-1P", "CCP-2B", "CCP-3P"])
        self.assertEqual(self.call(502), ["CCP-3P"])  # 시작 전 배치는 처음 시작 때 설정대로
        forward(apps, types.SimpleNamespace(connection=connection))  # 다시 돌려도 그대로
        self.assertEqual(BatchCcpApplied.objects.count(), 2)

    def test_tc16_sql_count(self):
        batch(401, 201)
        with self.assertNumQueries(5):  # 기록 읽기 + 결정 1 + 저장점·넣기·해제
            store.ccp_for_batch(401, 201, "MANUFACTURE")
        with self.assertNumQueries(1):
            store.ccp_for_batch(401, 201, "MANUFACTURE")
        with self.assertNumQueries(0):
            store.batch_ccp([])

    def test_bool_check(self):
        batch(401, 201)
        store.ccp_for_batch(401, 201, "MANUFACTURE")
        with self.assertRaises(IntegrityError), transaction.atomic():
            with connection.cursor() as c:
                c.execute("UPDATE batch_ccp_applied SET ccp_1p = 2 WHERE batch_id = 401")


class ItemRemovalTests(TestCase):
    """D-263 Q1 a: 수불 미사용 품목 삭제(직접 SQL) → 품목 CCP 설정도 DB가 지움."""

    def setUp(self):
        setup_items()

    def test_cascade(self):
        from apps.inventory.item_removal import remove_items

        save(202, "own", ["1P"])
        with transaction.atomic():
            remove_items(
                {
                    "staff_id": 1,
                    "item_ids": [202],
                    "dry_run": False,
                    "confirmation": "DELETE_UNUSED_ITEMS",
                }
            )
        self.assertFalse(ItemCcp.objects.filter(item_id=202).exists())
        self.assertEqual(AdminChangeLog.objects.count(), 1)  # 이력은 남음(대상 FK 없음)
        out = services.history("item_ccp", 202)
        self.assertEqual(out["items"][0]["label"], None)  # 지워진 품목


class HistoryTests(TestCase):
    def setUp(self):
        setup_items()

    def test_history(self):
        save(201, "own", ["1P"], actor=2)
        save(202, "own", ["2B"])
        save(201, "default", version=1, reason="되돌림")
        out = services.history("item_ccp", 201)
        self.assertEqual([i["action"] for i in out["items"]], ["default", "set"])
        first = out["items"][1]
        self.assertEqual(first["actor"], {"id": 2, "name": "개발직원2"})
        self.assertEqual(
            (first["label"], first["before"]),
            ("유자환(3201)", {"mode": "default", "processes": []}),
        )
        self.assertEqual(len(services.history("item_ccp")["items"]), 3)
        self.assertTrue(first["at"].endswith("+09:00"))  # 검토 B5: 한국 시각(문서·결재 API와 같음)
        for args in (("staff",), ("item_ccp", -1), ("item_ccp", None, 0)):
            with self.subTest(args=args), self.assertRaises(ValidationFailed):
                services.history(*args)


class ApiTests(TestCase):
    """A01·A02·A11 HTTP, R27 헤더, R71 CSRF(검사 유지, home이 쿠키 발급)."""

    def setUp(self):
        setup_items()

    def put(self, client, item_id, body, **headers):
        return client.put(
            f"/api/v1/admin/item-ccp/{item_id}",
            json.dumps(body),
            content_type="application/json",
            **headers,
        )

    def test_read_write(self):
        c = Client()
        r = c.get("/api/v1/admin/item-ccp?include_inactive=1")
        self.assertEqual((r.status_code, len(r.json()["items"])), (200, 3))
        self.assertEqual(c.get("/api/v1/admin/item-ccp?only_own=2").status_code, 400)
        body = {"mode": "own", "processes": ["2B"], "expected_version": 0}
        r = self.put(c, 201, body)
        self.assertEqual((r.status_code, r.json()["code"]), (400, "STAFF_HEADER_MISSING"))
        r = self.put(c, 201, body, HTTP_X_STAFF_ID="1")
        self.assertEqual((r.status_code, r.json()["item"]["version"]), (200, 1))
        r = self.put(c, 201, body, HTTP_X_STAFF_ID="1")
        self.assertEqual((r.status_code, r.json()["code"]), (409, "VERSION_CONFLICT"))
        r = self.put(c, 999, body, HTTP_X_STAFF_ID="1")
        self.assertEqual(r.status_code, 404)
        r = c.get("/api/v1/admin/history?target=item_ccp&target_id=201")
        self.assertEqual([i["action"] for i in r.json()["items"]], ["set"])
        self.assertEqual(c.get("/api/v1/admin/history?target=x").status_code, 400)

    def test_csrf(self):
        c = Client(enforce_csrf_checks=True)
        body = {"mode": "own", "processes": ["1P"], "expected_version": 0}
        self.assertEqual(self.put(c, 201, body, HTTP_X_STAFF_ID="1").status_code, 403)
        c.get("/")  # 첫 화면이 쿠키 발급(R71)
        token = c.cookies["csrftoken"].value
        r = self.put(c, 201, body, HTTP_X_STAFF_ID="1", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(r.status_code, 200)


class FlowTraceTests(TestCase):
    """개발 콘솔 흐름(flows.py)과 서비스 trace 단계가 같은지(S4 검토 C2 — S5에서 등록)."""

    def setUp(self):
        setup_items()

    def test_flows(self):
        from apps.admin_settings import flows
        from apps.core import trace

        cases = []
        state, token = trace.start()
        try:
            services.list_item_ccp()
            cases.append(("ADM-CCP-LST", list(state.steps)))
            state.steps.clear()
            save(201, "own", ["1P"])
            cases.append(("ADM-CCP-SAV", list(state.steps)))
            state.steps.clear()
            services.history("item_ccp")
            cases.append(("ADM-HIS", list(state.steps)))
        finally:
            trace.stop(token)
        for flow, steps in cases:
            ids = [s.step_id for s in steps]
            self.assertTrue(flows.matches(flow, ids), (flow, ids))
