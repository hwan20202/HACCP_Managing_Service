"""PLG-TC-01~08 (p15-s2-spec.md 7장) — 공정·템플릿·이력 서비스."""

from unittest import mock

from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.core import trace
from apps.production_log import flows, services
from apps.production_log.models import MasterChangeLog, Process, ProcessTemplate

from .base import PlgTestCase, builtin, make_prod_log_row, run


class ProcessTests(PlgTestCase):
    def test_migration_builtins(self):
        rows = list(Process.objects.filter(is_builtin=True).values_list("kind", "created_by_id"))
        self.assertEqual(sorted(rows), sorted((k, None) for k in services.BUILTIN_ORDER))

    def test_tc01_create_duplicate_similar(self):
        p = self.new_process("  분쇄  공정 ", std_duration={"value": 1, "unit": "시간"})
        self.assertEqual(
            (p["name"], p["kind"], p["mode"], p["version"]), ("분쇄 공정", "GEN", "JUDGE", 1)
        )
        self.assertEqual(p["std_duration"], {"value": 1, "unit": "시간"})
        error = self.assertRaisesCode("PLG_NAME_TAKEN", self.new_process, "분쇄 공정")
        self.assertEqual(error.details[0]["id"], p["process_id"])
        self.assertRaisesCode("PLG_NAME_TAKEN", self.new_process, "분쇄   공정")  # 공백 정리
        self.new_process("Mixing")
        self.assertRaisesCode("PLG_NAME_TAKEN", self.new_process, "mixing")  # 대소문자 무시
        self.new_process("건조 (SD건조기)")
        error = self.assertRaisesCode("PLG_SIMILAR_NAME", self.new_process, "건조(SD 건조기)")
        self.assertEqual(error.details[0]["name"], "건조 (SD건조기)")
        self.new_process("건조(SD 건조기)", confirm_similar=True)  # [그래도 저장]
        for bad in (
            {"mode": "JUDGE"},
            {"name": " ", "mode": "JUDGE"},
            {"name": "가" * 41, "mode": "JUDGE"},
            {"name": "x", "mode": "BAD"},
            {"name": "y", "mode": "QTY", "kind": "CCP-1P"},
            {"name": "z", "mode": "QTY", "std_duration": {"value": 0, "unit": "일"}},
            {"name": "w", "mode": "QTY", "std_duration": {"value": 2}},
        ):
            self.assertRaisesCode("VALIDATION_ERROR", services.create_process, 1, bad)

    def test_tc02_builtin_locked(self):
        dry = builtin("CCP-2B")
        out = run(
            services.update_process,
            1,
            dry.pk,
            {
                "name": "건조 공정",
                "description": "70℃",
                "std_duration": {"value": 2, "unit": "시간"},
            },
            1,
        )
        self.assertEqual((out["name"], out["description"], out["version"]), ("건조 공정", "70℃", 2))
        self.assertRaisesCode(
            "PLG_BUILTIN_LOCKED", services.update_process, 1, dry.pk, {"mode": "JUDGE"}, 2
        )
        self.assertRaisesCode(
            "PLG_BUILTIN_LOCKED", services.set_process_active, 1, dry.pk, False, 2
        )
        self.assertRaisesCode("PLG_BUILTIN_LOCKED", services.delete_process, 1, dry.pk, 2)
        self.assertRaisesCode(
            "VALIDATION_ERROR", services.update_process, 1, dry.pk, {"kind": "GEN"}, 2
        )

    def test_tc03_deactivate_delete_in_use(self):
        a = self.new_process("분쇄")
        b = self.new_process("배양")
        c = self.new_process("접종")
        self.new_template("효력환", [a["process_id"]])
        self.assertRaisesCode(
            "PLG_IN_USE", services.delete_process, 1, a["process_id"], 1
        )  # 템플릿
        make_prod_log_row(b["process_id"])
        self.assertRaisesCode(
            "PLG_IN_USE", services.delete_process, 1, b["process_id"], 1
        )  # 생산일지
        run(services.delete_process, 1, c["process_id"], 1)
        self.assertFalse(Process.objects.filter(pk=c["process_id"]).exists())
        off = run(services.set_process_active, 1, a["process_id"], False, 1)
        self.assertFalse(off["is_active"])
        self.new_process("분쇄")  # 중지된 공정과 같은 이름 OK
        self.assertRaisesCode(
            "PLG_NAME_TAKEN", services.set_process_active, 1, a["process_id"], True, 2
        )
        self.assertEqual(
            services.list_processes(status="inactive")["items"][0]["process_id"], a["process_id"]
        )

    def test_tc04_update_impact_and_mode_confirm(self):
        a = self.new_process("추출", "TEMP_TIME")
        self.new_template("녹용", [a["process_id"]])
        self.new_template("녹용2", [a["process_id"]])
        error = self.assertRaisesCode(
            "PLG_CONFIRM_REQUIRED",
            services.update_process,
            1,
            a["process_id"],
            {"mode": "JUDGE"},
            1,
        )
        self.assertEqual(error.details[0]["template_count"], 2)
        out = run(
            services.update_process, 1, a["process_id"], {"mode": "JUDGE", "confirm_mode": True}, 1
        )
        self.assertEqual((out["mode"], out["template_count"]), ("JUDGE", 2))
        self.assertRaisesCode(
            "VERSION_CONFLICT", services.update_process, 1, a["process_id"], {"description": "x"}, 1
        )
        self.assertRaisesCode(
            "VALIDATION_ERROR", services.update_process, 1, a["process_id"], {}, 2
        )
        listed = {p["process_id"]: p for p in services.list_processes(kind="general")["items"]}
        self.assertEqual(listed[a["process_id"]]["template_count"], 2)

    def test_tc05_history(self):
        a = self.new_process("분쇄", actor=2)
        run(services.update_process, 3, a["process_id"], {"description": "곱게"}, 1)
        run(services.set_process_active, 3, a["process_id"], False, 2)
        run(services.delete_process, 2, a["process_id"], 3)
        items = services.history("process", a["process_id"])["items"]
        self.assertEqual([i["action"] for i in items], ["delete", "deactivate", "update", "create"])
        update = items[2]
        self.assertEqual(
            (update["before"]["description"], update["after"]["description"]), (None, "곱게")
        )
        self.assertEqual(update["actor"], {"id": 3, "name": "개발직원3"})
        self.assertIsNone(items[0]["after"])
        self.assertIsNone(items[3]["before"])
        self.assertRaisesCode("VALIDATION_ERROR", services.history, "item", 1)

    def test_list_filters_and_order(self):
        self.new_process("분쇄")
        self.new_process("배양")
        kinds = [p["kind"] for p in services.list_processes()["items"]]
        self.assertEqual(kinds[:5], services.BUILTIN_ORDER)  # 기본 제공 먼저
        self.assertEqual(
            [p["name"] for p in services.list_processes(kind="general")["items"]], ["배양", "분쇄"]
        )
        self.assertEqual(len(services.list_processes(query="분")["items"]), 1)
        self.assertRaisesCode("VALIDATION_ERROR", services.list_processes, "", "x")


