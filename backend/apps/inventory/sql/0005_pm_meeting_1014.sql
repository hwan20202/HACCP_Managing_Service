/* =========================================================
   HACCP 생산·수불 — 마이그레이션 005: 10/14 PM 미팅 반영 (SQLite 3.37+)
   전제: 0001~0004 적용 후. 규칙 S1~S6, 불변식 I1~I5 그대로.

   [결정 — 10/14 PM 미팅]
   C1. 정제수 같은 공정용수는 재고가 아님 → items.is_stock_managed = 0
       재고 비관리 품목은 LOT 을 만들지 않는다 (입고·기초재고·생산 투입 기록 없음, 트리거로 막음).
       BOM 에는 그대로 두고, 사용량은 생산일지(문서)에 적는다.
   D3. 과거 수불도 수정 가능해야 함 → 입고 수량 일부 정정 허용 (movements.correct_movement).
       문서 뷰 v_doc_incoming_lot 끝에 정정 반영 수량(net_quantity_e6) 추가 (계약: 추가만)
   근무조 폐지(B1·C2, 데이터팀 v6.1): production_batches.shift 는 v_doc_batch 계약 때문에 열만
       남긴다 (항상 NULL). 채번 규칙 변경은 migrations/0005 의 데이터 단계에서 한다.
   ========================================================= */

ALTER TABLE items ADD COLUMN is_stock_managed INTEGER NOT NULL DEFAULT 1 CHECK (is_stock_managed IN (0, 1));

/* 재고 비관리 품목(정제수 등)은 LOT 이 없다 */
CREATE TRIGGER trg_lots_stock_managed BEFORE INSERT ON lots
WHEN (SELECT is_stock_managed FROM items WHERE id = NEW.item_id) = 0
BEGIN
    SELECT RAISE(ABORT, 'item is not stock-managed: no lots (C1)');
END;

/* LOT 이 생긴 품목은 재고 비관리로 바꿀 수 없다 (재고가 허공에 남음) */
CREATE TRIGGER trg_items_stock_managed_locked BEFORE UPDATE OF is_stock_managed ON items
WHEN NEW.is_stock_managed = 0 AND OLD.is_stock_managed = 1
 AND EXISTS (SELECT 1 FROM lots WHERE item_id = OLD.id)
BEGIN
    SELECT RAISE(ABORT, 'item has lots: it cannot become non stock-managed');
END;

/* 문서 쪽 읽기 창구 (0001 과 같은 컬럼 + 끝에 net_quantity_e6)
   quantity_e6     = 입고 등록 수량 (그대로)
   net_quantity_e6 = 입고 수량 - 입고 정정·취소분. 취소된 입고는 0. 입고 건 없으면 NULL */
DROP VIEW v_doc_incoming_lot;

CREATE VIEW v_doc_incoming_lot AS
SELECT l.id                     AS lot_id,
       l.lot_number,
       l.lot_kind,
       i.id                     AS item_id,
       i.item_code,
       i.name                   AS item_name,
       i.item_type,
       it.name                  AS item_type_name,
       i.base_unit,
       i.origin_country,
       s.name                   AS supplier_name,
       r.supplier_lot_number,
       r.received_date,
       r.quantity_e6,
       l.manufactured_date,
       l.expiration_date,
       l.status                 AS lot_status,
       r.receipt_status,
       i.item_code || ' ' || i.name || ' / ' || l.lot_number
           || ' / ' || COALESCE(r.received_date, l.manufactured_date, '') AS subject_label,
       r.quantity_e6 - (SELECT COALESCE(SUM(c.quantity_e6), 0) FROM stock_movements c
                         WHERE c.corrects_movement_id = r.stock_movement_id) AS net_quantity_e6
FROM lots l
JOIN items i                     ON i.id = l.item_id
JOIN item_types it               ON it.code = i.item_type
LEFT JOIN incoming_receipts r    ON r.lot_id = l.id
LEFT JOIN suppliers s            ON s.id = r.supplier_id;
