"""Production journal sources, excluding the undecided blend ratio."""

from django.db import migrations, models

from apps.inventory.sql_runner import chain, recreate_from_sql_file, run_sql_file


def reverse_schema(_apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("DROP VIEW v_doc_batch_usage")
        cursor.execute("DROP VIEW v_doc_batch_bom_line")
        cursor.execute("DROP VIEW v_doc_batch")
        cursor.execute("ALTER TABLE items DROP COLUMN manufacturing_report_number")


class Migration(migrations.Migration):
    dependencies = [("inventory", "0008_movement_ea_and_unused_purge")]
    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(
                    run_sql_file("0009_document_production_sources.sql"),
                    chain(
                        reverse_schema,
                        recreate_from_sql_file("0006_mvp_bulk_scope.sql", ["v_doc_batch"]),
                    ),
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="item",
                    name="manufacturing_report_number",
                    field=models.TextField(null=True, blank=True),
                ),
            ],
        ),
    ]