class TemplateTests(PlgTestCase):
    def test_tc06_create_update_validation(self):
        a = self.new_process("분쇄")
        inner = builtin("INNER")
        t = run(
            services.create_template,
            1,
            {
                "name": "효력환",
                "steps": [
                    {
                        "process_id": a["process_id"],
                        "overrides": {"name": "곱게 분쇄", "duration": None},
                    },
                    {"process_id": inner.pk, "overrides": {"spec": "1환 3.75 g", "qty_unit": "환"}},
                ],
            },
        )
        self.assertEqual([s["seq"] for s in t["steps"]], [1, 2])
        self.assertEqual(t["steps"][0]["resolved"]["name"], "곱게 분쇄")
        self.assertIsNone(t["steps"][0]["resolved"]["duration"])
        self.assertEqual(t["steps"][1]["resolved"]["spec"], "1환 3.75 g")
        bad_steps = [
            [],
            [{"process_id": a["process_id"]}, {"process_id": a["process_id"]}],  # 같은 공정 두 번
            [{"process_id": 9999}],
            [{"process_id": inner.pk, "overrides": {"mode": "QTY"}}],  # 기본 제공에 입력 방식
            [{"process_id": a["process_id"], "overrides": {"material": "PE"}}],  # 외포장 값
            [{"process_id": a["process_id"], "extra": 1}],
            [{"process_id": a["process_id"]}] * 31,
        ]
        for steps in bad_steps:
            self.assertRaisesCode(
                "PLG_TEMPLATE_INVALID",
                services.create_template,
                1,
                {"name": "새 템플릿", "steps": steps},
            )
        self.assertRaisesCode(
            "PLG_NAME_TAKEN",
            services.create_template,
            1,
            {"name": "효력환 ", "steps": [{"process_id": a["process_id"]}]},
        )
        # 중지된 공정: 새로 넣을 수 없음, 이미 있던 것은 둘 수 있음
        b = self.new_process("배양")
        t2 = self.new_template("EXO", [b["process_id"]])
        run(services.set_process_active, 1, b["process_id"], False, 1)
        self.assertRaisesCode(
            "PLG_TEMPLATE_INVALID",
            services.update_template,
            1,
            t["process_template_id"],
            {"steps": [{"process_id": b["process_id"]}]},
            1,
        )
        out = run(
            services.update_template,
            1,
            t2["process_template_id"],
            {
                "name": "EXO 발효",
                "steps": [{"process_id": b["process_id"]}, {"process_id": inner.pk}],
            },
            1,
        )
        self.assertEqual((out["name"], out["step_count"], out["version"]), ("EXO 발효", 2, 2))
        self.assertFalse(out["steps"][0]["process_is_active"])
        self.assertRaisesCode(
            "VERSION_CONFLICT",
            services.update_template,
            1,
            t2["process_template_id"],
            {"name": "x"},
            1,
        )

    def test_tc07_copy(self):
        t = self.new_template("효력환")
        c1 = run(services.copy_template, 2, t["process_template_id"])
        c2 = run(services.copy_template, 2, t["process_template_id"])
        self.assertEqual((c1["name"], c2["name"]), ("효력환 (복사)", "효력환 (복사 2)"))
        self.assertEqual(
            [s["process_id"] for s in c1["steps"]], [s["process_id"] for s in t["steps"]]
        )
        long = self.new_template("가" * 40, [builtin("OUTER").pk])
        self.assertEqual(
            len(run(services.copy_template, 1, long["process_template_id"])["name"]), 40
        )
        log = services.history("template", c1["process_template_id"])["items"][0]
        self.assertEqual(
            (log["action"], log["before"]), ("copy", {"from": t["process_template_id"]})
        )

    def test_tc08_deactivate_delete(self):
        t = self.new_template("효력환")
        tid = t["process_template_id"]
        ProcessTemplate.objects.filter(pk=tid).update(
            used_count=1, last_used_at="2026-10-26T09:00:00+09:00"
        )
        self.assertRaisesCode("PLG_IN_USE", services.delete_template, 1, tid, 1)
        off = run(services.set_template_active, 1, tid, False, 1)
        self.assertFalse(off["is_active"])
        self.assertEqual(services.list_templates()["items"], [])
        self.assertEqual(len(services.list_templates(status="inactive")["items"]), 1)
        fresh = self.new_template("녹용", [builtin("CCP-3P").pk])
        run(services.delete_template, 1, fresh["process_template_id"], 1)
        self.assertFalse(ProcessTemplate.objects.filter(pk=fresh["process_template_id"]).exists())
        actions = [
            i["action"] for i in services.history("template", fresh["process_template_id"])["items"]
        ]
        self.assertEqual(actions, ["delete", "create"])

    def test_list_summary(self):
        self.new_template(
            "효력환", [builtin("CCP-1P").pk, builtin("INNER").pk, builtin("CCP-3P").pk], actor=2
        )
        item = services.list_templates()["items"][0]
        self.assertEqual(item["step_count"], 3)
        self.assertEqual(item["ccp_kinds"], ["CCP-1P", "CCP-3P"])
        self.assertEqual(item["created_by"], {"id": 2, "name": "개발직원2"})


