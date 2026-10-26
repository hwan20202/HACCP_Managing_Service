"""P15 S4b r1·r2 — 생산일지용 REQ 읽기(REQ-PLS-02)."""

from django.db import OperationalError
from django.test import TestCase

from apps.doc_requirements import errors, services, sources


class ProdLogSourceTests(TestCase):
    def test_missing_column_only_for_0009_queries(self):
        """r2 C1: 0009 계약 조회만 컬럼 없음 → SourceUnavailable, 다른 조회 오타는 그대로 오류."""
        select = (("no_such_col", "no_such_col"),)
        with self.assertRaises(errors.SourceUnavailable):
            sources._select(sources.BATCH_VIEW, select, " WHERE 1=0", [], contract_0009=True)
        with self.assertRaises(OperationalError):
            sources._select(sources.BATCH_VIEW, select, " WHERE 1=0", [])

    def test_batch_state_not_found(self):
        with self.assertRaises(errors.BatchNotFound):
            services.production_batch_state(987654)

    def test_batch_state_reads_base_columns_only(self):
        self.assertIsNone(sources.batch_state(987654))

    def test_state_with_lines_not_found(self):
        self.assertEqual(sources.batch_state_with_lines(987654), (None, []))
        with self.assertRaises(errors.BatchNotFound):
            services.production_batch_state(987654, with_lines=True)
