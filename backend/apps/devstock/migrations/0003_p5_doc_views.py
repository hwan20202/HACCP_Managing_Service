"""REQ가 읽는 뷰 두 개(ERD v5 V1·V2, erd/v5/devstock_p5.sql과 같은 DDL, D-069).

수불·생산이 같은 이름·컬럼의 실제 뷰를 주면 devstock을 빼는 것으로 교체한다(REQ 코드 변경 없음).
주의(REQ-S3 검토 3.1): 이 뷰가 읽는 devstock 테이블을 나중에 바꾸는 마이그레이션은
뷰 DROP → 테이블 변경 → 뷰 CREATE 순서로 쓴다(SQLite 테이블 재작성이 뷰 검사로 실패할 수 있음).
"""

from django.db import migrations

INCOMING_LOT_VIEW = """
CREATE VIEW v_doc_incoming_lot AS
SELECT
  l.id               AS lot_id,
  l.lot_number       AS lot_number,
  l.lot_kind         AS lot_kind,
  l.item_id          AS item_id,
  i.name             AS item_name,
  r.material_kind    AS material_kind,
  r.supplier_name    AS supplier_name,
  r.received_date    AS received_date,
  r.quantity         AS quantity,
  r.unit             AS unit,
  l.expiration_date  AS expiration_date,
  r.origin           AS origin
FROM lots l
JOIN items i ON i.id = l.item_id
LEFT JOIN dev_lot_receipts r ON r.lot_id = l.id
WHERE l.lot_kind <> 'INCOMING' OR r.lot_id IS NOT NULL
"""

BATCH_VIEW = """
CREATE VIEW v_doc_batch AS
SELECT
  b.id                 AS production_batch_id,
  b.batch_number       AS batch_number,
  b.item_id            AS item_id,
  i.name               AS item_name,
  b.process_type       AS process_type,
  b.status             AS status,
  b.manufactured_date  AS manufactured_date,
  p.quantity_kg        AS quantity_kg
FROM production_batches b
JOIN items i ON i.id = b.item_id
LEFT JOIN dev_batch_plans p ON p.production_batch_id = b.id
"""


class Migration(migrations.Migration):
    dependencies = [("devstock", "0002_p5_receipts_plans")]

    operations = [
        migrations.RunSQL(INCOMING_LOT_VIEW, "DROP VIEW v_doc_incoming_lot"),
        migrations.RunSQL(BATCH_VIEW, "DROP VIEW v_doc_batch"),
    ]