class ReviewFixTests(PlgTestCase):
    """S4a 외부 검토 B1~B3·C2 회귀."""

    def test_b1_duration_finite_and_bounded(self):
        for value, unit in (
            (float("inf"), "일"),
            (float("nan"), "일"),
            (1001, "일"),
            (100001, "분"),
        ):
            self.assertRaisesCode(
                "VALIDATION_ERROR",
                services.create_process,
                1,
                {"name": "x", "mode": "JUDGE", "std_duration": {"value": value, "unit": unit}},
            )
        a = self.new_process("분쇄", std_duration={"value": 1000, "unit": "일"})  # 상한 포함
        self.assertRaisesCode(
            "PLG_TEMPLATE_INVALID",
            services.create_template,
            1,
            {
                "name": "t",
                "steps": [
                    {
                        "process_id": a["process_id"],
                        "overrides": {"duration": {"value": float("inf"), "unit": "분"}},
                    }
                ],
            },
        )

    def test_b2_copy_rejects_inactive_process(self):
        a = self.new_process("분쇄")
        t = self.new_template("효력환", [a["process_id"], builtin("OUTER").pk])
        run(services.set_process_active, 1, a["process_id"], False, 1)
        error = self.assertRaisesCode(
            "PLG_TEMPLATE_INVALID", services.copy_template, 1, t["process_template_id"]
        )
        self.assertEqual(error.details[0]["code"], "inactive")
        self.assertEqual(ProcessTemplate.objects.count(), 1)

    def test_b3_no_change_no_version_no_log(self):
        a = self.new_process("분쇄")
        t = self.new_template("효력환", [a["process_id"]])
        same = run(
            services.update_template,
            1,
            t["process_template_id"],
            {"name": "효력환", "steps": [{"process_id": a["process_id"]}]},
            1,
        )
        self.assertEqual(same["version"], 1)
        out = run(services.update_process, 1, a["process_id"], {"name": "분쇄", "mode": "JUDGE"}, 1)
        self.assertEqual(out["version"], 1)
        self.assertEqual(MasterChangeLog.objects.exclude(action="create").count(), 0)
        changed = run(
            services.update_template, 1, t["process_template_id"], {"name": "효력환 2"}, 1
        )
        self.assertEqual(changed["version"], 2)

    def test_c2_matches_ignores_api_steps(self):
        self.assertTrue(flows.matches("PRC-ACT", ["PRC-ACT-00", "PRC-ACT-00b", "PRC-ACT-01"]))
        self.assertFalse(flows.matches("PRC-ACT", ["PRC-ACT-00"]))


