"""P8 S4 양식 확장 (p8-s2-spec 7장 P8-TC-001~051, DOC 몫). 이름의 tcNNN은 P8-TC ID.

WF가 필요한 것(TC-036 상신, TC-070 일괄 승인)은 document_workflow/tests/test_p8_wf.py,
REQ-F06(TC-060·061)은 doc_requirements/tests/test_p8.py. DOC 테스트는 WF를 import하지 않는다.
"""

import json

from django.db import IntegrityError, connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.documents import errors, flows, services, validation
from apps.documents.models import Document
from apps.documents.seed_forms import D10, D11, D12

from .p8 import (
    FIRST_MON,
    FRI,
    MON,
    THU,
    TUE,
    WED,
    captured,
    checks_row,
    fill,
    info_row,
    periodic,
    result_keys,
    setup_p8,
)

WEEKLY = ("w_pest_count", "w_clean_noncontact", "w_laundry")
MONTHLY = ("m_clean_all", "m_education", "m_product_test", "m_ccp_verify")
YEARLY_DATES = ("y_water_test_date", "y_calibration_date")  # 종이대로 실시일만(검토 A4)


def version_of(document_id):
    return Document.objects.get(pk=document_id).version


class P8Case(TestCase):
    def setUp(self):
        self.t = setup_p8()

    def post(self, path, body, staff=3):
        headers = {} if staff is None else {"HTTP_X_STAFF_ID": str(staff)}
        return self.client.post(
            f"/api/v1/{path}", data=json.dumps(body), content_type="application/json", **headers
        )

    def assertError(self, response, status, code):
        self.assertEqual(response.status_code, status, response.content)
        self.assertEqual(response.json()["code"], code)
        return response.json()

    def items(self, *details):
        return [
            {"document_id": d["document_id"], "expected_version": version_of(d["document_id"])}
            for d in details
        ]

    def skip(self, *details, reason="휴무", staff=3):
        return self.post("documents/batch-skip", {"items": self.items(*details), "reason": reason})

    def direct_d10(self):
        """직접 만든 D10(record_key 없음) — requirement_only라 API로는 못 만들어 ORM으로."""
        from django.utils import timezone

        now = timezone.now()
        document = Document.objects.create(
            template=self.t["D10"],
            work_date=TUE,
            created_by_id=3,
            status="draft",
            created_at=now,
            updated_at=now,
        )
        return {"document_id": document.document_id}


# ---------------------------------------------------------------- 시드·N1·F05


class SeedTests(P8Case):
    def test_tc001_seed(self):
        for code, schema, count in (("D10", D10, 24), ("D12", D12, 17), ("D11", D11, 12)):
            self.assertEqual(validation.check_template_schema(schema), [], code)
            fields = sum(len(s["fields"]) for s in schema["sections"])
            self.assertEqual(fields, count, code)
            self.assertTrue(schema["skippable"] and schema["requirement_only"], code)
        # 결과 필드 수: D10 21(연간 2줄은 실시일만), D12 15, D11 9 / 매일(규칙 없는) 항목 D10 13
        self.assertEqual([len(result_keys(c)) for c in ("D10", "D12", "D11")], [21, 15, 9])
        d10 = next(s for s in D10["sections"] if s["key"] == "checks")
        daily = [
            f
            for f in d10["fields"]
            if f["type"] == "select" and not {"na_default", "initial"} & set(f)
        ]
        self.assertEqual(len(daily), 13)
        dates = [f for f in d10["fields"] if f["type"] == "date"]
        self.assertEqual([f["key"] for f in dates], list(YEARLY_DATES))
        self.assertFalse(any("required" in f or "na_default" in f for f in dates))

    def test_schema_key_checks(self):
        """새 키 형식 검사(check_template_schema)."""
        base = {
            "key": "r",
            "label": "결과",
            "type": "select",
            "options": ["O", "X", "NA"],
        }
        cases = [
            ({**base, "na_default": {"weekday": 8}}, "na_default"),
            ({**base, "na_default": {"weekday": 5, "first_weekday_of_month": 1}}, "na_default"),
            ({**base, "options": ["O", "X"], "na_default": {}}, "na_default"),
            ({**base, "initial": "Y"}, "initial"),
            ({"key": "d", "type": "date", "date_window": {"from": 3, "to": 1}}, "date_window"),
            ({"key": "t", "type": "text", "date_window": {"from": 0, "to": 6}}, "date_window"),
        ]
        for field, word in cases:
            schema = {
                "sections": [
                    {
                        "key": "s",
                        "repeat": False,
                        "fields": [base, field] if field["key"] != "r" else [field],
                    }
                ]
            }
            problems = validation.check_template_schema(schema)
            self.assertTrue(any(word in p for p in problems), (field, problems))
        self.assertIn(
            "skippable은 true/false여야 합니다.",
            validation.check_template_schema(
                {"skippable": 1, "sections": [{"key": "s", "repeat": False, "fields": [base]}]}
            ),
        )


