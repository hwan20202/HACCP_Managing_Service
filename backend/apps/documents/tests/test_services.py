"""메소드 테스트 (수준 M): 서비스 함수를 직접 호출한다. 이름의 tcNNN은 s2-spec 7장의 TC ID."""

from unittest.mock import patch

from django.db import DatabaseError, transaction
from django.test import TestCase, TransactionTestCase

from apps.core.http import ApiError
from apps.documents import errors, services
from apps.documents.models import DocSection, Document
from apps.documents.tests.base import (
    ccp_payload,
    make_document,
    setup_reference_data,
    snapshot,
    update_current,
)


class ReferenceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.t = setup_reference_data()

    def test_tc001_list_staff(self):
        self.assertEqual(services.list_staff(), [1, 2, 3, 4, 5])

    def test_tc003_list_templates_latest_active_only(self):
        items = services.list_templates()
        self.assertEqual(
            [(i["type_code"], i["version"]) for i in items],
            [("CCP_MONITORING", 1), ("HYGIENE_CHECK", 1)],
        )
        self.assertNotIn("schema", items[0])

    def test_tc005_get_template_not_found(self):
        with self.assertRaises(errors.TemplateNotFound):
            services.get_template(9999)


class CreateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.t = setup_reference_data()

    def assertNoDocuments(self):
        self.assertEqual(Document.objects.count(), 0)
        self.assertEqual(DocSection.objects.count(), 0)

    def details(self, ctx):
        return {d["path"]: d["code"] for d in ctx.exception.details}

    def test_tc010_create_ok(self):
        result = services.create_document(3, ccp_payload(self.t["ccp"]))
        document = Document.objects.get(pk=result["document_id"])
        self.assertEqual(document.status, "draft")
        self.assertEqual(document.created_by_id, 3)
        self.assertEqual(document.assignee_id, 2)
        self.assertEqual(document.updated_at, document.created_at)
        rows = list(DocSection.objects.filter(document=document).order_by("section_def", "row_no"))
        self.assertEqual(
            [(r.section_def, r.row_no) for r in rows], [("info", 1), ("rounds", 1), ("rounds", 2)]
        )
        self.assertTrue(all(r.recorded_by_id == 3 and r.recorded_at for r in rows))
        self.assertTrue(result["created_at"].endswith("+09:00"))  # DOC-NFR-07

    def test_tc013_inactive_template(self):
        with self.assertRaises(errors.TemplateInactive):
            services.create_document(3, ccp_payload(self.t["ccp_v0"]))
        self.assertNoDocuments()

    def test_tc014_basic_fields(self):
        cases = [
            ({"work_date": None}, "work_date"),
            ({"work_date": "2026-02-30"}, "work_date"),
            ({"work_date": "20261009"}, "work_date"),
            ({"subject": "가" * 101}, "subject"),
        ]
        for override, path in cases:
            with self.subTest(override=override):
                with self.assertRaises(errors.ValidationFailed) as ctx:
                    services.create_document(3, ccp_payload(self.t["ccp"], **override))
                self.assertIn(path, self.details(ctx))
        self.assertNoDocuments()

    def test_tc015_unknown_assignee(self):
        with self.assertRaises(errors.ValidationFailed) as ctx:
            services.create_document(3, ccp_payload(self.t["ccp"], assignee_id=999))
        self.assertEqual(self.details(ctx), {"assignee_id": "unknown_staff"})

    def test_tc016_section_structure(self):
        base = ccp_payload(self.t["ccp"])
        info = base["sections"][0]
        cases = {
            "unknown section": base["sections"] + [{"section_def": "nope", "values": {}}],
            "info twice": base["sections"] + [info],
        }
        for name, sections in cases.items():
            with self.subTest(name), self.assertRaises(errors.ValidationFailed):
                services.create_document(3, ccp_payload(self.t["ccp"], sections=sections))
        self.assertNoDocuments()
        # P4 §7.1: info 누락은 저장 성공, 빈 info 행이 만들어진다(C-2)
        created = services.create_document(
            3, ccp_payload(self.t["ccp"], sections=base["sections"][1:])
        )
        info_rows = DocSection.objects.filter(
            document_id=created["document_id"], section_def="info"
        )
        self.assertEqual([r.values_json for r in info_rows], [{}])

    def test_tc017_field_values(self):
        payload = ccp_payload(self.t["ccp"])
        payload["sections"][0]["values"] = {
            "product": "유자차"
        }  # lot 필수 누락 → 저장 때는 검사 안 함
        payload["sections"][1]["values"].update({"temp": "abc", "color": "red", "measured_by": 999})
        with self.assertRaises(errors.ValidationFailed) as ctx:
            services.create_document(3, payload)
        self.assertEqual(
            self.details(ctx),
            {
                "sections[1].values.temp": "invalid",
                "sections[1].values.color": "unknown_field",
                "sections[1].values.measured_by": "unknown_staff",
            },
        )

    def test_tc018_max_rows(self):
        rows = [
            {
                "section_def": "rounds",
                "values": {
                    "round": f"{h:02d}:{m:02d}",
                    "temp": 86,
                    "hold_sec": 16,
                    "measured_by": 3,
                },
            }
            for h in range(24)
            for m in (0, 20, 40)
        ][:49]
        payload = ccp_payload(self.t["ccp"])
        payload["sections"] = payload["sections"][:1] + rows
        with self.assertRaises(errors.ValidationFailed) as ctx:
            services.create_document(3, payload)
        self.assertEqual(self.details(ctx), {"sections[rounds]": "max_rows"})

    def test_tc019_duplicate_round_and_retake(self):
        payload = ccp_payload(self.t["ccp"])
        payload["sections"][2]["values"]["round"] = "09:00"
        with self.assertRaises(errors.DuplicateRound):
            services.create_document(3, payload)
        payload["sections"][2]["values"]["retake"] = False  # false도 재측정 아님(M7)
        with self.assertRaises(errors.DuplicateRound):
            services.create_document(3, payload)
        payload["sections"][2]["values"]["retake"] = True
        services.create_document(3, payload)
        self.assertEqual(Document.objects.count(), 1)


class ListAndGetTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.t = setup_reference_data()
        cls.docs = []
        for n in range(25):
            doc, _ = make_document(
                cls.t["ccp"], author=(n % 5) + 1, work_date=f"2026-10-{(n % 9) + 1:02d}"
            )
            cls.docs.append(doc)
        cls.hygiene_doc, _ = make_document(
            cls.t["hygiene"], work_date="2026-10-01", status="approved"
        )
        cls.deleted, _ = make_document(cls.t["ccp"], deleted=True)

    def test_tc030_paging_and_order(self):
        page1 = services.list_documents({}, 1)
        page2 = services.list_documents({}, 2)
        self.assertEqual(page1["total"], 26)  # 삭제 1건 제외
        self.assertEqual(len(page1["items"]), 20)
        self.assertEqual(len(page2["items"]), 6)
        keys = [(i["work_date"], i["document_id"]) for i in page1["items"] + page2["items"]]
        self.assertEqual(keys, sorted(keys, reverse=True))
        self.assertNotIn(self.deleted.document_id, [i["document_id"] for i in page1["items"]])

    def test_tc031_filters(self):
        def ids(**filters):
            return {i["document_id"] for i in services.list_documents(filters, 1)["items"]}

        self.assertEqual(
            ids(**{"from": "2026-10-09", "to": "2026-10-09"}),
            {d.document_id for d in self.docs if str(d.work_date) == "2026-10-09"},
        )
        self.assertEqual(
            ids(template_id=str(self.t["hygiene"].template_id)), {self.hygiene_doc.document_id}
        )
        self.assertEqual(ids(status="approved"), {self.hygiene_doc.document_id})
        self.assertEqual(services.list_documents({"author_id": "2"}, 1)["total"], 5)
        self.assertEqual(services.list_documents({"assignee_id": "2"}, 1)["total"], 26)

    def test_tc033_query_count(self):
        with self.assertNumQueries(3):  # 개수 + 목록 + 대상 요약(NFR-03: 4개 이하)
            services.list_documents({"from": "2026-10-01", "to": "2026-10-09"}, 1)

    def test_tc040_get_document_ordered(self):
        result = services.get_document(self.docs[0].document_id)
        self.assertEqual(
            [(s["section_def"], s["row_no"]) for s in result["sections"]],
            [("info", 1), ("rounds", 1), ("rounds", 2)],
        )
        self.assertEqual(result["template"]["type_code"], "CCP_MONITORING")

    def test_get_deleted_or_missing(self):
        for document_id in (self.deleted.document_id, 99999):
            with self.subTest(document_id), self.assertRaises(errors.DocumentNotFound):
                services.get_document(document_id)


class UpdateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.t = setup_reference_data()

    def setUp(self):
        self.doc, self.rows = make_document(self.t["ccp"])

    def full_patch(self):
        return {
            "document": {"subject": "CCP-2B/라인B"},
            "sections": {
                "add": [
                    {
                        "section_def": "rounds",
                        "values": {
                            "round": "11:00",
                            "temp": 86.0,
                            "hold_sec": 15,
                            "measured_by": 3,
                        },
                    }
                ],
                "update": [
                    {
                        "section_id": self.rows["r1"].section_id,
                        "values": {"temp": 85.5, "note": None},
                    }
                ],
                "delete": [self.rows["r2"].section_id],
            },
        }

    def test_tc050_only_changes_are_applied(self):
        info_before = DocSection.objects.get(pk=self.rows["info"].section_id)
        r1_before = DocSection.objects.get(pk=self.rows["r1"].section_id)
        result = update_current(4, self.doc.document_id, self.full_patch())
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.subject, "CCP-2B/라인B")
        self.assertGreater(self.doc.updated_at, self.doc.created_at)
        info_after = DocSection.objects.get(pk=self.rows["info"].section_id)
        self.assertEqual(
            (info_after.values_json, info_after.recorded_at, info_after.recorded_by_id),
            (info_before.values_json, info_before.recorded_at, 3),
        )  # DOC-FR-07
        r1 = DocSection.objects.get(pk=self.rows["r1"].section_id)
        self.assertEqual(
            r1.values_json, {"round": "09:00", "temp": 85.5, "hold_sec": 16, "measured_by": 3}
        )
        self.assertEqual(r1.recorded_by_id, 4)  # DOC-FR-08
        self.assertGreater(r1.recorded_at, r1_before.recorded_at)
        self.assertFalse(DocSection.objects.filter(pk=self.rows["r2"].section_id).exists())
        new = DocSection.objects.get(document=self.doc, values_json__round="11:00")
        self.assertEqual((new.row_no, new.recorded_by_id), (3, 4))
        self.assertEqual(len(result["sections"]), 3)

    def test_tc052_locked_statuses_change_nothing(self):
        for status in ("submitted", "approved"):
            with self.subTest(status):
                doc, rows = make_document(self.t["ccp"], status=status)
                before = snapshot(doc.document_id)
                with self.assertRaises(errors.DocumentLocked):
                    update_current(3, doc.document_id, {"document": {"subject": "x"}})
                self.assertEqual(snapshot(doc.document_id), before)

    def test_tc053_rejected_is_editable(self):
        doc, _ = make_document(self.t["ccp"], status="rejected")
        update_current(3, doc.document_id, {"document": {"subject": "수정"}})
        doc.refresh_from_db()
        self.assertEqual((doc.subject, doc.status), ("수정", "rejected"))

    def test_tc054_row_of_other_document(self):
        other, other_rows = make_document(self.t["ccp"])
        before = snapshot(self.doc.document_id)
        patch_body = {
            "document": {"subject": "x"},
            "sections": {"delete": [other_rows["r1"].section_id]},
        }
        with self.assertRaises(errors.SectionRowNotFound):
            update_current(3, self.doc.document_id, patch_body)
        self.assertEqual(snapshot(self.doc.document_id), before)  # 잠금 UPDATE까지 롤백

    def test_tc055_single_row_section(self):
        for body in (
            {"sections": {"delete": [self.rows["info"].section_id]}},
            {"sections": {"add": [{"section_def": "info", "values": {}}]}},
        ):
            with self.subTest(body), self.assertRaises(errors.ValidationFailed):
                update_current(3, self.doc.document_id, body)

    def test_tc056_required_checked_after_merge(self):
        body = {
            "sections": {
                "update": [{"section_id": self.rows["r1"].section_id, "values": {"temp": None}}]
            }
        }
        result = update_current(3, self.doc.document_id, body)  # 저장은 성공(C-2)
        with self.assertRaises(errors.CompletionIncomplete) as ctx:
            services.complete_document(3, self.doc.document_id, result["version"])
        self.assertIn("required", {d["code"] for d in ctx.exception.details})

    def test_tc057_duplicate_round_and_delete_then_add(self):
        add_0900 = {
            "section_def": "rounds",
            "values": {"round": "09:00", "temp": 86, "hold_sec": 16, "measured_by": 3},
        }
        with self.assertRaises(errors.DuplicateRound):
            update_current(3, self.doc.document_id, {"sections": {"add": [add_0900]}})
        update_current(
            3,
            self.doc.document_id,
            {"sections": {"delete": [self.rows["r1"].section_id], "add": [add_0900]}},
        )
        self.assertEqual(
            DocSection.objects.filter(document=self.doc, values_json__round="09:00").count(), 1
        )

    def test_no_changes(self):
        with self.assertRaises(errors.NoChanges):
            update_current(3, self.doc.document_id, {})

    def test_tc060_failure_rolls_back_everything(self):
        before = snapshot(self.doc.document_id)
        with patch.object(DocSection.objects, "bulk_create", side_effect=DatabaseError("boom")):
            with self.assertRaises(DatabaseError):
                update_current(3, self.doc.document_id, self.full_patch())
        self.assertEqual(snapshot(self.doc.document_id), before)


class DeleteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.t = setup_reference_data()

    def test_tc070_logical_delete(self):
        doc, _ = make_document(self.t["ccp"])
        sections_before = snapshot(doc.document_id)[1]
        services.delete_document(3, doc.document_id)
        doc.refresh_from_db()
        self.assertIsNotNone(doc.deleted_at)
        self.assertEqual(doc.deleted_by_id, 3)
        self.assertEqual(snapshot(doc.document_id)[1], sections_before)

    def test_tc072_not_deletable(self):
        cases = [
            dict(status="submitted"),
            dict(status="approved"),
            dict(status="rejected"),
            dict(status="draft", submitted=True),
        ]
        for kwargs in cases:
            with self.subTest(kwargs):
                doc, _ = make_document(self.t["ccp"], **kwargs)
                before = snapshot(doc.document_id)
                with self.assertRaises(errors.DocumentNotDeletable):
                    services.delete_document(3, doc.document_id)
                self.assertEqual(snapshot(doc.document_id), before)

    def test_already_deleted(self):
        doc, _ = make_document(self.t["ccp"], deleted=True)
        with self.assertRaises(errors.DocumentNotFound):
            services.delete_document(3, doc.document_id)


class LifecycleTests(TestCase):
    """F09~F11: TestCase는 테스트마다 트랜잭션 안에서 실행되므로 WF 트랜잭션 안 호출과 같다."""

    @classmethod
    def setUpTestData(cls):
        cls.t = setup_reference_data()

    def status_of(self, doc):
        doc.refresh_from_db()
        return doc.status

    def test_tc080_lock_completed(self):
        doc, _ = make_document(self.t["ccp"], status="completed")
        result = services.lock_for_review(doc.document_id)
        doc.refresh_from_db()
        self.assertEqual((result["status"], doc.status), ("submitted", "submitted"))
        self.assertIsNotNone(doc.submitted_at)

    def test_tc081_lock_rejected_resubmit(self):
        doc, _ = make_document(self.t["ccp"], status="rejected")
        with self.assertRaises(errors.DocumentLocked):  # 반려 상태에서 바로 상신 불가
            services.lock_for_review(doc.document_id)
        services.complete_document(3, doc.document_id, 1)
        services.lock_for_review(doc.document_id)
        self.assertEqual(self.status_of(doc), "submitted")

    def test_tc082_lock_failures(self):
        for kwargs, error in (
            (dict(status="submitted"), errors.DocumentLocked),
            (dict(status="approved"), errors.DocumentLocked),
            (dict(deleted=True), errors.DocumentNotFound),
        ):
            with self.subTest(kwargs):
                doc, _ = make_document(self.t["ccp"], **kwargs)
                with self.assertRaises(error):
                    services.lock_for_review(doc.document_id)

    def test_tc083_mark_approved(self):
        doc, _ = make_document(self.t["ccp"], status="submitted")
        services.mark_approved(doc.document_id)
        self.assertEqual(self.status_of(doc), "approved")
        draft, _ = make_document(self.t["ccp"])
        with self.assertRaises(errors.InvalidTransition):
            services.mark_approved(draft.document_id)

    def test_tc084_mark_rejected(self):
        doc, _ = make_document(self.t["ccp"], status="submitted")
        services.mark_rejected(doc.document_id)
        self.assertEqual(self.status_of(doc), "rejected")
        approved, _ = make_document(self.t["ccp"], status="approved")
        with self.assertRaises(errors.InvalidTransition):
            services.mark_rejected(approved.document_id)


