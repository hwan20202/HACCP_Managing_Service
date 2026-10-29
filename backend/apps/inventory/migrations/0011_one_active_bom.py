"""At most one active BOM version per item, enforced by the database."""

from django.db import migrations

from apps.inventory.sql_runner import run_sql_file


def drop_index(_apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("DROP INDEX IF EXISTS ux_boms_one_active_per_item")


class Migration(migrations.Migration):
    dependencies = [("inventory", "0010_normalize_active_boms")]
    operations = [migrations.RunPython(run_sql_file("0011_one_active_bom.sql"), drop_index)]