class SeedFlowAndQueryTests(PlgTestCase):
    def test_seed_idempotent(self):
        from apps.production_log.seed import seed_production_master

        self.assertEqual(seed_production_master(1), {"processes": 9, "templates": 3, "builtins": 4})
        self.assertEqual(seed_production_master(1), {"processes": 0, "templates": 0, "builtins": 0})
        names = [t["name"] for t in services.list_templates()["items"]]
        self.assertEqual(sorted(names), sorted(["효력환", "녹용농축분말", "EXO-Boost 발효녹용"]))
        exo = next(t for t in services.list_templates()["items"] if t["name"].startswith("EXO"))
        detail = services.get_template(exo["process_template_id"])
        self.assertEqual(detail["steps"][0]["resolved"]["name"], "살균 (건조)")
        self.assertEqual(detail["steps"][0]["kind"], "GEN")  # A4 b: 일반 공정
        self.assertEqual(detail["step_count"], 7)

    def test_tc28_query_counts(self):
        from apps.production_log.seed import seed_production_master

        seed_production_master(1)
        with CaptureQueriesContext(connection) as q:
            services.list_processes()
        self.assertLessEqual(len(q), 3)
        with CaptureQueriesContext(connection) as q:
            services.list_templates()
        self.assertLessEqual(len(q), 3)
        tid = services.list_templates()["items"][0]["process_template_id"]
        with CaptureQueriesContext(connection) as q:
            services.get_template(tid)
        self.assertLessEqual(len(q), 3)

    def test_flows_trace(self):
        cases = []
        state, token = trace.start()
        try:
            p = self.new_process("분쇄")
            cases.append(("PRC-NEW", list(state.steps)))
            state.steps.clear()
            run(services.update_process, 1, p["process_id"], {"description": "x"}, 1)
            cases.append(("PRC-UPD", list(state.steps)))
            state.steps.clear()
            t = self.new_template("효력환", [p["process_id"]])
            cases.append(("TPL-NEW", [s for s in state.steps if s.step_id.startswith("TPL-NEW")]))
            state.steps.clear()
            run(services.delete_template, 1, t["process_template_id"], 1)
            cases.append(("TPL-DEL", list(state.steps)))
            state.steps.clear()
            run(services.delete_process, 1, p["process_id"], 2)
            cases.append(("PRC-DEL", [s for s in state.steps if s.step_id.startswith("PRC")]))
        finally:
            trace.stop(token)
        for flow, steps in cases:
            self.assertTrue(
                flows.matches(flow, [s.step_id for s in steps]), (flow, [s.step_id for s in steps])
            )
        self.assertEqual(MasterChangeLog.objects.count(), 5)


class OutsideTransactionTests(PlgTestCase):
    """트랜잭션 밖 호출 거부. TestCase는 늘 트랜잭션 안이라 연결 상태 확인만 바꿔 본다.

    (TransactionTestCase는 끝나고 표를 비워 0002 기본 제공 5종이 사라지고,
    serialized_rollback은 전체 실행에서 content type 중복 오류가 난다.)
    """

    def test_transaction_required(self):
        p = self.new_process("분쇄")
        with mock.patch.object(services, "connection", mock.Mock(in_atomic_block=False)):
            with self.assertRaises(services.errors.TransactionRequired):
                services.create_process(1, {"name": "배양", "mode": "JUDGE"})
            with self.assertRaises(services.errors.TransactionRequired):
                services.delete_process(1, p["process_id"], 1)
        self.assertFalse(Process.objects.filter(name="배양").exists())
