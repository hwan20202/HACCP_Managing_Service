/* =========================================================
   HACCP 생산·수불 — 마이그레이션 002 (SQLite 3.37+)
   상태: 10/11 ERD 협의 반영 확정본. apps/inventory/migrations/0002_production.py 가 실행
         (main merge 전까지만 이 파일 수정, 이후는 새 마이그레이션)
   전제: 0001_core.sql 적용 후. 0001 의 운영 규칙 S1~S6, 불변식 I1~I5 를 그대로 따른다.

   [범위]
   BOM(다단계), 제조배치, 자재 투입, 생산 산출, LOT 추적 뷰, 문서용 배치 뷰, v_stock_ledger 재정의

   [설계 근거 — 9/30·10/7 현업 미팅, 10/7 멘토링]
   P1. 생산지시가 아닌 제조배치 중심 (production_batches). 지시가 필요해지면 production_orders 를
       추가하고 배치에 order_id(NULL 허용) 를 붙인다 — 이름 변경 없이 확장
   P2. 사후 실적 입력이 많다 → 계획값은 NULL 허용, PLANNED 를 거치지 않고 바로 COMPLETED 등록 가능
   P3. BOM 표준 소요량 ≠ 실제 투입량 → BOM(boms/bom_lines) 과 실제 투입(production_material_usages) 분리
   P4. 다단계 BOM: 원료 → 반제품 → 완제품. 반제품도 판매·재투입 가능. 품목 유형으로 기능을 막지 않는다
       구성 품목에 자기 BOM 이 있으면 펼쳐서 다단계 처리 (BOM → BOM 직접 참조 컬럼 없음)
   P5. 포장도 배치로 처리: 제조 배치(원료 → 반제품), 포장 배치(반제품 + 포장재 → 완제품)
       벌크 보관 = 반제품 재고. 보관 박스·출고 단위가 달라도 LOT 은 그대로 (10/7)
   P6. 배치 → 산출 LOT 은 1:N 구조 (production_outputs). 1:1 이면 한 줄만 사용
   P7. 투입·산출은 기존 수불 이동(PRODUCTION_USE / PRODUCTION_OUTPUT) 을 가리킨다 (입고와 같은 방식)
       stock_movements 는 손대지 않는다. 투입·산출 행도 append-only, 잘못된 기록은 수불 정정(CORRECTION)
       → 실제 수량 = 원 수량 − 정정 합계 (뷰에서 계산)
   P8. 생산 LOT 번호 (BOM v4 멘토안, 10/12): 반제품 = LOT 약어 + 제조일 (BNY261007),
       완제품 = 제조일 + 근무조 (261011A, 완제품코드와 함께 읽음). 같은 날 같은 품목이 또 생기면 -2, -3
       → 완제품 LOT 은 배치의 shift 로 채번

   [10/11 ERD 협의로 정해진 것]
   D1. 문서 ↔ 배치 연결은 문서 쪽 document_ref.production_batch_id (+ process_code) 가 이 테이블을 FK 로 참조
       → 문서 앱 마이그레이션은 inventory 0002 에 의존. 배치 없는 독립 CCP 점검은 문서 쪽이 process_code 만으로 기록
   D2. 문서 쪽 읽기 창구 v_doc_batch: 컬럼 이름은 문서 쪽 요청에 맞춤 (production_batch_id, status)
       수량은 *_e6 + base_unit (S3). 완제품은 단위가 '개' 일 수 있어 kg 로 주지 않는다
       kg 환산이 필요하면 unit_weight_mg 사용 (수량 × unit_weight_mg ÷ 1,000,000 g, 10/13 문서 요청 V1)
   D3. 문서 쪽은 status = 'CANCELLED' 배치에 문서를 만들지 않는다

   [이 파일에 없는 것 — 스키마 영향이 없거나 이후 마이그레이션]
   - 배치 HOLD 와 산출 LOT 전파: 방식 결정 후 새 마이그레이션 (0001 lot_holds 재정의 포함).
     production_batches 에 컬럼이 필요하면 ADD COLUMN 으로 추가 가능
   - 포장 시 완제품 LOT 번호·소비기한 기준일, batch_number 형식: 채번 규칙·서비스 로직 (스키마 변경 없음)
   ========================================================= */


/* =========================================================
   1. BOM (P3, P4)
   ========================================================= */

