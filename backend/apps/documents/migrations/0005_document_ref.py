"""ERD v5 A9: document_ref — 업무 대상 참조.

DDL을 그대로 RunSQL로 만든다(ON DELETE·복합 FK·식 유니크 포함). Django 모델은 managed=False라서
Django가 이 테이블을 다시 만들지 않는다(P4-S3-Q6, check_django.py D2·D3). 구조 변경은 항상 RunSQL로.
수불 테이블(lots, production_batches, items)이 없어도 SQLite는 FK 정의를 허용하고 쓰기 때 검사한다.
기준: dev-notes/erd/v5/schema.sql, dev-notes/interfaces/document_ref.sql
"""

from django.db import migrations

CREATE = [
    """
CREATE TABLE document_ref (
  ref_id               INTEGER PRIMARY KEY AUTOINCREMENT,
  document_id          INTEGER NOT NULL REFERENCES document (document_id) ON DELETE CASCADE,
  section_id           INTEGER,
  lot_id               INTEGER REFERENCES lots (id) ON DELETE RESTRICT,
  production_batch_id  INTEGER REFERENCES production_batches (id) ON DELETE RESTRICT,
  item_id              INTEGER REFERENCES items (id) ON DELETE RESTRICT,
  process_code         TEXT,
  label                TEXT CHECK (label IS NULL OR length(label) <= 100),
  created_at           TEXT NOT NULL,
  FOREIGN KEY (section_id, document_id) REFERENCES doc_section (section_id, document_id)
    ON DELETE CASCADE,
  CHECK (lot_id IS NOT NULL OR production_batch_id IS NOT NULL OR item_id IS NOT NULL
         OR process_code IS NOT NULL)
)""",
    """CREATE UNIQUE INDEX ux_document_ref ON document_ref (
  document_id, COALESCE(section_id, 0), COALESCE(lot_id, 0), COALESCE(production_batch_id, 0),
  COALESCE(item_id, 0), COALESCE(process_code, ''))""",
    "CREATE INDEX ix_document_ref_lot ON document_ref (lot_id) WHERE lot_id IS NOT NULL",
    "CREATE INDEX ix_document_ref_batch ON document_ref (production_batch_id, process_code) "
    "WHERE production_batch_id IS NOT NULL",
    "CREATE INDEX ix_document_ref_item ON document_ref (item_id) WHERE item_id IS NOT NULL",
    "CREATE INDEX ix_document_ref_process ON document_ref (process_code) "
    "WHERE process_code IS NOT NULL",
    "CREATE INDEX ix_document_ref_label ON document_ref (label) WHERE label IS NOT NULL",
]
DROP = ["DROP TABLE IF EXISTS document_ref"]


# 0004에서 Django가 doc_section을 다시 만들면서(ux_section_document 추가) RunSQL로 만든
# ux_section_round(0002)가 사라진다. 같은 정의로 다시 만든다(S4 실제 DDL 대조에서 발견).
RESTORE_ROUND = """
CREATE UNIQUE INDEX IF NOT EXISTS ux_section_round ON doc_section (
  document_id, section_def, json_extract(values_json, '$.round')
) WHERE json_extract(values_json, '$.round') IS NOT NULL
    AND COALESCE(json_extract(values_json, '$.retake'), 0) = 0
"""


class Migration(migrations.Migration):
    dependencies = [("documents", "0004_v5_completed_record_key_file_deviation")]

    operations = [
        migrations.RunSQL(RESTORE_ROUND, migrations.RunSQL.noop),
        migrations.RunSQL(CREATE, DROP),
    ]
