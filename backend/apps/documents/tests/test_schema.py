"""마이그레이션으로 만든 실제 스키마가 ERD v2와 같은지 확인한다(s3-erd-review 5장)."""

from django.db import connection
from django.test import TestCase

# ERD v2: 테이블 → {컬럼: NOT NULL 여부}
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
}
EXPECTED_FKS = {
    ("document", "template_id"): "document_template",
    ("document", "assignee_id"): "staff",
    ("document", "created_by"): "staff",
    ("document", "deleted_by"): "staff",
    ("doc_section", "document_id"): "document",
    ("doc_section", "recorded_by"): "staff",
}


class SchemaMatchesErdV2Tests(TestCase):
    def query(self, sql, params=()):
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall()

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
        for table, _ in EXPECTED_COLUMNS.items():
            for row in self.query(f'PRAGMA foreign_key_list("{table}")'):
                found[(table, row[3])] = row[2]
        self.assertEqual(found, EXPECTED_FKS)

    def test_indexes(self):
        rows = dict(
            self.query(
                "SELECT name, sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL "
                "AND tbl_name IN ('document', 'doc_section', 'document_template', 'staff')"
            )
        )
        # ERD v2의 명시적 인덱스만 있어야 한다(FK 자동 인덱스 없음).
        self.assertEqual(set(rows), {"ix_document_list", "ux_section_round"})
        self.assertIn('WHERE "deleted_at" IS NULL', rows["ix_document_list"])
        self.assertIn(
            "COALESCE(json_extract(values_json, '$.retake'), 0) = 0", rows["ux_section_round"]
        )

    def test_unique_and_check_constraints(self):
        ddl = dict(self.query("SELECT name, sql FROM sqlite_master WHERE type='table'"))
        self.assertIn('UNIQUE ("type_code", "version")', ddl["document_template"])
        self.assertIn('UNIQUE ("document_id", "section_def", "row_no")', ddl["doc_section"])
        self.assertIn("ck_document_status", ddl["document"])
        self.assertIn("ck_document_deleted_pair", ddl["document"])

    def test_out_of_scope_tables_are_not_created(self):
        tables = {row[0] for row in self.query("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertFalse({"approval", "file", "deviation_action"} & tables)
