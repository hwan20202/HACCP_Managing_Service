"""Optional reference EA and a narrowly scoped exception for unused item removal."""

from django.db import migrations, models

FORWARD = """
ALTER TABLE stock_movements ADD COLUMN ea_count INTEGER CHECK (ea_count IS NULL OR ea_count >= 0);
CREATE TABLE inventory_purge_scope (lot_id INTEGER PRIMARY KEY REFERENCES lots(id)) STRICT;
DROP TRIGGER trg_sm_no_delete;
CREATE TRIGGER trg_sm_no_delete BEFORE DELETE ON stock_movements
WHEN NOT EXISTS (SELECT 1 FROM inventory_purge_scope WHERE lot_id = OLD.lot_id)
 OR EXISTS (SELECT 1 FROM production_material_usages WHERE lot_id = OLD.lot_id)
 OR EXISTS (SELECT 1 FROM production_outputs WHERE lot_id = OLD.lot_id)
 OR EXISTS (SELECT 1 FROM holds WHERE lot_id = OLD.lot_id)
 OR EXISTS (SELECT 1 FROM stock_movements WHERE lot_id = OLD.lot_id
            AND movement_type_code NOT IN ('RECEIPT', 'CORRECTION_IN', 'CORRECTION_OUT'))
BEGIN
    SELECT RAISE(ABORT, 'stock_movements is append-only: only unused item removal is allowed');
END;
"""

REVERSE = """
DROP TRIGGER trg_sm_no_delete;
CREATE TRIGGER trg_sm_no_delete BEFORE DELETE ON stock_movements
BEGIN
    SELECT RAISE(ABORT, 'stock_movements is append-only: add a CORRECTION movement (I2)');
END;
DROP TABLE inventory_purge_scope;
ALTER TABLE stock_movements DROP COLUMN ea_count;
"""


class Migration(migrations.Migration):
    dependencies = [("inventory", "0007_expiration_status")]
    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunSQL(FORWARD, REVERSE)],
            state_operations=[migrations.AddField(
                model_name="stockmovement", name="ea_count",
                field=models.BigIntegerField(null=True, blank=True),
            )],
        ),
    ]