class PrefillTests(P8Case):
    def test_tc002_na_default(self):
        expected = {
            FRI: (None, "NA"),  # 금요일: 주 항목 빈칸, 월 항목 NA
            FIRST_MON: ("NA", None),  # 그 달 첫째 월요일: 주 항목 NA, 월 항목 빈칸
            TUE: ("NA", "NA"),
        }
        for day, (weekly, monthly) in expected.items():
            values = checks_row(periodic("D10", day))["values"]
            for key in WEEKLY:
                self.assertEqual(values.get(key), weekly, (day, key))
            for key in MONTHLY:
                self.assertEqual(values.get(key), monthly, (day, key))
            for key in YEARLY_DATES:
                self.assertNotIn(key, values, (day, key))  # 미리 채우지 않음
        # 둘째 월요일(10-12)은 월 항목 NA
        self.assertEqual(checks_row(periodic("D10", MON))["values"]["m_clean_all"], "NA")

    def test_first_monday_boundaries(self):
        """그 달 첫째 월요일이 1일(2026-06-01)·7일(2026-09-07), 둘째 월요일(09-14)."""
        for day, monthly in (("2026-06-01", None), ("2026-09-07", None), ("2026-09-14", "NA")):
            values = checks_row(periodic("D10", day))["values"]
            self.assertEqual(values.get("m_clean_all"), monthly, day)
            self.assertEqual(values.get("w_laundry"), "NA", day)

    def test_requirement_periodic(self):
        """검토 A2: 참조 없는 작성 요구 문서는 periodic(P9 규칙 앞당김) — 상세·목록 문서 줄."""
        self.assertEqual(periodic("D10", TUE)["requirement"], "periodic")
        d11 = periodic("D11", MON)
        rows = self.client.get("/api/v1/documents").json()["items"]
        row = next(r for r in rows if r.get("document_id") == d11["document_id"])
        self.assertEqual(row["requirement"], "periodic")

    def test_tc003_caller_value_wins(self):
        detail = periodic("D10", TUE, values={"checks": {"w_laundry": "O"}})
        values = checks_row(detail)["values"]
        self.assertEqual(values["w_laundry"], "O")
        self.assertEqual(values["w_pest_count"], "NA")
        self.assertNotIn("checks.w_laundry", detail["prefilled"])

    def test_tc005_incoming_initial(self):
        detail = periodic("D10", FRI)
        self.assertEqual(checks_row(detail)["values"]["r_incoming"], "O")
        self.assertIn("checks.r_incoming", detail["prefilled"])
        # 매일 항목은 비어 있음
        self.assertNotIn("d_hyg_clothes", checks_row(detail)["values"])

    def test_tc004_prefilled_only_version_1(self):
        detail = periodic("D10", TUE)
        self.assertEqual(detail["version"], 1)
        self.assertEqual(
            sorted(detail["prefilled"]),
            sorted(["checks.r_incoming", *(f"checks.{k}" for k in (*WEEKLY, *MONTHLY))]),
        )
        self.assertTrue(detail["skippable"])
        self.assertIsNone(detail["skip"])
        after = fill(detail["document_id"])
        self.assertEqual(after["prefilled"], [])
        # 다시 부르면 existing, 같은 상세
        again = periodic("D10", TUE)
        self.assertEqual(again["document_id"], detail["document_id"])
        # D12·D11은 미리 채울 것 없음
        self.assertEqual(periodic("D12", TUE)["prefilled"], [])
        self.assertEqual(periodic("D11", MON)["prefilled"], [])

    def test_existing_document_not_prefilled_again(self):
        """N1 재호출(이미 있음)은 값을 바꾸지 않는다."""
        detail = fill(periodic("D10", TUE)["document_id"])
        with transaction.atomic():
            out = services.get_or_create_document(3, "D10", f"D10|day:{TUE}", TUE, [])
        self.assertFalse(out["created"])
        self.assertEqual(checks_row(out["document"])["values"], checks_row(detail)["values"])


