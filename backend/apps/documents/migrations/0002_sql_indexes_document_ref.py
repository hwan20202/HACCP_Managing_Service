"""ORM으로 만들 수 없는 문서 영역 DDL(C2 재생성, D-128 — 이전 0002·0005를 합침).

1. ux_section_round (ERD v2 M7): 같은 반복 섹션 안에서 재측정이 아닌 행끼리 round 값 중복 금지.
   JSON 식 + 부분 조건 인덱스라 SQL로 만든다(SQLite 전용).
2. document_ref (ERD v5 A9, v7): 업무 대상 참조. DDL을 그대로 RunSQL로 만든다
   (ON DELETE·복합 FK·식 유니크). Django 모델은 managed=False라서 Django가 이 테이블을
   다시 만들지 않는다(P4-S3-Q6). 구조 변경은 항상 RunSQL로.
   lots·production_batches·items는 수불 앱 테이블이다(inventory 0001·0002, 0001_initial이 의존).
기준: dev-notes/interfaces/erd-v7-handoff.md 부록 A
"""

from django.db import migrations

ROUND = """
CREATE UNIQUE INDEX ux_section_round ON doc_section (
  document_id, section_def, json_extract(values_json, '$.round')
) WHERE json_extract(values_json, '$.round') IS NOT NULL
    AND COALESCE(json_extract(values_json, '$.retake'), 0) = 0
"""
DROP_ROUND = "DROP INDEX IF EXISTS ux_section_round"

DOCUMENT_REF = [
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
DROP_DOCUMENT_REF = ["DROP TABLE IF EXISTS document_ref"]


class Migration(migrations.Migration):
    dependencies = [("documents", "0001_initial")]

    operations = [
        migrations.RunSQL(ROUND, DROP_ROUND),
        migrations.RunSQL(DOCUMENT_REF, DROP_DOCUMENT_REF),
    ]
