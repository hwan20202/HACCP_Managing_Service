"""LOT 소비기한 유무 (docs/inventory-erd-review-20261014.md, 확정 범위).

- lots.expiration_status: KNOWN / NONE / UNKNOWN (+ 날짜와의 일관성 트리거)
- 기존 LOT: 날짜가 있으면 KNOWN, 없으면 UNKNOWN (NONE 으로 자동 이관하지 않음)
- 원료 입고 LOT 은 UNKNOWN 불가 (채번 기준: KNOWN 은 소비기한, NONE 은 입고일)
- v_doc_incoming_lot 끝에 expiration_status

Reversing drops the triggers and the column and restores 0005's v_doc_incoming_lot.
"""

from django.db import migrations

from apps.inventory.sql_runner import chain, recreate_from_sql_file, run_sql_file

SQL_FILE = "0007_expiration_status.sql"


def drop_schema(_apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("DROP VIEW IF EXISTS v_doc_incoming_lot")
        for name in (
            "trg_lots_expiration_status_insert",
            "trg_lots_expiration_status_update",
            "trg_receipts_raw_expiration_known",
        ):
            cursor.execute(f"DROP TRIGGER IF EXISTS {name}")
        cursor.execute("ALTER TABLE lots DROP COLUMN expiration_status")


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0006_mvp_bulk_scope"),
    ]

    operations = [
        migrations.RunPython(
            run_sql_file(SQL_FILE),
            chain(
                drop_schema,
                recreate_from_sql_file("0005_pm_meeting_1014.sql", ["v_doc_incoming_lot"]),
            ),
        ),
    ]