# ---------------------------------------------------------------- F07·F12


class SaveRuleTests(P8Case):
    def patch(self, detail, section, values):
        row = checks_row(detail) if section == "checks" else info_row(detail)
        return self.client.patch(
            f"/api/v1/documents/{detail['document_id']}",
            data=json.dumps(
                {
                    "expected_version": detail["version"],
                    "sections": {"update": [{"section_id": row["section_id"], "values": values}]},
                }
            ),
            content_type="application/json",
            HTTP_X_STAFF_ID="3",
        )

    def test_tc010_option_values(self):
        detail = periodic("D10", TUE)
        for values in ({"d_hyg_clothes": "Y"}, {"d_hyg_clothes": "NA"}):
            body = self.assertError(self.patch(detail, "checks", values), 400, "VALIDATION_ERROR")
            self.assertEqual(body["details"][0]["path"], "sections.update[0].values.d_hyg_clothes")
        self.assertEqual(self.patch(detail, "checks", {"w_laundry": "NA"}).status_code, 200)

    def test_tc011_date_window(self):
        detail = periodic("D11", MON)
        for day, ok in (("2026-10-18", True), ("2026-10-19", False), ("2026-10-11", False)):
            current = services.get_document(detail["document_id"])
            response = self.patch(current, "info", {"checked_on": day})
            if ok:
                self.assertEqual(response.status_code, 200, response.content)
            else:
                body = self.assertError(response, 400, "VALIDATION_ERROR")
                self.assertEqual(body["details"][0]["code"], "date_window")

    def test_tc012_yearly_date(self):
        """연간 실시일은 선택 날짜 — 형식만 보고, 비워도 작성완료·부적합과 무관(검토 A4)."""
        detail = periodic("D10", TUE)
        bad = self.assertError(
            self.patch(detail, "checks", {"y_water_test_date": "2026-13-01"}),
            400,
            "VALIDATION_ERROR",
        )
        self.assertEqual(bad["details"][0]["code"], "invalid")
        ok = self.patch(detail, "checks", {"y_water_test_date": "2026-03-05"})
        self.assertEqual(ok.status_code, 200, ok.content)
        done = fill(detail["document_id"], extra={"checks": {"y_water_test_date": None}})
        done = services.complete_document(3, done["document_id"], done["version"])
        self.assertEqual(done["status"], "completed")

    def test_n1_initial_values_checked(self):
        """N1 호출자 값도 date_window를 본다."""
        with self.assertRaises(errors.ValidationFailed):
            periodic("D11", MON, values={"info": {"checked_on": "2026-10-20"}})

    def test_tc020_blank_blocks_completion(self):
        detail = fill(periodic("D10", TUE)["document_id"])
        row = checks_row(detail)
        detail = services.update_document(
            3,
            detail["document_id"],
            {
                "expected_version": detail["version"],
                "sections": {
                    "update": [
                        {"section_id": row["section_id"], "values": {"d_proc_package": None}}
                    ]
                },
            },
        )
        with self.assertRaises(errors.CompletionIncomplete) as ctx:
            services.complete_document(3, detail["document_id"], detail["version"])
        self.assertEqual(
            [d["path"] for d in ctx.exception.details],
            ["sections[checks#1].values.d_proc_package"],
        )

    def test_tc021_x_needs_deviation(self):
        detail = fill(periodic("D12", TUE)["document_id"], extra={"checks": {"pack_film": "X"}})
        with self.assertRaises(errors.CompletionIncomplete) as ctx:
            services.complete_document(3, detail["document_id"], detail["version"])
        self.assertEqual([d["code"] for d in ctx.exception.details], ["deviation_required"])
        services.create_deviation(3, detail["document_id"], {"description": "비닐 조각 발견"})
        done = services.complete_document(
            3, detail["document_id"], version_of(detail["document_id"])
        )
        self.assertEqual(done["status"], "completed")

    def test_tc022_na_only_no_deviation(self):
        detail = fill(periodic("D10", TUE)["document_id"])  # 주·월·연 NA, 나머지 O
        self.assertEqual(
            services.complete_document(3, detail["document_id"], detail["version"])["status"],
            "completed",
        )

    def test_d11_completion_needs_checked_on(self):
        detail = periodic("D11", MON)
        row = checks_row(detail)
        detail = services.update_document(
            3,
            detail["document_id"],
            {
                "expected_version": 1,
                "sections": {
                    "update": [
                        {
                            "section_id": row["section_id"],
                            "values": dict.fromkeys(result_keys("D11"), "O"),
                        }
                    ]
                },
            },
        )
        with self.assertRaises(errors.CompletionIncomplete) as ctx:
            services.complete_document(3, detail["document_id"], detail["version"])
        self.assertEqual(
            sorted(d["path"].rsplit(".", 1)[1] for d in ctx.exception.details),
            ["checked_on", "inspector"],
        )


