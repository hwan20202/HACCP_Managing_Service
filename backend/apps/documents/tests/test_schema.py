"""마이그레이션으로 만든 실제 스키마가 ERD v5(erd/v5/schema.sql)와 같은지 확인한다.

P4 S3 검토 V2: Django 마이그레이션 결과 ↔ 확정 DDL 동등성.
알려진 차이(erd/v5/erd.md "실제 DB와의 차이")는 비교하지 않는다:
Django 테이블의 PK AUTOINCREMENT, FK의 ON DELETE(ORM이 처리), CHECK 문구 모양.
"""

from django.db import connection
from django.test import TestCase

# ERD v5: 테이블 → {컬럼: NOT NULL 여부}. PK 컬럼은 NOT NULL로 본다.
EXPECTED_COLUMNS = {
    "staff": {"staff_id": True},
    "document_template": {
        "template_id": True,
        "type_code": True,
        "version": True,
        "name": True,
        "schema_json": True,
        "is_active": True,
        "created_at": True,
    },
    "document": {
        "document_id": True,
        "template_id": True,
        "subject": False,
        "work_date": True,
        "assignee_id": False,
        "created_by": True,
        "due_at": False,
        "status": True,
        "submitted_at": False,
        "record_key": False,
        "completed_at": False,
        "completed_by": False,
        "created_at": True,
        "updated_at": True,
        "version": True,
        "deleted_at": False,
        "deleted_by": False,
    },
    "doc_section": {
        "section_id": True,
        "document_id": True,
        "section_def": True,
        "row_no": True,
        "values_json": True,
        "recorded_at": False,
        "recorded_by": False,
    },
    "document_ref": {
        "ref_id": True,
        "document_id": True,
        "section_id": False,
        "lot_id": False,
        "production_batch_id": False,
        "item_id": False,
        "process_code": False,
        "label": False,
        "created_at": True,
    },
    "file": {
        "file_id": True,
        "storage_path": True,
        "original_name": True,
        "mime_type": True,
        "size_bytes": True,
        "sha256": True,
        "uploaded_by": True,
        "uploaded_at": True,
        "retained_at": False,
    },
    "document_file": {"document_id": True, "file_id": True, "linked_by": True, "linked_at": True},
    "deviation_action": {
        "deviation_id": True,
        "document_id": True,
        "section_id": False,
        "description": True,
        "action_result": False,
        "actor_id": False,
        "checked_by": False,
        "checked_at": False,
        "created_by": True,
        "created_at": True,
        "updated_by": True,
        "updated_at": True,
        "version": True,
        "deleted_at": False,
        "deleted_by": False,
    },
    "deviation_checker": {"deviation_id": True, "staff_id": True},
}
# (테이블, 컬럼) → 참조 테이블
EXPECTED_FKS = {
    ("document", "template_id"): "document_template",
    ("document", "assignee_id"): "staff",
    ("document", "created_by"): "staff",
    ("document", "completed_by"): "staff",
    ("document", "deleted_by"): "staff",
    ("doc_section", "document_id"): "document",
    ("doc_section", "recorded_by"): "staff",
    ("document_ref", "document_id"): "document",
    ("document_ref", "lot_id"): "lots",
    ("document_ref", "production_batch_id"): "production_batches",
    ("document_ref", "item_id"): "items",
    ("file", "uploaded_by"): "staff",
    ("document_file", "document_id"): "document",
    ("document_file", "file_id"): "file",
    ("document_file", "linked_by"): "staff",
    ("deviation_action", "document_id"): "document",
    ("deviation_action", "section_id"): "doc_section",
    ("deviation_action", "actor_id"): "staff",
    ("deviation_action", "checked_by"): "staff",
    ("deviation_action", "created_by"): "staff",
    ("deviation_action", "updated_by"): "staff",
    ("deviation_action", "deleted_by"): "staff",
    ("deviation_checker", "deviation_id"): "deviation_action",
    ("deviation_checker", "staff_id"): "staff",
}
# 문서 도메인 테이블의 명시적 인덱스(FK 자동 인덱스 없음)
EXPECTED_INDEXES = {
    "ix_document_list",
    "ux_document_record_key",
    "ux_section_round",
    "ux_document_ref",
    "ix_document_ref_lot",
    "ix_document_ref_batch",
    "ix_document_ref_item",
    "ix_document_ref_process",
    "ix_document_ref_label",
    "ix_document_file_file",
    "ix_deviation_document",
    "ix_deviation_checker_staff",
}


