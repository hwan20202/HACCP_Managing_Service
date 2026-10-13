"""APR-TC-051: 마이그레이션 결과가 ERD v4(approval_request, approval)와 같은지 확인한다."""

from django.db import connection
from django.test import TestCase

EXPECTED_COLUMNS = {
    "approval_request": {
        "request_id": True,
        "document_id": True,
        "attempt": True,
        "status": True,
        "document_version": True,
        "template_id": True,
        "subject": False,
        "work_date": True,
        "snapshot_json": True,
        "requested_by": True,
        "requested_at": True,
        "closed_at": False,
    },
    "approval": {
        "approval_id": True,
        "request_id": True,
        "slot_no": True,
        "label": False,
        "approver_id": True,
        "state": True,
        "comment": False,
        "decided_at": False,
    },
}
EXPECTED_FKS = {
    ("approval_request", "document_id"): "document",
    ("approval_request", "template_id"): "document_template",
    ("approval_request", "requested_by"): "staff",
    ("approval", "request_id"): "approval_request",
    ("approval", "approver_id"): "staff",
}


class SchemaMatchesErdV4Tests(TestCase):
    def query(self, sql):
        with connection.cursor() as cursor:
            cursor.execute(sql)
            return cursor.fetchall()

    def test_columns_and_not_null(self):
        for table, columns in EXPECTED_COLUMNS.items():
            with self.subTest(table):
                info = {
                    r[1]: bool(r[3]) or bool(r[5])
                    for r in self.query(f'PRAGMA table_info("{table}")')
                }
                self.assertEqual(info, columns)

    def test_foreign_keys(self):
        found = {
            (t, r[3]): r[2]
            for t in EXPECTED_COLUMNS
            for r in self.query(f'PRAGMA foreign_key_list("{t}")')
        }
        self.assertEqual(found, EXPECTED_FKS)

    def test_indexes(self):
        rows = dict(
            self.query(
                "SELECT name, sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"
                " AND tbl_name IN ('approval_request', 'approval')"
            )
        )
        self.assertEqual(set(rows), {"ux_request_open", "ix_approval_inbox"})
        self.assertIn("UNIQUE", rows["ux_request_open"])
        self.assertIn("\"status\" = 'in_progress'", rows["ux_request_open"])
        self.assertIn('("approver_id", "state")', rows["ix_approval_inbox"])

    def test_unique_and_check_constraints(self):
        ddl = dict(self.query("SELECT name, sql FROM sqlite_master WHERE type='table'"))
        self.assertIn('UNIQUE ("document_id", "attempt")', ddl["approval_request"])
        for name in ("ck_request_attempt", "ck_request_status", "ck_request_closed"):
            self.assertIn(name, ddl["approval_request"])
        self.assertIn('UNIQUE ("request_id", "slot_no")', ddl["approval"])
        self.assertIn('UNIQUE ("request_id", "approver_id")', ddl["approval"])
        for name in (
            "ck_approval_slot_no",
            "ck_approval_state",
            "ck_approval_decided",
            "ck_approval_reject_comment",
        ):
            self.assertIn(name, ddl["approval"])
