"""Production schema (sql/0002_production.sql) on top of 0001: triggers, views, trace.

The two SQL files are applied to a plain in-memory SQLite connection, so these tests exercise
the schema itself without Django. Django's test database also runs both files through the
migrations (see tests.SchemaTests).
"""

import sqlite3

from django.test import SimpleTestCase

from .sql_runner import read_sql, split_statements

E6 = 1_000_000


class ProductionSchemaTests(SimpleTestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:", isolation_level=None)
        self.db.execute("PRAGMA foreign_keys = ON")
        for sql in [read_sql("0001_core.sql"), read_sql("0002_production.sql")]:
            for statement in split_statements(sql):
                self.db.execute(statement)
        self.seed()

    def tearDown(self):
        self.db.close()

    def one(self, sql, *params):
        return self.db.execute(sql, params).fetchone()

    def insert(self, sql, *params):
        return self.db.execute(sql, params).lastrowid

    def lot(self, item, number, kind):
        return self.insert(
            "INSERT INTO lots (lot_number, item_id, lot_kind, status)"
            " VALUES (?, ?, ?, 'AVAILABLE')",
            number,
            item,
            kind,
        )

    def move(self, lot, code, quantity, key, corrects=None, reason=None):
        return self.insert(
            "INSERT INTO stock_movements (lot_id, movement_type_code, quantity_e6, staff_id,"
            " occurred_at, idempotency_key, corrects_movement_id, reason)"
            " VALUES (?, ?, ?, 1, '2026-10-09 09:00:00', ?, ?, ?)",
            lot,
            code,
            quantity * E6,
            key,
            corrects,
            reason,
        )

    def seed(self):
        self.insert("INSERT INTO staff (staff_code, name) VALUES ('S1', '가상직원')")
        items = [
            ("RAW", "1000001", "가상원료", "kg"),
            ("PACKAGING", "2000001", "가상파우치", "장"),
            ("SEMI", "3000001", "가상환", "개"),
            ("FINISHED", "4000001", "가상완제품", "개"),
        ]
        self.raw, self.pouch, self.semi, self.fin = [
            self.insert(
                "INSERT INTO items (item_type, item_code, name, base_unit) VALUES (?, ?, ?, ?)",
                *row,
            )
            for row in items
        ]
        self.raw_lot = self.lot(self.raw, "1000001-261001A", "INCOMING")
        self.move(self.raw_lot, "RECEIPT", 100, "r1")
        self.pouch_lot = self.lot(self.pouch, "2000001-261001A", "INCOMING")
        self.move(self.pouch_lot, "RECEIPT", 1000, "r2")
        self.semi_bom = self.insert(
            "INSERT INTO boms (item_id, version, base_quantity_e6, effective_from)"
            " VALUES (?, 1, ?, '2026-01-01')",
            self.semi,
            10000 * E6,
        )
        self.insert(
            "INSERT INTO bom_lines (bom_id, line_no, component_item_id, quantity_e6)"
            " VALUES (?, 1, ?, ?)",
            self.semi_bom,
            self.raw,
            40 * E6,
        )

    def batch(self, number, item, process, bom=None, status="COMPLETED"):
        return self.insert(
            "INSERT INTO production_batches (batch_number, process_type, item_id, bom_id, status,"
            " manufactured_date, completed_at, staff_id)"
            " VALUES (?, ?, ?, ?, ?, '2026-10-09', '2026-10-09 18:00:00', 1)",
            number,
            process,
            item,
            bom,
            status,
        )

    def use(self, batch, lot, quantity, key):
        movement = self.move(lot, "PRODUCTION_USE", quantity, key)
        self.insert(
            "INSERT INTO production_material_usages"
            " (batch_id, lot_id, quantity_e6, stock_movement_id) VALUES (?, ?, ?, ?)",
            batch,
            lot,
            quantity * E6,
            movement,
        )
        return movement

    def output(self, batch, item, number, quantity, key):
        lot = self.lot(item, number, "PRODUCED")
        movement = self.move(lot, "PRODUCTION_OUTPUT", quantity, key)
        self.insert(
            "INSERT INTO production_outputs (batch_id, lot_id, quantity_e6, stock_movement_id)"
            " VALUES (?, ?, ?, ?)",
            batch,
            lot,
            quantity * E6,
            movement,
        )
        return lot

    def make_chain(self):
        """원료 40kg → 제조 배치 → 환 10,000개 → 포장 배치 (환 + 파우치) → 완제품 2 LOT."""
        self.mfg = self.batch("B-3000001-261009A", self.semi, "MANUFACTURE", self.semi_bom)
        self.use(self.mfg, self.raw_lot, 40, "u1")
        self.semi_lot = self.output(self.mfg, self.semi, "3000001-261009A", 10000, "o1")
        self.pack = self.batch("B-4000001-261009A", self.fin, "PACKAGING")
        self.use(self.pack, self.semi_lot, 10000, "u2")
        self.use(self.pack, self.pouch_lot, 200, "u3")
        self.fin_a = self.output(self.pack, self.fin, "4000001-261009A", 100, "o2")
        self.fin_b = self.output(self.pack, self.fin, "4000001-261009B", 100, "o3")

    def test_stock_follows_usage_and_output(self):
        self.make_chain()
        stock = dict(self.db.execute("SELECT lot_id, quantity_e6 FROM inventory").fetchall())
        self.assertEqual(stock[self.raw_lot], 60 * E6)
        self.assertEqual(stock[self.semi_lot], 0)
        self.assertEqual(stock[self.fin_a], 100 * E6)
        self.assertEqual(self.db.execute("SELECT * FROM v_inventory_mismatch").fetchall(), [])

    def test_trace_forward_and_backward(self):
        self.make_chain()
        forward = self.db.execute(
            "SELECT derived_lot_id, depth FROM v_lot_trace WHERE source_lot_id = ? ORDER BY 1",
            (self.raw_lot,),
        ).fetchall()
        self.assertEqual(forward, [(self.semi_lot, 1), (self.fin_a, 2), (self.fin_b, 2)])
        backward = {
            row[0]
            for row in self.db.execute(
                "SELECT source_lot_id FROM v_lot_trace WHERE derived_lot_id = ?", (self.fin_b,)
            )
        }
        self.assertEqual(backward, {self.raw_lot, self.semi_lot, self.pouch_lot})

    def test_corrected_usage_is_netted_and_leaves_the_trace(self):
        self.make_chain()
        mistake = self.use(self.pack, self.raw_lot, 5, "u4")  # 잘못 투입
        self.move(self.raw_lot, "CORRECTION_IN", 5, "c1", corrects=mistake, reason="오입력")
        net = self.one(
            "SELECT net_quantity_e6 FROM v_batch_usages WHERE stock_movement_id = ?", mistake
        )
        self.assertEqual(net, (0,))
        depth = self.one(
            "SELECT depth FROM v_lot_trace WHERE source_lot_id = ? AND derived_lot_id = ?",
            self.raw_lot,
            self.fin_a,
        )
        self.assertEqual(depth, (2,))  # still reached through the semi LOT, not directly

    def test_insufficient_stock_blocks_usage(self):
        batch = self.batch("B-X", self.semi, "MANUFACTURE")
        with self.assertRaises(sqlite3.IntegrityError):
            self.use(batch, self.raw_lot, 101, "u1")

    def test_integrity_triggers(self):
        self.make_chain()
        checks = [
            # usage pointing at a movement of another type
            (
                "INSERT INTO production_material_usages (batch_id, lot_id, quantity_e6,"
                " stock_movement_id) VALUES (?, ?, ?, 1)",
                (self.mfg, self.raw_lot, 100 * E6),
            ),
            # append-only
            ("UPDATE production_material_usages SET quantity_e6 = 1", ()),
            ("DELETE FROM production_outputs", ()),
            ("DELETE FROM production_batches", ()),
            # BOM used by a batch is locked
            ("UPDATE bom_lines SET quantity_e6 = 1", ()),
            (
                "INSERT INTO bom_lines (bom_id, line_no, component_item_id, quantity_e6)"
                " VALUES (?, 2, ?, 1)",
                (self.semi_bom, self.pouch),
            ),
            # BOM of another item
            (
                "INSERT INTO production_batches (batch_number, process_type, item_id, bom_id,"
                " status, staff_id) VALUES ('B-Y', 'MANUFACTURE', ?, ?, 'PLANNED', 1)",
                (self.fin, self.semi_bom),
            ),
            # completed without a manufacturing date
            (
                "INSERT INTO production_batches (batch_number, process_type, item_id, status,"
                " staff_id) VALUES ('B-Z', 'MANUFACTURE', ?, 'COMPLETED', 1)",
                (self.semi,),
            ),
        ]
        for sql, params in checks:
            with self.subTest(sql=sql[:60]), self.assertRaises(sqlite3.IntegrityError):
                self.db.execute(sql, params)

    def test_output_lot_must_match_batch_item(self):
        batch = self.batch("B-W", self.semi, "MANUFACTURE")
        lot = self.lot(self.fin, "WRONG", "PRODUCED")
        movement = self.move(lot, "PRODUCTION_OUTPUT", 1, "o9")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(
                "INSERT INTO production_outputs (batch_id, lot_id, quantity_e6, stock_movement_id)"
                " VALUES (?, ?, ?, ?)",
                (batch, lot, E6, movement),
            )

    def test_bom_cannot_contain_itself(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(
                "INSERT INTO bom_lines (bom_id, line_no, component_item_id, quantity_e6)"
                " VALUES (?, 9, ?, 1)",
                (self.semi_bom, self.semi),
            )

    def test_doc_batch_and_ledger_views(self):
        self.make_chain()
        row = self.one(
            "SELECT batch_number, process_type, output_quantity_e6, output_lot_count,"
            " input_line_count, subject_label FROM v_doc_batch WHERE production_batch_id = ?",
            self.pack,
        )
        self.assertEqual(
            row,
            (
                "B-4000001-261009A",
                "PACKAGING",
                200 * E6,
                2,
                2,
                "4000001 가상완제품 / B-4000001-261009A / 2026-10-09",
            ),
        )
        self.assertEqual(
            self.one(
                "SELECT status, base_unit FROM v_doc_batch WHERE production_batch_id = ?",
                self.pack,
            ),
            ("COMPLETED", "개"),
        )
        ledger = self.db.execute(
            "SELECT movement_code, lot_id, item_id, batch_id FROM v_stock_ledger"
            " WHERE lot_id = ? ORDER BY movement_id",
            (self.raw_lot,),
        ).fetchall()
        self.assertEqual(
            ledger,
            [
                ("RECEIPT", self.raw_lot, self.raw, None),
                ("PRODUCTION_USE", self.raw_lot, self.raw, self.mfg),
            ],
        )
