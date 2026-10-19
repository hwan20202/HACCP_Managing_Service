/* =========================================================
   HACCP 생산·수불 — 마이그레이션 007: LOT 소비기한 유무 (SQLite 3.37+)
   전제: 0001~0006 적용 후. 규칙 S1~S6, 불변식 I1~I5 그대로.

   [확정 — docs/inventory-erd-review-20261014.md]
   - 원료 LOT 채번: 소비기한이 있으면 약어 + 소비기한, 소비기한이 없으면 약어 + 입고일
   - 소비기한 유무를 별도 필드로 관리. 날짜가 비었다고 '없음'으로 보지 않는다
       KNOWN    소비기한 있음 (expiration_date 필수)
       NONE     소비기한 없음으로 확인 (날짜 없음)
       UNKNOWN  미확인 (날짜 없음) — 이관된 기존 LOT 등
   - 원료 입고는 KNOWN 또는 NONE 이어야 채번 기준이 정해진다 → 원료 입고 LOT 은 UNKNOWN 불가

   [이번 범위 (10/15 정리)]
   - 원료는 입고 건별 LOT 유지: 같은 기준일이 또 나오면 -2, -3 (입고 1건 = LOT 1개)
   - 상태 필드만 추가. 품목별 소비기한 정책 열과 새 사용 차단 정책은 제외
     (NONE·UNKNOWN LOT 은 이전처럼 사용 가능)
   ========================================================= */

ALTER TABLE lots ADD COLUMN expiration_status TEXT NOT NULL DEFAULT 'UNKNOWN'
    CHECK (expiration_status IN ('KNOWN', 'NONE', 'UNKNOWN'));

/* 기존 LOT: 날짜가 있으면 KNOWN, 없으면 UNKNOWN 그대로 (NONE 은 확인 후에만) */
UPDATE lots SET expiration_status = 'KNOWN' WHERE expiration_date IS NOT NULL;

/* KNOWN 이면 날짜가 있고, 날짜가 있으면 KNOWN */
CREATE TRIGGER trg_lots_expiration_status_insert BEFORE INSERT ON lots
WHEN (NEW.expiration_status = 'KNOWN') <> (NEW.expiration_date IS NOT NULL)
BEGIN
    SELECT RAISE(ABORT, 'expiration_status KNOWN needs expiration_date, and only KNOWN has one (0007)');
END;

CREATE TRIGGER trg_lots_expiration_status_update BEFORE UPDATE OF expiration_status, expiration_date ON lots
WHEN (NEW.expiration_status = 'KNOWN') <> (NEW.expiration_date IS NOT NULL)
BEGIN
    SELECT RAISE(ABORT, 'expiration_status KNOWN needs expiration_date, and only KNOWN has one (0007)');
END;

/* 원료 입고 LOT 은 소비기한 유무가 확인돼야 한다 (채번 기준) */
CREATE TRIGGER trg_receipts_raw_expiration_known BEFORE INSERT ON incoming_receipts
WHEN (SELECT i.item_type FROM lots l JOIN items i ON i.id = l.item_id WHERE l.id = NEW.lot_id) = 'RAW'
 AND (SELECT expiration_status FROM lots WHERE id = NEW.lot_id) = 'UNKNOWN'
BEGIN
    SELECT RAISE(ABORT, 'raw material receipt needs expiration_status KNOWN or NONE (0007)');
END;

/* 문서 쪽 읽기 창구 (0005 와 같은 컬럼 + 끝에 expiration_status) */
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
                         WHERE c.corrects_movement_id = r.stock_movement_id) AS net_quantity_e6,
       l.expiration_status      -- 0007: KNOWN 있음 / NONE 없음 / UNKNOWN 미확인
FROM lots l
JOIN items i                     ON i.id = l.item_id
JOIN item_types it               ON it.code = i.item_type
LEFT JOIN incoming_receipts r    ON r.lot_id = l.id
LEFT JOIN suppliers s            ON s.id = r.supplier_id;
