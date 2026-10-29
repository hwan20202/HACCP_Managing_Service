"""Keep the existing default recipe when legacy saves left multiple versions active."""

import datetime
import json

from django.db import migrations


def normalize_active_boms(_apps, schema_editor):
    # The SQL-owned unmanaged models omit foreign keys in historical Django state.
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
    today = now.date().isoformat()
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT item_id FROM boms WHERE is_active = 1 GROUP BY item_id HAVING COUNT(*) > 1"
        )
        duplicates = [row[0] for row in cursor.fetchall()]
        for item_id in duplicates:
            cursor.execute(
                "SELECT id, version, effective_from, created_by FROM boms "
                "WHERE item_id = %s AND is_active = 1 "
                "ORDER BY effective_from DESC, version DESC, id DESC",
                [item_id],
            )
            versions = cursor.fetchall()
            eligible = [bom for bom in versions if bom[2] <= today]
            # Match production._default_bom today. Future-only recipes keep the
            # nearest applicable date, then its highest version.
            earliest = min(bom[2] for bom in versions)
            keep = eligible[0] if eligible else next(bom for bom in versions if bom[2] == earliest)
            for bom in versions:
                if bom[0] == keep[0]:
                    continue
                actor = keep[3] or bom[3]
                if actor is None:
                    cursor.execute("SELECT MIN(id) FROM staff")
                    actor = cursor.fetchone()[0]
                if actor is None:
                    raise RuntimeError("중복 활성 BOM 정리 이력을 기록할 담당자가 없습니다.")
                cursor.execute("UPDATE boms SET is_active = 0 WHERE id = %s", [bom[0]])
                cursor.execute(
                    "INSERT INTO audit_logs "
                    "(table_name, record_id, action, before_json, after_json, "
                    "reason, staff_id, occurred_at) "
                    "VALUES ('boms', %s, 'UPDATE', %s, %s, %s, %s, %s)",
                    [
                        str(bom[0]),
                        json.dumps({"version": bom[1], "is_active": True}),
                        json.dumps({"version": bom[1], "is_active": False}),
                        f"기존 중복 활성 정리: 기본 선택 v{keep[1]} 유지 (0010)",
                        actor,
                        now.strftime("%Y-%m-%d %H:%M:%S"),
                    ],
                )


class Migration(migrations.Migration):
    dependencies = [("inventory", "0009_document_production_sources")]
    operations = [migrations.RunPython(normalize_active_boms, migrations.RunPython.noop)]