CREATE TABLE boms (
    id                INTEGER PRIMARY KEY,
    item_id           INTEGER NOT NULL REFERENCES items(id),          -- 만드는 품목 (반제품·완제품)
    version           INTEGER NOT NULL CHECK (version > 0),
    base_quantity_e6  INTEGER NOT NULL CHECK (base_quantity_e6 > 0),  -- 이 수량(산출 품목 기준단위)을 만들 때의 소요량이 bom_lines
    effective_from    TEXT    NOT NULL CHECK (effective_from IS date(effective_from)),
    is_active         INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    notes             TEXT,
    created_by        INTEGER REFERENCES staff(id),
    created_at        TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE (item_id, version)
) STRICT;

CREATE INDEX ix_boms_item_active ON boms (item_id, is_active, effective_from);

CREATE TABLE bom_lines (
    id                 INTEGER PRIMARY KEY,
    bom_id             INTEGER NOT NULL REFERENCES boms(id),
    line_no            INTEGER NOT NULL CHECK (line_no > 0),
    component_item_id  INTEGER NOT NULL REFERENCES items(id),         -- 원료·반제품·포장재 (유형 제한 없음, P4)
    quantity_e6        INTEGER NOT NULL CHECK (quantity_e6 > 0),      -- base_quantity 당 표준 소요량 (구성 품목 기준단위)
    notes              TEXT,
    UNIQUE (bom_id, line_no),
    UNIQUE (bom_id, component_item_id)
) STRICT;

CREATE INDEX ix_bom_lines_component ON bom_lines (component_item_id);   -- "이 원료가 들어가는 BOM" 역조회

/* 자기 자신을 구성 품목으로 넣지 않는다. 여러 단계에 걸친 순환은 앱이 펼칠 때 검사 */
CREATE TRIGGER trg_bom_lines_no_self BEFORE INSERT ON bom_lines
WHEN NEW.component_item_id = (SELECT item_id FROM boms WHERE id = NEW.bom_id)
BEGIN
    SELECT RAISE(ABORT, 'a BOM cannot contain its own item');
END;

/* 배치가 사용한 BOM 은 고정: 구성을 바꾸려면 새 버전을 만든다 (배치가 어떤 기준으로 만들어졌는지 보존) */
CREATE TRIGGER trg_bom_lines_locked_update BEFORE UPDATE ON bom_lines
WHEN EXISTS (SELECT 1 FROM production_batches WHERE bom_id IN (OLD.bom_id, NEW.bom_id))
BEGIN
    SELECT RAISE(ABORT, 'BOM is used by a production batch: create a new version');
END;

CREATE TRIGGER trg_bom_lines_locked_insert BEFORE INSERT ON bom_lines
WHEN EXISTS (SELECT 1 FROM production_batches WHERE bom_id = NEW.bom_id)
BEGIN
    SELECT RAISE(ABORT, 'BOM is used by a production batch: create a new version');
END;

CREATE TRIGGER trg_bom_lines_locked_delete BEFORE DELETE ON bom_lines
WHEN EXISTS (SELECT 1 FROM production_batches WHERE bom_id = OLD.bom_id)
BEGIN
    SELECT RAISE(ABORT, 'BOM is used by a production batch: create a new version');
END;

CREATE TRIGGER trg_boms_locked BEFORE UPDATE OF item_id, base_quantity_e6 ON boms
WHEN EXISTS (SELECT 1 FROM production_batches WHERE bom_id = OLD.id)
BEGIN
    SELECT RAISE(ABORT, 'BOM is used by a production batch: create a new version');
END;


/* =========================================================
   2. 제조배치 (P1, P2, P5)
   ========================================================= */

