"""MVP 범위 = 입고 ~ 제조 벌크 산출 (10/15).

- 새 포장배치 금지 (예전 행·'PACKAGING' 값은 유지)
- 한 제조배치 = 산출 LOT 하나, 한 LOT = 한 배치 (새 산출 행에만 적용, 예전 기록은 그대로)
- v_doc_batch: output_lot_count = 서로 다른 LOT 수, 끝에 output_lot_number

Reversing drops the triggers and restores 0002's v_doc_batch.
"""

from django.db import migrations

from apps.inventory.sql_runner import (
    chain,
    drop_sql_file_objects,
    recreate_from_sql_file,
    run_sql_file,
)

SQL_FILE = "0006_mvp_bulk_scope.sql"


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0005_pm_meeting_1014"),
    ]

    operations = [
        migrations.RunPython(
            run_sql_file(SQL_FILE),
            chain(
                drop_sql_file_objects(SQL_FILE),
                recreate_from_sql_file("0002_production.sql", ["v_doc_batch"]),
            ),
        ),
    ]