# ---------------------------------------------------------------- F27·F28 작성 안 함·되돌리기


class SkipTests(P8Case):
    def test_tc030_skip_three(self):
        made = [periodic("D10", day) for day in (MON, TUE, WED)]
        with captured() as steps:
            response = self.skip(*made, reason="  휴무  ")
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual((body["action"], body["total"], body["succeeded"]), ("skip", 3, 3))
        for line, detail in zip(body["results"], made, strict=True):
            self.assertEqual(line["result"], {"status": "skipped", "version": 2})
            current = services.get_document(detail["document_id"])
            self.assertEqual(current["status"], "skipped")
            self.assertEqual(current["skip"]["reason"], "휴무")
            self.assertEqual(current["skip"]["by"], 3)
            # 값은 그대로
            self.assertEqual(checks_row(current)["values"], checks_row(detail)["values"])
        ids = list(steps)
        batch_flow = flows.BATCH["DOC-SKP"]
        self.assertEqual(
            ids,
            batch_flow["head"] + batch_flow["items"]["skipped"] * 3 + batch_flow["tail"],
        )

    def test_tc031_mixed(self):
        completed = fill(periodic("D10", MON)["document_id"])
        completed = services.complete_document(3, completed["document_id"], completed["version"])
        d03 = self.d03()
        direct = self.direct_d10()
        stale = periodic("D10", TUE)
        good = periodic("D10", WED)
        items = self.items(completed, d03, direct, stale, good)
        items[3]["expected_version"] = 9
        response = self.post("documents/batch-skip", {"items": items, "reason": "작업 없음"})
        body = response.json()
        self.assertEqual(response.status_code, 200, body)
        codes = [r["ok"] or r["error"]["code"] for r in body["results"]]
        self.assertEqual(
            codes,
            [
                "INVALID_TRANSITION",
                "DOCUMENT_NOT_SKIPPABLE",
                "DOCUMENT_NOT_SKIPPABLE",
                "VERSION_CONFLICT",
                True,
            ],
        )
        self.assertEqual((body["succeeded"], body["failed"]), (1, 4))
        self.assertEqual(services.get_document(stale["document_id"])["status"], "draft")

    def d03(self):
        from apps.documents.tests.p4 import D03_INFO, lot_ref, stub

        stub("items", id=1, name="유자")
        stub(
            "lots",
            id=88,
            lot_number="RM-1011-01",
            item_id=1,
            lot_kind="INCOMING",
            status="QUARANTINE",
        )
        with transaction.atomic():
            return services.get_or_create_document(
                3, "D03", "D03|lot:88", TUE, lot_ref(88), values={"info": dict(D03_INFO)}
            )["document"]

    def test_tc032_request_errors(self):
        made = periodic("D10", TUE)
        before = version_of(made["document_id"])
        for reason in ("   ", "가" * 201, None):
            self.assertError(self.skip(made, reason=reason), 400, "VALIDATION_ERROR")
        too_many = [{"document_id": i, "expected_version": 1} for i in range(1, 52)]
        self.assertError(
            self.post("documents/batch-skip", {"items": too_many, "reason": "휴무"}),
            400,
            "INVALID_REQUEST",
        )
        self.assertEqual(version_of(made["document_id"]), before)
        self.assertError(
            self.post("documents/batch-skip", {"items": [], "reason": "휴무"}),
            400,
            "INVALID_REQUEST",
        )
        self.assertError(
            self.post(
                "documents/batch-skip", {"items": self.items(made), "reason": "휴무"}, staff=None
            ),
            400,
            "STAFF_HEADER_MISSING",
        )

    def test_fifty_items_ok(self):
        from datetime import date, timedelta

        start = date(2026, 1, 5)
        made = [periodic("D10", (start + timedelta(days=n)).isoformat()) for n in range(50)]
        body = self.skip(*made).json()
        self.assertEqual((body["total"], body["succeeded"]), (50, 50))

    def test_reason_200_ok(self):
        made = periodic("D10", TUE)
        self.assertEqual(self.skip(made, reason="가" * 200).json()["succeeded"], 1)

    def test_tc033_unskip(self):
        made = fill(periodic("D10", TUE)["document_id"])
        self.skip(made)
        with captured() as steps:
            response = self.post(
                f"documents/{made['document_id']}/unskip", {"expected_version": made["version"] + 1}
            )
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(
            (body["status"], body["skip"], body["version"]), ("draft", None, made["version"] + 2)
        )
        self.assertEqual(checks_row(body)["values"], checks_row(made)["values"])
        row = Document.objects.get(pk=made["document_id"])
        self.assertEqual((row.skipped_at, row.skipped_by_id, row.skip_reason), (None, None, None))
        self.assertTrue(flows.matches("DOC-USK", steps))

    def test_tc034_skipped_locked(self):
        made = periodic("D10", TUE)
        self.skip(made)
        version = version_of(made["document_id"])
        row = checks_row(made)
        patch = self.client.patch(
            f"/api/v1/documents/{made['document_id']}",
            data=json.dumps(
                {
                    "expected_version": version,
                    "sections": {
                        "update": [
                            {"section_id": row["section_id"], "values": {"d_hyg_clothes": "O"}}
                        ]
                    },
                }
            ),
            content_type="application/json",
            HTTP_X_STAFF_ID="3",
        )
        self.assertError(patch, 409, "DOCUMENT_LOCKED")
        self.assertError(
            self.post(f"documents/{made['document_id']}/complete", {"expected_version": version}),
            409,
            "INVALID_TRANSITION",
        )
        delete = self.client.delete(f"/api/v1/documents/{made['document_id']}", HTTP_X_STAFF_ID="3")
        self.assertError(delete, 409, "DOCUMENT_NOT_DELETABLE")
        # 작성중 문서 되돌리기 / 버전 틀림 / 없는 문서
        other = periodic("D10", WED)
        self.assertError(
            self.post(f"documents/{other['document_id']}/unskip", {"expected_version": 1}),
            409,
            "INVALID_TRANSITION",
        )
        self.assertError(
            self.post(f"documents/{made['document_id']}/unskip", {"expected_version": 1}),
            409,
            "VERSION_CONFLICT",
        )
        self.assertError(
            self.post("documents/99999/unskip", {"expected_version": 1}), 404, "DOCUMENT_NOT_FOUND"
        )
        self.assertEqual(version_of(made["document_id"]), version)

    def test_tc035_n1_keeps_skipped(self):
        made = periodic("D10", TUE)
        self.skip(made)
        with transaction.atomic():
            out = services.get_or_create_document(3, "D10", f"D10|day:{TUE}", TUE, [])
        self.assertFalse(out["created"])
        self.assertEqual(out["document"]["status"], "skipped")

    def test_db_checks(self):
        """v7.1 CHECK: skipped면 기록 필수, 셋은 짝, 사유 공백만 불가, 작성완료 기록 없음."""
        made = periodic("D10", TUE)
        bad = [
            "UPDATE document SET status = 'skipped' WHERE document_id = %s",
            "UPDATE document SET skipped_at = '2026-10-13 00:00:00', skipped_by = 3, "
            "skip_reason = '휴무' WHERE document_id = %s",
            "UPDATE document SET status = 'skipped', skipped_at = '2026-10-13 00:00:00', "
            "skipped_by = 3 WHERE document_id = %s",
            "UPDATE document SET status = 'skipped', skipped_at = '2026-10-13 00:00:00', "
            "skipped_by = 3, skip_reason = '   ' WHERE document_id = %s",
            "UPDATE document SET status = 'skipped', skipped_at = '2026-10-13 00:00:00', "
            "skipped_by = 3, skip_reason = '휴무', completed_at = '2026-10-13 00:00:00', "
            "completed_by = 3 WHERE document_id = %s",
        ]
        for statement in bad:
            with self.subTest(statement=statement):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute(statement, [made["document_id"]])