CREATE TABLE production_batches (
    id                   INTEGER PRIMARY KEY,
    batch_number         TEXT    NOT NULL UNIQUE,                      -- 형식은 서비스가 채번 (미정)
    process_type         TEXT    NOT NULL CHECK (process_type IN ('MANUFACTURE', 'PACKAGING')),
    item_id              INTEGER NOT NULL REFERENCES items(id),        -- 산출 품목
    bom_id               INTEGER REFERENCES boms(id),                   -- 기준 BOM 버전 (없이도 기록 가능)
    status               TEXT    NOT NULL CHECK (status IN ('PLANNED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED')),
    planned_date         TEXT    CHECK (planned_date IS NULL OR planned_date IS date(planned_date)),
    planned_quantity_e6  INTEGER CHECK (planned_quantity_e6 IS NULL OR planned_quantity_e6 > 0),
    manufactured_date    TEXT    CHECK (manufactured_date IS NULL OR manufactured_date IS date(manufactured_date)),   -- 생산 LOT 채번 기준일
    shift                TEXT    CHECK (shift IS NULL OR shift IN ('A', 'B', 'C')),   -- 근무조 A 주간 / B 야간 / C 오후. 완제품 LOT 채번에 사용
    started_at           TEXT    CHECK (started_at   IS NULL OR started_at   IS datetime(started_at)),
    completed_at         TEXT    CHECK (completed_at IS NULL OR completed_at IS datetime(completed_at)),
    staff_id             INTEGER NOT NULL REFERENCES staff(id),        -- 작업 책임자 / 기록자
    notes                TEXT,
    cancelled_at         TEXT    CHECK (cancelled_at IS NULL OR cancelled_at IS datetime(cancelled_at)),
    cancel_reason        TEXT,
    created_at           TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at           TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    CHECK (status <> 'COMPLETED' OR (manufactured_date IS NOT NULL AND completed_at IS NOT NULL)),
    CHECK ((status = 'CANCELLED') = (cancelled_at IS NOT NULL)),
    CHECK (cancelled_at IS NULL OR cancel_reason IS NOT NULL)
) STRICT;

CREATE INDEX ix_batches_item_date ON production_batches (item_id, manufactured_date);
CREATE INDEX ix_batches_status    ON production_batches (status);

/* 배치의 BOM 은 같은 품목의 BOM 이어야 한다 */
CREATE TRIGGER trg_batches_bom_item_insert BEFORE INSERT ON production_batches
WHEN NEW.bom_id IS NOT NULL AND (SELECT item_id FROM boms WHERE id = NEW.bom_id) IS NOT NEW.item_id
BEGIN
    SELECT RAISE(ABORT, 'batch BOM must belong to the batch item');
END;

CREATE TRIGGER trg_batches_bom_item_update BEFORE UPDATE OF bom_id, item_id ON production_batches
WHEN NEW.bom_id IS NOT NULL AND (SELECT item_id FROM boms WHERE id = NEW.bom_id) IS NOT NEW.item_id
BEGIN
    SELECT RAISE(ABORT, 'batch BOM must belong to the batch item');
END;

/* 투입·산출이 생긴 배치는 품목을 바꿀 수 없다 */
CREATE TRIGGER trg_batches_item_locked BEFORE UPDATE OF item_id ON production_batches
WHEN NEW.item_id <> OLD.item_id
 AND (EXISTS (SELECT 1 FROM production_material_usages WHERE batch_id = OLD.id)
      OR EXISTS (SELECT 1 FROM production_outputs WHERE batch_id = OLD.id))
BEGIN
    SELECT RAISE(ABORT, 'batch item cannot change after inputs or outputs exist');
END;

CREATE TRIGGER trg_batches_updated_at AFTER UPDATE ON production_batches
WHEN NEW.updated_at = OLD.updated_at
BEGIN
    UPDATE production_batches SET updated_at = datetime('now', 'localtime') WHERE id = NEW.id;
END;

CREATE TRIGGER trg_batches_no_delete BEFORE DELETE ON production_batches
BEGIN
    SELECT RAISE(ABORT, 'production batches are not deleted: cancel instead');
END;


/* =========================================================
   3. 투입 / 산출 (P3, P6, P7)
   - 서비스 트랜잭션: stock_movements(PRODUCTION_USE|OUTPUT) INSERT → 이 테이블 INSERT
   - 재고 차감·증가는 0001 트리거(trg_sm_inventory) 가 처리. 재고 부족이면 이동 INSERT 가 실패
   ========================================================= */

CREATE TABLE production_material_usages (
    id                 INTEGER PRIMARY KEY,
    batch_id           INTEGER NOT NULL REFERENCES production_batches(id),
    lot_id             INTEGER NOT NULL REFERENCES lots(id),
    quantity_e6        INTEGER NOT NULL CHECK (quantity_e6 > 0),              -- 실제 투입량 (투입 LOT 품목 기준단위)
    stock_movement_id  INTEGER NOT NULL UNIQUE REFERENCES stock_movements(id),
    bom_line_id        INTEGER REFERENCES bom_lines(id),                       -- 대응하는 BOM 줄 (BOM 밖 투입이면 NULL)
    created_at         TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
) STRICT;

CREATE INDEX ix_usages_batch ON production_material_usages (batch_id);
CREATE INDEX ix_usages_lot   ON production_material_usages (lot_id);