class LifecycleOutsideTransactionTests(TransactionTestCase):
    def test_tc085_transaction_required(self):
        t = setup_reference_data()
        doc, _ = make_document(t["ccp"], status="submitted")
        for func in (services.lock_for_review, services.mark_approved, services.mark_rejected):
            with self.subTest(func.__name__), self.assertRaises(errors.TransactionRequired):
                func(doc.document_id)
        with transaction.atomic():
            services.mark_approved(doc.document_id)
        doc.refresh_from_db()
        self.assertEqual(doc.status, "approved")


class VersionTests(TestCase):
    """ISS-001: 문서 단위 버전 번호로 동시 수정 충돌을 감지한다."""

    @classmethod
    def setUpTestData(cls):
        cls.t = setup_reference_data()

    def version(self, doc):
        return Document.objects.get(pk=doc.document_id).version

    def test_tc063_stale_version_is_rejected(self):
        doc, _ = make_document(self.t["ccp"])
        services.update_document(
            3, doc.document_id, {"expected_version": 1, "document": {"subject": "A"}}
        )
        before = snapshot(doc.document_id)
        with self.assertRaises(errors.VersionConflict) as ctx:
            services.update_document(
                4, doc.document_id, {"expected_version": 1, "document": {"subject": "B"}}
            )
        detail = ctx.exception.details[0]
        self.assertEqual((detail["expected"], detail["current"]), (1, 2))
        self.assertEqual(snapshot(doc.document_id), before)  # version·updated_at 포함 변화 없음

    def test_expected_version_required_in_service(self):
        doc, _ = make_document(self.t["ccp"])
        for bad in (None, "1", 0, True):
            with self.subTest(bad), self.assertRaises(ApiError) as ctx:
                services.update_document(
                    3, doc.document_id, {"expected_version": bad, "document": {"subject": "x"}}
                )
            self.assertEqual(ctx.exception.code, "INVALID_REQUEST")

    def test_tc065_every_write_increments_version(self):
        created = services.create_document(3, ccp_payload(self.t["ccp"]))
        doc = Document.objects.get(pk=created["document_id"])
        self.assertEqual(created["version"], 1)
        steps = [
            lambda: services.update_document(
                3, doc.document_id, {"expected_version": 1, "document": {"subject": "1"}}
            ),
            lambda: services.complete_document(3, doc.document_id, 2),
            lambda: services.lock_for_review(doc.document_id),
            lambda: services.mark_rejected(doc.document_id),
            lambda: services.update_document(
                3, doc.document_id, {"expected_version": 5, "document": {"subject": "2"}}
            ),
            lambda: services.complete_document(3, doc.document_id, 6),
            lambda: services.lock_for_review(doc.document_id),
            lambda: services.mark_approved(doc.document_id),
        ]
        versions = []
        for call in steps:
            call()
            versions.append(self.version(doc))
        self.assertEqual(versions, [2, 3, 4, 5, 6, 7, 8, 9])
        other, _ = make_document(self.t["ccp"])
        services.delete_document(3, other.document_id)
        self.assertEqual(self.version(other), 2)

    def test_tc066_status_is_reported_before_version(self):
        doc, _ = make_document(self.t["ccp"], status="submitted")
        with self.assertRaises(errors.DocumentLocked):
            services.update_document(
                3, doc.document_id, {"expected_version": 99, "document": {"subject": "x"}}
            )


class LockVersionTests(TestCase):
    """WF 변경 요청 C-1: 상신 잠금도 화면이 본 버전을 확인한다."""

    @classmethod
    def setUpTestData(cls):
        cls.t = setup_reference_data()

    def test_tc086_lock_with_expected_version(self):
        doc, _ = make_document(self.t["ccp"])
        update_current(3, doc.document_id, {"document": {"subject": "v2"}})
        services.complete_document(3, doc.document_id, 2)
        before = snapshot(doc.document_id)
        with self.assertRaises(errors.VersionConflict):
            services.lock_for_review(doc.document_id, expected_version=2)
        self.assertEqual(snapshot(doc.document_id), before)
        result = services.lock_for_review(doc.document_id, expected_version=3)
        self.assertEqual((result["status"], result["version"]), ("submitted", 4))

    def test_tc086_status_before_version(self):
        doc, _ = make_document(self.t["ccp"], status="approved")
        with self.assertRaises(errors.DocumentLocked):
            services.lock_for_review(doc.document_id, expected_version=99)