# ---------------------------------------------------------------- F29 최근 값


class RecentValueTests(P8Case):
    def test_tc040_recent(self):
        for day, name in ((MON, "내포장"), (TUE, "세척"), (WED, "내포장")):
            fill(periodic("D12", day)["document_id"], extra={"info": {"process_name": name}})
        deleted_or_blank = periodic("D12", THU)
        fill(deleted_or_blank["document_id"], extra={"info": {"process_name": "  "}})
        with captured() as steps:
            response = self.client.get(
                "/api/v1/documents/recent-values?type_code=D12&field=process_name"
            )
        self.assertEqual(response.json(), {"items": ["내포장", "세척"]})
        self.assertTrue(flows.matches("DOC-RCV", steps))
        self.assertEqual(
            services.recent_values("D12", "info", "process_name", limit=1), {"items": ["내포장"]}
        )

    def test_recent_errors(self):
        for query in (
            "type_code=D12&field=nope",
            "type_code=D12&field=pack_film",  # select
            "type_code=ZZ&field=process_name",
            "type_code=D12",
        ):
            self.assertError(
                self.client.get(f"/api/v1/documents/recent-values?{query}"), 400, "INVALID_FILTER"
            )
        self.assertError(
            self.client.get("/api/v1/documents/recent-values?type_code=D12&field=process_name&x=1"),
            400,
            "INVALID_REQUEST",
        )