CREATE TABLE production_outputs (
    id                 INTEGER PRIMARY KEY,
    batch_id           INTEGER NOT NULL REFERENCES production_batches(id),
    lot_id             INTEGER NOT NULL REFERENCES lots(id),
    quantity_e6        INTEGER NOT NULL CHECK (quantity_e6 > 0),              -- 산출량 (산출 품목 기준단위)
    stock_movement_id  INTEGER NOT NULL UNIQUE REFERENCES stock_movements(id),
    created_at         TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
) STRICT;

CREATE INDEX ix_outputs_batch ON production_outputs (batch_id);
CREATE INDEX ix_outputs_lot   ON production_outputs (lot_id);

/* 투입 행은 같은 LOT·같은 수량의 PRODUCTION_USE 이동을 가리켜야 한다 */
CREATE TRIGGER trg_usages_movement BEFORE INSERT ON production_material_usages
WHEN NOT EXISTS (
    SELECT 1 FROM stock_movements m
     WHERE m.id = NEW.stock_movement_id AND m.lot_id = NEW.lot_id
       AND m.quantity_e6 = NEW.quantity_e6 AND m.movement_type_code = 'PRODUCTION_USE')
BEGIN
    SELECT RAISE(ABORT, 'usage must point to a PRODUCTION_USE movement of the same lot and quantity');
END;

/* 산출 행은 같은 LOT·같은 수량의 PRODUCTION_OUTPUT 이동을 가리키고, 산출 LOT 은 생산 LOT·배치 품목이어야 한다 */
CREATE TRIGGER trg_outputs_movement BEFORE INSERT ON production_outputs
WHEN NOT EXISTS (
    SELECT 1 FROM stock_movements m
     WHERE m.id = NEW.stock_movement_id AND m.lot_id = NEW.lot_id
       AND m.quantity_e6 = NEW.quantity_e6 AND m.movement_type_code = 'PRODUCTION_OUTPUT')
BEGIN
    SELECT RAISE(ABORT, 'output must point to a PRODUCTION_OUTPUT movement of the same lot and quantity');
END;

CREATE TRIGGER trg_outputs_lot_item BEFORE INSERT ON production_outputs
WHEN (SELECT l.item_id FROM lots l WHERE l.id = NEW.lot_id)
         IS NOT (SELECT b.item_id FROM production_batches b WHERE b.id = NEW.batch_id)
  OR (SELECT l.lot_kind FROM lots l WHERE l.id = NEW.lot_id) <> 'PRODUCED'
BEGIN
    SELECT RAISE(ABORT, 'output lot must be a PRODUCED lot of the batch item');
END;

/* 취소된 배치에는 투입·산출을 추가하지 않는다 */
CREATE TRIGGER trg_usages_batch_open BEFORE INSERT ON production_material_usages
WHEN (SELECT status FROM production_batches WHERE id = NEW.batch_id) = 'CANCELLED'
BEGIN
    SELECT RAISE(ABORT, 'batch is cancelled');
END;

CREATE TRIGGER trg_outputs_batch_open BEFORE INSERT ON production_outputs
WHEN (SELECT status FROM production_batches WHERE id = NEW.batch_id) = 'CANCELLED'
BEGIN
    SELECT RAISE(ABORT, 'batch is cancelled');
END;

/* append-only (P7): 바로잡을 때는 연결된 수불 이동을 정정한다 */
CREATE TRIGGER trg_usages_no_update BEFORE UPDATE ON production_material_usages
BEGIN
    SELECT RAISE(ABORT, 'production_material_usages is append-only: correct the stock movement');
END;

CREATE TRIGGER trg_usages_no_delete BEFORE DELETE ON production_material_usages
BEGIN
    SELECT RAISE(ABORT, 'production_material_usages is append-only: correct the stock movement');
END;

CREATE TRIGGER trg_outputs_no_update BEFORE UPDATE ON production_outputs
BEGIN
    SELECT RAISE(ABORT, 'production_outputs is append-only: correct the stock movement');
END;

CREATE TRIGGER trg_outputs_no_delete BEFORE DELETE ON production_outputs
BEGIN
    SELECT RAISE(ABORT, 'production_outputs is append-only: correct the stock movement');
END;


/* =========================================================
   4. 뷰
   ========================================================= */

/* 투입·산출의 실제 수량 = 원 수량 − 정정 합계 (P7) */
CREATE VIEW v_batch_usages AS
SELECT u.id                AS usage_id,
       u.batch_id,
       u.lot_id,
       l.lot_number,
       l.item_id,
       u.bom_line_id,
       u.quantity_e6,
       u.quantity_e6 - COALESCE((SELECT SUM(c.quantity_e6) FROM stock_movements c
                                  WHERE c.corrects_movement_id = u.stock_movement_id), 0) AS net_quantity_e6,
       u.stock_movement_id
