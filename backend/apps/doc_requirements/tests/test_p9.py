"""P9 S4 주기형 작성 요구 REQ-F07~F09·A05~A07·CMD-01 (p9-s2-spec 7장 P9-TC-001~060).

날짜는 P8 준비물의 주(2026-10-12 월 ~ 10-16 금)를 쓰고, 오늘은 periodic._today를 바꿔 고정한다.
규칙 파일은 기본 파일(start_date 2026-10-12) 또는 임시 파일(override_settings).
"""

import datetime
import io
import json
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.core.management import CommandError, call_command
from django.db import transaction
from django.test import TestCase, override_settings

from apps.doc_requirements import errors, flows, periodic
from apps.doc_requirements import services as req
from apps.document_workflow.tests.base import invariant_violations
from apps.documents import errors as doc_errors
from apps.documents import services as doc
from apps.documents.models import Document, DocumentTemplate
from apps.documents.seed import ensure_templates
from apps.documents.tests.base import ccp_payload
from apps.documents.tests.p8 import (
    FRI,
    MON,
    THU,
    TUE,
    WED,
    captured,
    checks_row,
    fill,
    setup_p8,
)
from apps.staff.services import InvalidStaff

from .base import setup_req

SAT, SUN = "2026-10-17", "2026-10-18"
NEXT_MON, NEXT_TUE = "2026-10-19", "2026-10-20"
RULES = [
    {
        "type_code": "D10",
        "cadence": "daily",
        "weekdays": [1, 2, 3, 4, 5],
        "start_date": MON,
        "enabled": True,
    },
    {
        "type_code": "D12",
        "cadence": "daily",
        "weekdays": [1, 2, 3, 4, 5],
        "start_date": MON,
        "enabled": True,
    },
    {
        "type_code": "D11",
        "cadence": "weekly",
        "weekdays": [1, 2, 3, 4, 5],
        "start_date": MON,
        "enabled": True,
    },
]


def today(day):
    return mock.patch.object(periodic, "_today", return_value=datetime.date.fromisoformat(day))


def run(date_from, date_to=None, types=None, actor=3):
    return periodic.run_periodic(actor, date_from, date_to or date_from, types)


def results(out):
    return [(line["work_date"], line["type_code"], line["result"]) for line in out["lines"]]