# ---------------------------------------------------------------- F04 주 묶음 줄·F26


class WeekBundleListTests(P8Case):
    def week(self):
        made = {day: periodic("D10", day) for day in (MON, TUE, WED, THU, FRI)}
        for day in (MON, TUE, FRI):
            d = fill(made[day]["document_id"])
            services.complete_document(3, d["document_id"], d["version"])
        self.skip(made[WED])
        with transaction.atomic():  # 결재중(상신 잠금 — DOC 함수, 결재 기록은 이 테스트 밖)
            services.lock_for_review(made[FRI]["document_id"])
        return made

    def test_tc050_week_row(self):
        self.week()
        SkipTests.d03(self)  # 같은 주 D03 — 날짜 줄 그대로
        response = self.client.get(f"/api/v1/documents?from={MON}&to=2026-10-18")
        items = response.json()["items"]
        bundles = [i for i in items if i["kind"] == "bundle"]
        d10 = [b for b in bundles if b["type_code"] == "D10"]
        self.assertEqual(len(d10), 1)
        self.assertEqual(
            {
                k: d10[0][k]
                for k in (
                    "work_date",
                    "period_end",
                    "bundle_unit",
                    "count",
                    "total",
                    "status_counts",
                    "requirement",
                )
            },
            {
                "work_date": MON,
                "period_end": FRI,
                "bundle_unit": "week",
                "count": 5,
                "total": 5,
                "status_counts": {"completed": 2, "skipped": 1, "draft": 1, "submitted": 1},
                "requirement": "periodic",
            },
        )
        d03_rows = [b for b in bundles if b["type_code"] == "D03"]
        self.assertEqual(
            [(b["work_date"], b["bundle_unit"], b["period_end"]) for b in d03_rows],
            [(TUE, "day", None)],
        )

    def test_tc051_skipped_filter(self):
        self.week()
        items = self.client.get("/api/v1/documents?status=skipped").json()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(
            (items[0]["count"], items[0]["total"], items[0]["status_counts"]),
            (1, 5, {"skipped": 1}),
        )

    def test_weekend_in_same_week_row(self):
        periodic("D10", MON)
        periodic("D10", "2026-10-18")  # 일요일 → 같은 주(월 12일) 줄
        periodic("D10", "2026-10-19")  # 다음 주 월요일
        rows = [
            i for i in self.client.get("/api/v1/documents").json()["items"] if i["kind"] == "bundle"
        ]
        self.assertEqual(
            [(r["work_date"], r["count"]) for r in rows], [("2026-10-19", 1), (MON, 2)]
        )

    def test_week_row_sorted_by_latest_day(self):
        """ISS-031(P8-S5-Q1 a): 주 줄은 그 주 가장 늦은 작업일 자리(수요일 문서 → 화요일보다 앞)."""
        from django.utils import timezone

        periodic("D10", MON)
        periodic("D10", WED)
        periodic("D11", MON)
        now = timezone.now()
        tue = Document.objects.create(
            template=self.t["D01"],
            work_date=TUE,
            created_by_id=3,
            status="draft",
            created_at=now,
            updated_at=now,
        )
        items = self.client.get(f"/api/v1/documents?from={MON}&to={FRI}").json()["items"]
        order = [(i["kind"], i.get("type_code") or i["template"]["type_code"]) for i in items]
        self.assertEqual(order, [("bundle", "D10"), ("document", "D01"), ("document", "D11")])
        self.assertEqual(items[0]["work_date"], MON)  # 표시 날짜는 그대로 월요일
        self.assertEqual(items[1]["document_id"], tue.document_id)

    def test_list_flow_and_queries(self):
        self.week()
        with captured() as steps, CaptureQueriesContext(connection) as ctx:
            self.client.get("/api/v1/documents?from=2026-10-01")
        self.assertTrue(flows.matches("DOC-LST", steps))
        self.assertLessEqual(len(ctx.captured_queries), 6)

    def test_brief_check_counts(self):
        detail = fill(
            periodic("D10", TUE)["document_id"],
            extra={"checks": {"d_proc_zone": "X", "d_proc_metal": None}},
        )
        brief = services.brief_documents([detail["document_id"]])["items"][0]
        self.assertEqual(brief["check_counts"], {"O": 12, "X": 1, "NA": 7, "blank": 1})
        # 검토 A5(Q3 b): 판정 필드 없는 점검표도 nonconforming 계산 — X 있음 True
        self.assertEqual((brief["verdict"], brief["nonconforming"]), (None, True))

    def test_brief_nonconforming_states(self):
        clean = fill(periodic("D12", TUE)["document_id"])  # 다 채움, X 없음 → False
        blank = periodic("D12", WED)  # 빈칸, X 없음 → None
        ccp_like = periodic("D11", MON)
        briefs = {
            b["document_id"]: b["nonconforming"]
            for b in services.brief_documents(
                [clean["document_id"], blank["document_id"], ccp_like["document_id"]]
            )["items"]
        }
        self.assertEqual(
            [briefs[clean["document_id"]], briefs[blank["document_id"]]], [False, None]
        )


class InspectorTypesTests(P8Case):
    def test_batch_inspector_d10(self):
        made = periodic("D11", MON)
        response = self.post(
            "documents/batch-inspector",
            {
                "items": [{"document_id": made["document_id"], "expected_version": 1}],
                "inspector_id": 4,
            },
        )
        self.assertEqual(response.json()["succeeded"], 1, response.content)
        self.assertEqual(
            info_row(services.get_document(made["document_id"]))["values"]["inspector"], 4
        )