class SchemaMatchesErdV5Tests(TestCase):
    def query(self, sql, params=()):
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall()

    def ddl(self):
        return dict(self.query("SELECT name, sql FROM sqlite_master WHERE type='table'"))

    def test_columns_and_not_null(self):
        for table, columns in EXPECTED_COLUMNS.items():
            with self.subTest(table):
                info = {
                    row[1]: bool(row[3]) or bool(row[5])
                    for row in self.query(f'PRAGMA table_info("{table}")')
                }
                self.assertEqual(info, columns)

    def test_foreign_keys(self):
        found = {}
        for table in EXPECTED_COLUMNS:
            for row in self.query(f'PRAGMA foreign_key_list("{table}")'):
                if table == "document_ref" and row[2] == "doc_section":
                    continue  # 복합 FK는 아래에서 따로 본다
                found[(table, row[3])] = row[2]
        self.assertEqual(found, EXPECTED_FKS)

    def test_document_ref_composite_fk_and_cascade(self):
        # document_ref만 RunSQL로 DDL 그대로 만든다: 복합 FK와 ON DELETE가 DB에 있다(D-059 Q6).
        rows = self.query('PRAGMA foreign_key_list("document_ref")')
        composite = sorted((r[3], r[4]) for r in rows if r[2] == "doc_section")
        self.assertEqual(composite, [("document_id", "document_id"), ("section_id", "section_id")])
        actions = {(r[2], r[3]): r[6] for r in rows}
        self.assertEqual(actions[("document", "document_id")], "CASCADE")
        self.assertEqual(actions[("doc_section", "section_id")], "CASCADE")
        self.assertEqual(actions[("lots", "lot_id")], "RESTRICT")
        self.assertIn("AUTOINCREMENT", self.ddl()["document_ref"])

    def test_indexes(self):
        tables = ", ".join(f"'{t}'" for t in EXPECTED_COLUMNS)
        rows = dict(
            self.query(
                "SELECT name, sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL "
                f"AND tbl_name IN ({tables})"
            )
        )
        self.assertEqual(set(rows), EXPECTED_INDEXES)
        self.assertIn('WHERE "deleted_at" IS NULL', rows["ix_document_list"])
        self.assertIn(
            "COALESCE(json_extract(values_json, '$.retake'), 0) = 0", rows["ux_section_round"]
        )
        self.assertIn('"record_key" IS NOT NULL', rows["ux_document_record_key"])
        self.assertIn("COALESCE(process_code, '')", rows["ux_document_ref"])

    def test_unique_and_check_constraints(self):
        ddl = self.ddl()
        self.assertIn('UNIQUE ("type_code", "version")', ddl["document_template"])
        self.assertIn('UNIQUE ("document_id", "section_def", "row_no")', ddl["doc_section"])
        self.assertIn(
            '"ux_section_document" UNIQUE ("section_id", "document_id")', ddl["doc_section"]
        )
        for name in (
            "ck_document_status",
            "ck_document_deleted_pair",
            "ck_document_completed_pair",
            "ck_document_completed_required",
            "ck_document_draft_not_completed",
        ):
            self.assertIn(name, ddl["document"])
        self.assertIn('PRIMARY KEY ("document_id", "file_id")', ddl["document_file"])
        self.assertIn('PRIMARY KEY ("deviation_id", "staff_id")', ddl["deviation_checker"])

    def test_dev_stock_tables(self):
        # 개발·테스트 설정에서만 만드는 수불 임시 테이블(apps.devstock, D-059 Q1)
        tables = {row[0] for row in self.query("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({"items", "lots", "production_batches"} <= tables)
