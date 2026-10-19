"""10/14 PM 미팅 반영.

- items.is_stock_managed (정제수 같은 공정용수는 재고 아님, C1) + 트리거
- v_doc_incoming_lot 끝에 net_quantity_e6 (입고 수량 일부 정정 허용, D3)
- LOT 규칙: 근무조({shift}) 규칙을 끄고 같은 품목유형·적용일로 제조일 + 생산 순번 규칙을 넣음.
  구매 반제품(INCOMING SEMI) 규칙 추가 (D2, 형식은 가정). 기본 규칙이 없는 DB(seed 전)는 그대로
  두고 seed_master 가 새 기본값으로 넣는다.

Reversing drops the column, triggers and new rules, reactivates the shift rules and restores
0001's v_doc_incoming_lot.
"""

from django.db import migrations

from apps.inventory.sql_runner import chain, recreate_from_sql_file, run_sql_file

SQL_FILE = "0005_pm_meeting_1014.sql"
FINISHED_NOTE = "제조일 + 생산 순번 (근무조 폐지, 0005)"
INCOMING_SEMI_NOTE = "구매 반제품 LOT: 입고일 + 순번 (가정, 0005)"
PRODUCED_PATTERN = "{date:yyMMdd}{seq:A}"


def replace_rules(_apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        # Same kind, item type and effective date as each active shift rule, without the shift.
        cursor.execute(
            "INSERT INTO lot_number_rules (lot_kind, item_type, pattern, effective_from, notes) "
            "SELECT lot_kind, item_type, %s, effective_from, %s FROM lot_number_rules "
            "WHERE is_active = 1 AND pattern LIKE '%%{shift}%%'",
            [PRODUCED_PATTERN, FINISHED_NOTE],
        )
        cursor.execute(
            "UPDATE lot_number_rules SET is_active = 0 "
            "WHERE is_active = 1 AND pattern LIKE '%%{shift}%%'"
        )
        cursor.execute(
            "INSERT INTO lot_number_rules (lot_kind, item_type, pattern, effective_from, notes) "
            "SELECT 'INCOMING', 'SEMI', %s, (SELECT MIN(effective_from) FROM lot_number_rules "
            "WHERE lot_kind = 'INCOMING' AND is_active = 1), %s "
            "WHERE EXISTS (SELECT 1 FROM lot_number_rules "
            "WHERE lot_kind = 'INCOMING' AND is_active = 1) "
            "AND NOT EXISTS (SELECT 1 FROM lot_number_rules "
            "WHERE lot_kind = 'INCOMING' AND item_type = 'SEMI' AND is_active = 1)",
            [PRODUCED_PATTERN, INCOMING_SEMI_NOTE],
        )


def restore_rules(_apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "UPDATE lot_number_rules SET is_active = 1 WHERE is_active = 0 "
            "AND pattern LIKE '%%{shift}%%' AND EXISTS (SELECT 1 FROM lot_number_rules n "
            "WHERE n.notes = %s AND n.lot_kind = lot_number_rules.lot_kind "
            "AND n.item_type IS lot_number_rules.item_type)",
            [FINISHED_NOTE],
        )
        cursor.execute(
            "DELETE FROM lot_number_rules WHERE notes IN (%s, %s)",
            [FINISHED_NOTE, INCOMING_SEMI_NOTE],
        )


def drop_schema(_apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("DROP VIEW IF EXISTS v_doc_incoming_lot")
        cursor.execute("DROP TRIGGER IF EXISTS trg_lots_stock_managed")
        cursor.execute("DROP TRIGGER IF EXISTS trg_items_stock_managed_locked")
        cursor.execute("ALTER TABLE items DROP COLUMN is_stock_managed")


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0004_bomlinealternative"),
    ]

    operations = [
        migrations.RunPython(
            run_sql_file(SQL_FILE),
            chain(drop_schema, recreate_from_sql_file("0001_core.sql", ["v_doc_incoming_lot"])),
        ),
        migrations.RunPython(replace_rules, restore_rules),
    ]
