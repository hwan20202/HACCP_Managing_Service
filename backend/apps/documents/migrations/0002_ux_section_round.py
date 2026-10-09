"""ERD v2 M7: 같은 반복 섹션 안에서 재측정이 아닌 행끼리 round 값 중복 금지.

JSON 식 + 부분 조건 인덱스라 ORM 대신 SQL로 만든다(SQLite 전용).
"""

from django.db import migrations

CREATE = """
CREATE UNIQUE INDEX ux_section_round ON doc_section (
  document_id, section_def, json_extract(values_json, '$.round')
) WHERE json_extract(values_json, '$.round') IS NOT NULL
    AND COALESCE(json_extract(values_json, '$.retake'), 0) = 0
"""
DROP = "DROP INDEX IF EXISTS ux_section_round"


class Migration(migrations.Migration):
    dependencies = [("documents", "0001_initial")]

    operations = [migrations.RunSQL(CREATE, DROP)]
