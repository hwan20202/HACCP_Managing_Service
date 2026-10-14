/* =========================================================
   HACCP 생산·수불 — 마이그레이션 006: MVP 범위 = 입고 ~ 제조 벌크 산출 (SQLite 3.37+)
   전제: 0001~0005 적용 후. 규칙 S1~S6, 불변식 I1~I5 그대로.

   [결정 — 10/15]
   - 물류 소분·포장·출고와 포장배치는 구현 범위에서 제외. 새 포장배치는 만들지 않는다.
     production_batches.process_type 의 'PACKAGING' 값과 예전 행은 그대로 둔다 (조회·문서 참조용).
   - 한 제조배치의 산출은 제조 시작일로 채번한 LOT 하나. 산출을 나눠 입력해도 같은 LOT 에 더한다
     (production_outputs 는 여러 행, lot_id 는 하나). 0002 P6(배치 → 산출 LOT 1:N)을 대신한다.
   - 한 LOT 은 한 배치의 산출. 예전에 LOT 이 여러 개 생긴 배치는 그대로 두고 새 산출만 막는다.
   - v_doc_batch: output_lot_count 를 서로 다른 LOT 수로 (산출 행이 여러 개여도 LOT 은 하나),
     끝에 output_lot_number 추가 (계약: 열 삭제·이름 변경 없음, 추가만)
   ========================================================= */

CREATE TRIGGER trg_batches_no_packaging BEFORE INSERT ON production_batches
WHEN NEW.process_type = 'PACKAGING'
BEGIN
    SELECT RAISE(ABORT, 'packaging batches are out of the MVP scope (0006)');
END;

CREATE TRIGGER trg_batches_no_packaging_update BEFORE UPDATE OF process_type ON production_batches
WHEN NEW.process_type = 'PACKAGING' AND OLD.process_type <> 'PACKAGING'
BEGIN
    SELECT RAISE(ABORT, 'packaging batches are out of the MVP scope (0006)');
END;

CREATE TRIGGER trg_outputs_one_lot_per_batch BEFORE INSERT ON production_outputs
WHEN EXISTS (SELECT 1 FROM production_outputs WHERE batch_id = NEW.batch_id AND lot_id <> NEW.lot_id)
BEGIN
    SELECT RAISE(ABORT, 'a batch has one output lot: add output to that lot (0006)');
END;

CREATE TRIGGER trg_outputs_one_batch_per_lot BEFORE INSERT ON production_outputs
WHEN EXISTS (SELECT 1 FROM production_outputs WHERE lot_id = NEW.lot_id AND batch_id <> NEW.batch_id)
BEGIN
    SELECT RAISE(ABORT, 'an output lot belongs to one batch (0006)');
END;

DROP VIEW v_doc_batch;

/* 문서 쪽 읽기 창구: 생산일지·CCP 일지 자동 채움 (D2). 문서 쪽은 production_batch_id 로 조회
   계약: 컬럼 삭제·의미 변경 금지, 추가만 허용 */
CREATE VIEW v_doc_batch AS
SELECT b.id                        AS production_batch_id,
       b.batch_number,
       b.process_type,
       b.status,
       b.shift,
       i.id                        AS item_id,
       i.item_code,
       i.name                      AS item_name,
       i.item_type,
       i.base_unit,
       i.unit_weight_mg,           -- 기준단위 1개 무게(mg). base_unit 이 '개' 등일 때 kg 환산용 (문서 요청 V1)
       b.bom_id,
       bm.version                  AS bom_version,
       b.planned_date,
       b.planned_quantity_e6,
       b.manufactured_date,
       b.started_at,
       b.completed_at,
       (SELECT COALESCE(SUM(o.net_quantity_e6), 0) FROM v_batch_outputs o WHERE o.batch_id = b.id) AS output_quantity_e6,
       (SELECT COUNT(DISTINCT o.lot_id) FROM v_batch_outputs o WHERE o.batch_id = b.id)          AS output_lot_count,
       (SELECT COUNT(*) FROM v_batch_usages u WHERE u.batch_id = b.id)                            AS input_line_count,
       st.name                     AS staff_name,
       i.item_code || ' ' || i.name || ' / ' || b.batch_number
           || ' / ' || COALESCE(b.manufactured_date, b.planned_date, '') AS subject_label,
       (SELECT GROUP_CONCAT(DISTINCT o.lot_number) FROM v_batch_outputs o WHERE o.batch_id = b.id) AS output_lot_number   -- 0006: 배치의 산출 LOT 번호 (예전 다중 LOT 배치는 쉼표로 나열)
FROM production_batches b
JOIN items i  ON i.id = b.item_id
JOIN staff st ON st.id = b.staff_id
LEFT JOIN boms bm ON bm.id = b.bom_id;