FROM production_material_usages u
JOIN lots l ON l.id = u.lot_id;

CREATE VIEW v_batch_outputs AS
SELECT o.id                AS output_id,
       o.batch_id,
       o.lot_id,
       l.lot_number,
       l.item_id,
       o.quantity_e6,
       o.quantity_e6 - COALESCE((SELECT SUM(c.quantity_e6) FROM stock_movements c
                                  WHERE c.corrects_movement_id = o.stock_movement_id), 0) AS net_quantity_e6,
       o.stock_movement_id
FROM production_outputs o
JOIN lots l ON l.id = o.lot_id;

/* LOT 추적 (정·역): source_lot 이 (여러 단계를 거쳐) derived_lot 에 들어갔다
     정추적  WHERE source_lot_id = ?   (이 원료 LOT 이 들어간 반제품·완제품)
     역추적  WHERE derived_lot_id = ?  (이 완제품 LOT 에 들어간 모든 LOT)
   정정으로 투입량이 0 이 된 연결은 제외. 순환 방지를 위해 20단계까지 */
CREATE VIEW v_lot_trace AS
WITH RECURSIVE
edges (from_lot_id, to_lot_id, batch_id) AS (
    SELECT u.lot_id, o.lot_id, u.batch_id
    FROM v_batch_usages u
    JOIN v_batch_outputs o ON o.batch_id = u.batch_id
    WHERE u.net_quantity_e6 > 0 AND o.net_quantity_e6 > 0
),
trace (source_lot_id, derived_lot_id, via_batch_id, depth) AS (
    SELECT from_lot_id, to_lot_id, batch_id, 1 FROM edges
    UNION
    SELECT t.source_lot_id, e.to_lot_id, e.batch_id, t.depth + 1
    FROM trace t
    JOIN edges e ON e.from_lot_id = t.derived_lot_id
    WHERE t.depth < 20
)
SELECT source_lot_id, derived_lot_id, MIN(depth) AS depth
FROM trace
GROUP BY source_lot_id, derived_lot_id;

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
       (SELECT COUNT(*) FROM v_batch_outputs o WHERE o.batch_id = b.id)                          AS output_lot_count,
       (SELECT COUNT(*) FROM v_batch_usages u WHERE u.batch_id = b.id)                            AS input_line_count,
       st.name                     AS staff_name,
       i.item_code || ' ' || i.name || ' / ' || b.batch_number
           || ' / ' || COALESCE(b.manufactured_date, b.planned_date, '') AS subject_label
FROM production_batches b
JOIN items i  ON i.id = b.item_id
JOIN staff st ON st.id = b.staff_id
LEFT JOIN boms bm ON bm.id = b.bom_id;

/* 원료수불대장 뷰 재정의: 0001 컬럼은 그대로 두고 끝에 추가만 (계약)
   되돌리기(0002 역마이그레이션)는 0001 정의로 다시 만든다 (migrations/0002_production.py)
   추가: lot_id, item_id, 원천(입고 건 / 배치) */
DROP VIEW v_stock_ledger;

CREATE VIEW v_stock_ledger AS
SELECT i.item_code,
       i.name                                   AS item_name,
       i.item_type,
       i.base_unit,
       l.lot_number,
       l.expiration_date,
       m.id                                     AS movement_id,
       m.occurred_at,
       t.code                                   AS movement_code,
       t.name                                   AS movement_name,
       m.quantity_e6 * t.direction              AS signed_quantity_e6,
       SUM(m.quantity_e6 * t.direction) OVER (
           PARTITION BY m.lot_id ORDER BY m.occurred_at, m.id
       )                                        AS lot_balance_e6,
       m.corrects_movement_id,
       m.reason,
       st.name                                  AS staff_name,
       l.id                                     AS lot_id,
       i.id                                     AS item_id,
       r.id                                     AS receipt_id,
       COALESCE(pu.batch_id, po.batch_id)       AS batch_id
FROM stock_movements m
JOIN lots l                 ON l.id = m.lot_id
JOIN items i                ON i.id = l.item_id
JOIN stock_movement_types t ON t.code = m.movement_type_code
JOIN staff st               ON st.id = m.staff_id
LEFT JOIN incoming_receipts r           ON r.stock_movement_id = m.id
LEFT JOIN production_material_usages pu ON pu.stock_movement_id = m.id
LEFT JOIN production_outputs po         ON po.stock_movement_id = m.id;