class RulesFileMixin:
    """임시 규칙 파일. self.write_rules(...)로 바꾼다(호출마다 읽으므로 바로 반영)."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp(prefix="haccp-rules-")
        self.rules_path = Path(self.tmp) / "rules.json"
        self.write_rules(RULES)
        self._override = override_settings(HACCP_PERIODIC_RULES=str(self.rules_path))
        self._override.enable()

    def tearDown(self):
        self._override.disable()
        shutil.rmtree(self.tmp, ignore_errors=True)
        super().tearDown()

    def write_rules(self, rules, raw=None, **top):
        data = {"version": 1, "rules": rules, **top}
        self.rules_path.write_text(raw if raw is not None else json.dumps(data), encoding="utf-8")

    def rule(self, code, **changes):
        rules = [dict(r) for r in RULES]
        for r in rules:
            if r["type_code"] == code:
                r.update(changes)
        return rules


class RulesTests(RulesFileMixin, TestCase):
    def setUp(self):
        super().setUp()
        setup_p8()

    def test_tc001_rules(self):
        out = periodic.periodic_rules()
        self.assertEqual([r["type_code"] for r in out["rules"]], ["D10", "D12", "D11"])
        self.assertEqual(out["rules"][0]["name"], "일반위생관리 및 공정점검표")
        self.assertEqual(out["rules"][2]["cadence"], "weekly")
        self.assertEqual(out["rules"][0]["start_date"], MON)

    def test_tc001_default_file(self):
        """저장소의 규칙 파일도 검증을 통과한다(start_date = S4 구현 주 월요일, S2-Q2)."""
        with override_settings(HACCP_PERIODIC_RULES=None):
            out = periodic.periodic_rules()
        self.assertEqual(
            [(r["type_code"], r["cadence"], r["start_date"]) for r in out["rules"]],
            [("D10", "daily", MON), ("D12", "daily", MON), ("D11", "weekly", MON)],
        )

    def test_tc002_invalid(self):
        cases = [
            ({"version": 2}, "version"),
            ({"extra": 1}, "extra"),
            ({"rules": []}, "rules"),
            ({"rules": [{**RULES[0], "cadance": "daily"}]}, "rules[0].cadance"),
            ({"rules": [{**RULES[0], "cadence": "monthly"}]}, "rules[0].cadence"),
            ({"rules": [{**RULES[0], "weekdays": [0, 8]}]}, "rules[0].weekdays"),
            ({"rules": [{**RULES[0], "weekdays": [1, 1]}]}, "rules[0].weekdays"),
            ({"rules": [{**RULES[0], "start_date": "2026/10/12"}]}, "rules[0].start_date"),
            ({"rules": [{**RULES[0], "enabled": "yes"}]}, "rules[0].enabled"),
            # D-144 A3·B: 형식 함정(1.0·true·bool 요일·숫자 날짜·ISO 주 날짜·뒤에 글자)
            ({"version": 1.0}, "version"),
            ({"version": True}, "version"),
            ({"rules": [{**RULES[0], "weekdays": [True]}]}, "rules[0].weekdays"),
            ({"rules": [{**RULES[0], "start_date": 20261012}]}, "rules[0].start_date"),
            ({"rules": [{**RULES[0], "start_date": "2026-W42-1"}]}, "rules[0].start_date"),
            ({"rules": [{**RULES[0], "start_date": "20261012xx"}]}, "rules[0].start_date"),
            ({"rules": [RULES[0], RULES[0]]}, "rules[1].type_code"),
            ({"rules": [{**RULES[0], "type_code": "D99"}]}, "rules[0].type_code"),
        ]
        before = Document.objects.count()
        for top, path in cases:
            with self.subTest(path=path):
                data = {"version": 1, "rules": RULES, **top}
                self.rules_path.write_text(json.dumps(data), encoding="utf-8")
                with self.assertRaises(errors.RulesInvalid) as caught, today(FRI):
                    run(TUE)
                self.assertIn(path, [d["path"] for d in caught.exception.details])
        self.write_rules(RULES, raw="{not json")
        with self.assertRaises(errors.RulesInvalid) as caught:
            periodic.periodic_rules()
        self.assertEqual(caught.exception.details[0]["path"], "$")
        self.rules_path.unlink()
        with self.assertRaises(errors.RulesInvalid) as caught:
            periodic.periodic_rules()
        self.assertEqual(caught.exception.details[0]["code"], "missing")
        self.assertEqual(Document.objects.count(), before)


class RunTests(RulesFileMixin, TestCase):
    def setUp(self):
        super().setUp()
        setup_p8()

    def tearDown(self):
        self.assertEqual(invariant_violations(), [])
        super().tearDown()

    def test_tc010_one_day(self):
        with today(FRI):
            out = run(TUE)
        self.assertEqual(
            results(out),
            [(MON, "D11", "created"), (TUE, "D10", "created"), (TUE, "D12", "created")],
        )
        self.assertEqual(
            [line["record_key"] for line in out["lines"]],
            [f"D11|week:{MON}", f"D10|day:{TUE}", f"D12|day:{TUE}"],
        )
        self.assertEqual(
            out["totals"], {"created": 3, "existing": 0, "skipped_rule": 0, "failed": 0}
        )
        self.assertEqual((out["date_from"], out["date_to"], out["actor_id"]), (TUE, TUE, 3))
        d11 = doc.get_document(out["lines"][0]["document_id"])
        self.assertEqual((d11["work_date"], d11["status"], d11["created_by"]), (MON, "draft", 3))
        self.assertEqual(d11["refs"], [])
        self.assertIsNone(d11["assignee_id"])  # P9-Q4 a

    def test_tc011_again(self):
        with today(FRI):
            first = run(TUE)
            versions = {d.pk: d.version for d in Document.objects.all()}
            second = run(TUE)
        self.assertEqual([line["result"] for line in second["lines"]], ["existing"] * 3)
        self.assertEqual(
            [line["document_id"] for line in second["lines"]],
            [line["document_id"] for line in first["lines"]],
        )
        self.assertEqual({d.pk: d.version for d in Document.objects.all()}, versions)

    def test_tc012_saturday(self):
        before = Document.objects.count()
        with today(SUN):
            out = run(SAT)
        self.assertEqual(
            [(line["type_code"], line["result"], line.get("reason")) for line in out["lines"]],
            [
                ("D11", "skipped_rule", "weekday"),
                ("D10", "skipped_rule", "weekday"),
                ("D12", "skipped_rule", "weekday"),
            ],
        )
        self.assertEqual(out["lines"][0]["work_date"], MON)  # D11 줄은 그 주 월요일
        self.assertNotIn("document_id", out["lines"][0])
        self.assertEqual(Document.objects.count(), before)

    def test_tc013_week(self):
        with today(SUN):
            out = run(MON, SUN)
        counts = {}
        for _, code, result in results(out):
            counts[(code, result)] = counts.get((code, result), 0) + 1
        self.assertEqual(
            counts,
            {
                ("D10", "created"): 5,
                ("D12", "created"): 5,
                ("D10", "skipped_rule"): 2,
                ("D12", "skipped_rule"): 2,
                ("D11", "created"): 1,
            },
        )
        self.assertEqual(out["lines"][0]["type_code"], "D10")  # 월요일: 규칙 파일 순서 D10·D12·D11
        self.assertEqual([line["type_code"] for line in out["lines"][:3]], ["D10", "D12", "D11"])

    def test_tc014_two_weeks(self):
        with today(NEXT_TUE):
            out = run(WED, NEXT_TUE)
        d11 = [line for line in out["lines"] if line["type_code"] == "D11"]
        self.assertEqual(
            [(line["work_date"], line["result"]) for line in d11],
            [(MON, "created"), (NEXT_MON, "created")],
        )  # 첫 주 월요일은 기간 밖이어도 그 주 문서

    def test_tc015_start_wednesday(self):
        self.write_rules([{**r, "start_date": WED} for r in RULES])
        with today(FRI):
            out = run(MON, FRI)
        d10 = [(line["work_date"], line["result"], line.get("reason")) for line in out["lines"]]
        self.assertIn((MON, "skipped_rule", "before_start"), d10)
        self.assertIn((TUE, "skipped_rule", "before_start"), d10)
        made = [line for line in out["lines"] if line["result"] == "created"]
        self.assertEqual(
            sorted({line["work_date"] for line in made if line["type_code"] != "D11"}),
            [WED, THU, FRI],
        )
        self.assertEqual(
            [line["result"] for line in out["lines"] if line["type_code"] == "D11"], ["created"]
        )  # S2-Q1 a

    def test_tc015b_weekly_before_start_whole_week(self):
        self.write_rules([{**r, "start_date": NEXT_MON} for r in RULES])
        with today(FRI):
            out = run(MON, FRI)
        d11 = [line for line in out["lines"] if line["type_code"] == "D11"]
        self.assertEqual(
            [(d["result"], d["reason"]) for d in d11], [("skipped_rule", "before_start")]
        )

    def test_tc016_disabled(self):
        self.write_rules(self.rule("D12", enabled=False))
        with today(FRI):
            out = run(TUE)
        self.assertEqual(
            [(line["type_code"], line["result"], line.get("reason")) for line in out["lines"]],
            [
                ("D11", "created", None),
                ("D10", "created", None),
                ("D12", "skipped_rule", "disabled"),
            ],
        )

    def test_tc017_existing_status(self):
        with today(FRI):
            first = run(TUE, types=["D10", "D12"])
            d10, d12 = (line["document_id"] for line in first["lines"])
            doc.skip_documents(3, [{"document_id": d10, "expected_version": 1}], "휴무")
            done = fill(d12)
            doc.complete_document(3, d12, done["version"])
            again = run(TUE, types=["D10", "D12"])
        self.assertEqual(
            [(line["result"], line["status"]) for line in again["lines"]],
            [("existing", "skipped"), ("existing", "completed")],
        )  # 상태 그대로(만든 뒤 바뀐 문서도 건드리지 않음)

    def test_tc018_template_inactive(self):
        DocumentTemplate.objects.filter(type_code="D12").update(is_active=False)
        with today(FRI), captured() as steps:
            out = run(TUE)
        failed = [line for line in out["lines"] if line["result"] == "failed"]
        self.assertEqual(
            [(line["type_code"], line["code"]) for line in failed], [("D12", "TEMPLATE_INACTIVE")]
        )
        self.assertEqual(out["totals"]["created"], 2)
        self.assertEqual(out["totals"]["failed"], 1)
        self.assertFalse(Document.objects.filter(record_key=f"D12|day:{TUE}").exists())
        self.assertTrue(flows.matches("REQ-PRN", ["REQ-PRN-01", *steps]), steps)

    def test_tc019_initial_values(self):
        with today(FRI):
            out = run(FRI, types=["D10"])
        values = checks_row(doc.get_document(out["lines"][0]["document_id"]))["values"]
        self.assertEqual(values.get("r_incoming"), "O")  # initial
        self.assertNotEqual(values.get("w_pest_count"), "NA")  # 금요일 = 주 항목 대상

    def test_tc020_input(self):
        before = Document.objects.count()
        cases = [
            ((SAT, SAT), None, "date_to", "future"),
            (("2026-09-01", "2026-10-02"), None, "date_to", "max"),
            ((WED, TUE), None, "date_from", "order"),
            (("2026-10-1", TUE), None, "date_from", "invalid"),
            (("2026-W42-2", TUE), None, "date_from", "invalid"),  # D-144 A3
            ((TUE, "20261013xx"), None, "date_to", "invalid"),
            ((TUE, TUE), [], "type_codes", "required"),
            ((TUE, TUE), ["D10", "D10"], "type_codes[1]", "duplicate"),
            ((TUE, TUE), ["D03"], "type_codes[0]", "not_periodic"),
        ]
        for (start, end), types, path, code in cases:
            with self.subTest(path=path, code=code), today(FRI):
                with self.assertRaises(errors.ValidationFailed) as caught:
                    periodic.run_periodic(3, start, end, types)
                self.assertIn(
                    (path, code), [(d["path"], d["code"]) for d in caught.exception.details]
                )
        with today(TUE):
            run(TUE)  # 31일 경계: 정확히 31일은 허용
            periodic.run_periodic(3, "2026-09-13", TUE, ["D11"])
        self.assertEqual(
            Document.objects.count(), before + 3
        )  # D11 그 주는 이미 있음, 앞 주는 시작일 전

    def test_tc021_staff(self):
        before = Document.objects.count()
        with today(FRI):
            for actor in (999, 0, "3"):
                with self.subTest(actor=actor), self.assertRaises(InvalidStaff):
                    periodic.run_periodic(actor, TUE, TUE)
        self.assertEqual(Document.objects.count(), before)

    def test_tc022_transaction(self):
        with today(FRI):
            out = run(TUE)  # 바깥 트랜잭션 없음(테스트 자체 트랜잭션만)
            with transaction.atomic():
                inner = run(WED)
        self.assertEqual(out["totals"]["created"], 3)
        self.assertEqual(inner["totals"]["created"], 2)  # D11은 이미 있음
        self.assertEqual(inner["totals"]["existing"], 1)


class OpenTests(RulesFileMixin, TestCase):
    def setUp(self):
        super().setUp()
        setup_p8()

    def test_tc030_open(self):
        with captured() as steps:
            first = periodic.open_periodic_document(3, "D10", TUE)
        self.assertTrue(flows.matches("REQ-POD", ["REQ-POD-01", *steps]), steps)
        self.assertEqual(
            (first["result"], first["record_key"], first["work_date"], first["status"]),
            ("created", f"D10|day:{TUE}", TUE, "draft"),
        )
        doc.skip_documents(
            3, [{"document_id": first["document_id"], "expected_version": 1}], "휴무"
        )
        again = periodic.open_periodic_document(3, "D10", TUE)
        self.assertEqual(
            (again["result"], again["status"], again["document_id"]),
            ("existing", "skipped", first["document_id"]),
        )

    def test_tc031_future_weekend(self):
        out = periodic.open_periodic_document(3, "D12", "2026-10-24")  # 다음 주 토요일
        self.assertEqual((out["result"], out["record_key"]), ("created", "D12|day:2026-10-24"))

    def test_tc032_weekly(self):
        out = periodic.open_periodic_document(3, "D11", THU)
        self.assertEqual((out["record_key"], out["work_date"]), (f"D11|week:{MON}", MON))

    def test_tc033_disabled_and_not_periodic(self):
        self.write_rules(self.rule("D12", enabled=False))
        self.assertEqual(periodic.open_periodic_document(3, "D12", TUE)["result"], "created")
        with self.assertRaises(errors.NotPeriodic):
            periodic.open_periodic_document(3, "D03", TUE)
        with self.assertRaises(errors.ValidationFailed):
            periodic.open_periodic_document(3, "D10", "2026-10-1")
        with self.assertRaises(errors.ValidationFailed):
            periodic.open_periodic_document(3, "D10", "2026-W42-2")  # D-144 A3
        with self.assertRaises(InvalidStaff):
            periodic.open_periodic_document(999, "D10", TUE)

    def test_tc034_035_delete_and_skip(self):
        out = periodic.open_periodic_document(3, "D10", "2026-10-30")  # 날짜를 잘못 고름
        with self.assertRaises(doc_errors.DocumentNotDeletable):
            doc.delete_document(3, out["document_id"])  # C-3, ISS-028
        skipped = doc.skip_documents(
            3, [{"document_id": out["document_id"], "expected_version": 1}], "날짜 잘못 고름"
        )
        self.assertEqual(skipped["succeeded"], 1)


class ApiTests(RulesFileMixin, TestCase):
    def setUp(self):
        super().setUp()
        setup_p8()

    def post(self, path, body, staff="3"):
        headers = {} if staff is None else {"HTTP_X_STAFF_ID": staff}
        return self.client.post(
            f"/api/v1/{path}", json.dumps(body), content_type="application/json", **headers
        )

    def test_tc040_runs(self):
        body = {"date_from": TUE, "date_to": TUE}
        self.assertEqual(self.post("periodic-runs", body, staff=None).status_code, 400)
        self.assertEqual(self.post("periodic-runs", body, staff="999").status_code, 403)
        unknown = self.post("periodic-runs", {**body, "dry_run": True})
        self.assertEqual((unknown.status_code, unknown.json()["code"]), (400, "INVALID_REQUEST"))
        with today(FRI), captured() as steps:
            ok = self.post("periodic-runs", body)
        self.assertEqual(ok.status_code, 200, ok.content)
        self.assertTrue(flows.matches("REQ-PRN", steps), steps)
        self.assertEqual(ok.json()["totals"]["created"], 3)
        with today(FRI):
            future = self.post("periodic-runs", {"date_from": SAT, "date_to": SAT})
        self.assertEqual((future.status_code, future.json()["code"]), (400, "VALIDATION_ERROR"))
        with today(SUN), captured() as steps:
            self.post("periodic-runs", {"date_from": SAT, "date_to": SAT})
        self.assertTrue(flows.matches("REQ-PRN-NONE", steps), steps)
        self.write_rules(RULES, raw="[]")
        with today(FRI), self.assertLogs("django.request", "ERROR"):  # 500은 서버 오류 로그
            broken = self.post("periodic-runs", body)
        self.assertEqual((broken.status_code, broken.json()["code"]), (500, "RULES_INVALID"))

    def test_tc040_documents_and_rules(self):
        self.assertEqual(
            self.post(
                "periodic-documents", {"type_code": "D10", "date": TUE}, staff=None
            ).status_code,
            400,
        )
        with captured() as steps:
            ok = self.post("periodic-documents", {"type_code": "D11", "date": WED})
        self.assertEqual(ok.status_code, 200, ok.content)
        self.assertTrue(flows.matches("REQ-POD", steps), steps)
        self.assertEqual(ok.json()["work_date"], MON)
        bad = self.post("periodic-documents", {"type_code": "D03", "date": WED})
        self.assertEqual((bad.status_code, bad.json()["code"]), (400, "NOT_PERIODIC"))
        DocumentTemplate.objects.filter(type_code="D12").update(is_active=False)
        inactive = self.post("periodic-documents", {"type_code": "D12", "date": WED})
        self.assertEqual(
            (inactive.status_code, inactive.json()["code"]), (409, "TEMPLATE_INACTIVE")
        )
        with captured() as steps:
            listed = self.client.get("/api/v1/periodic-rules")
        self.assertEqual(listed.status_code, 200)
        self.assertTrue(flows.matches("REQ-PRL", steps), steps)
        self.assertIsNone(listed.json()["rules"][1]["name"])  # D12 활성 양식 없음

    def test_tc041_requirement_only(self):
        template_id = DocumentTemplate.objects.get(type_code="D10", is_active=True).pk
        response = self.post("documents", {"template_id": template_id, "work_date": TUE})
        self.assertEqual(
            (response.status_code, response.json()["code"]), (409, "TEMPLATE_REQUIREMENT_ONLY")
        )


class CommandTests(RulesFileMixin, TestCase):
    def setUp(self):
        super().setUp()
        setup_p8()

    def call(self, *args):
        out, err = io.StringIO(), io.StringIO()
        call_command("make_periodic_documents", *args, stdout=out, stderr=err)
        return out.getvalue()

    def test_tc050_ok(self):
        with today(TUE):
            text = self.call("--actor", "3")
        lines = text.strip().splitlines()
        self.assertEqual(len(lines), 4)
        self.assertRegex(lines[0], rf"^{MON} D11 created +#\d+ D11\|week:{MON}$")
        self.assertEqual(lines[-1], "합계: 만듦 3 · 이미 있음 0 · 대상 아님 0 · 실패 0")
        with today(TUE):
            again = self.call("--actor", "3", "--date", TUE)
        self.assertIn("existing", again)
        self.assertIn("(draft)", again)

    def test_tc050_failed_line(self):
        DocumentTemplate.objects.filter(type_code="D12").update(is_active=False)
        with today(TUE), self.assertRaises(CommandError) as caught:
            self.call("--actor", "3", "--from", MON, "--to", TUE, "--type", "D10,D12")
        self.assertEqual(caught.exception.returncode, 1)
        self.assertEqual(Document.objects.filter(record_key__startswith="D10|day:").count(), 2)

    def test_tc050_unexpected_error(self):
        """D-144 A1: ApiError가 아닌 예외(DB 오류 등)도 종료 코드 2 — 1("일부 만들어짐")과 구분."""
        from django.db import OperationalError

        boom = OperationalError("database is locked")
        with today(TUE), mock.patch.object(periodic, "run_periodic", side_effect=boom):
            with self.assertRaises(CommandError) as caught:
                self.call("--actor", "3")
        self.assertEqual(caught.exception.returncode, 2)
        self.assertIn("OperationalError", str(caught.exception))
        self.assertIn("아무것도 만들지 않았습니다", str(caught.exception))

    def test_tc050_input_errors(self):
        cases = [
            ("--actor", "3", "--date", TUE, "--from", MON),
            ("--actor", "3", "--from", MON),
            ("--actor", "3", "--date", SAT),
            ("--actor", "999"),
            ("--actor", "3", "--type", "D03"),
        ]
        before = Document.objects.count()
        for args in cases:
            with self.subTest(args=args), today(FRI), self.assertRaises(CommandError) as caught:
                self.call(*args)
            self.assertEqual(caught.exception.returncode, 2)
        self.write_rules(RULES, raw="{")
        with today(FRI), self.assertRaises(CommandError) as caught:
            self.call("--actor", "3")
        self.assertEqual(caught.exception.returncode, 2)
        self.assertIn("RULES_INVALID", str(caught.exception))
        self.assertEqual(Document.objects.count(), before)


class RequirementLabelTests(RulesFileMixin, TestCase):
    """P9-TC-060: DOC F04·F05 requirement — 주기 periodic / 입고 lot / 배치 batch / 일반 null."""

    def setUp(self):
        super().setUp()
        setup_req()
        setup_p8()

    def test_tc060(self):
        with today(FRI):
            d10 = run(TUE, types=["D10"])["lines"][0]["document_id"]
        with transaction.atomic():
            lot = req.require_for_lot(3, 88)["documents"]
            batch = req.require_for_batch(3, 12)["documents"]
        templates = ensure_templates()  # 일반 양식(CCP 가열 등)
        made = doc.create_document(3, ccp_payload(templates[("CCP_MONITORING", 1)]))
        expected = {
            d10: "periodic",
            lot[0]["document_id"]: "lot",
            batch[0]["document_id"]: "batch",
            made["document_id"]: None,
        }
        for document_id, label in expected.items():
            self.assertEqual(doc.get_document(document_id)["requirement"], label, document_id)
        listed = {
            row["document_id"]: row.get("requirement")
            for row in doc.list_documents({"from": "2026-10-01", "to": FRI})["items"]
            if row.get("kind") != "bundle"
        }
        self.assertEqual(listed.get(made["document_id"]), None)
        self.assertEqual(listed.get(lot[0]["document_id"]), "lot")


@override_settings(
    ROOT_URLCONF="apps.devtools.test_urls",
    MIDDLEWARE=[*settings.MIDDLEWARE, "apps.devtools.middleware.TraceMiddleware"],
)
class DevSnapshotTests(RulesFileMixin, TestCase):
    """C4 S5: 개발 콘솔 ④ 패널 — 기간의 주기 문서(작업일 범위, weekly는 그 주 월요일부터)."""

    def setUp(self):
        super().setUp()
        setup_req()
        setup_p8()

    def test_periodic_scope_snapshot(self):
        with today(FRI):
            run(WED, FRI)
        with transaction.atomic():
            lot = req.require_for_lot(3, 88)["documents"][0]["document_id"]
        data = self.client.get(f"/api/dev/snapshot?periodic_from={WED}&periodic_to={WED}").json()
        self.assertEqual(data["scope"], {"periodic_from": WED, "periodic_to": WED})
        keys = sorted(r["record_key"] for r in data["tables"]["document"])
        self.assertEqual(keys, [f"D10|day:{WED}", f"D11|week:{MON}", f"D12|day:{WED}"])
        self.assertTrue(data["tables"]["doc_section"])
        self.assertNotIn(lot, [r["document_id"] for r in data["tables"]["document"]])
        bad = self.client.get("/api/dev/snapshot?periodic_from=2026-13-01")
        self.assertEqual(bad.status_code, 400)
