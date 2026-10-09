/* =========================================================
   HACCP 생산·수불 코어 — 마이그레이션 001 (SQLite 3.37+)
   범위: 이번 주 개발 (원료 입고 · 입고 판정 반영 · 원료수불대장)
   설계 원본: haccp_production_v4.sql (MySQL 문법 설계본). 운영 기준은 이 파일

   [이 파일에 없는 것 — 다음 마이그레이션]
   BOM, 생산지시, 자재 투입, 설비·CCP, 수율·추적 뷰

   [SQLite 운영 규칙]
   S1. 연결할 때마다  PRAGMA foreign_keys = ON;  (연결 단위 설정. 안 하면 FK 무시됨)
       최초 1회         PRAGMA journal_mode = WAL;
   S2. 모든 테이블 STRICT. 타입 위반은 INSERT 시점에 오류.
   S3. 수량은 정수 *_e6 = 기준단위 × 1,000,000 (SQLite 에는 정확한 DECIMAL 이 없음)
         50 kg     → 50000000
         0.25 kg   → 250000
         12354 개  → 12354000000
       화면·문서 스냅샷에서는 / 1,000,000 해서 표시. 계산은 정수로.
   S4. 일자 'YYYY-MM-DD', 일시 'YYYY-MM-DD HH:MM:SS' (KST, 타임존 표기 없음). CHECK 로 형식 강제.
   S5. 쓰기 트랜잭션은 BEGIN IMMEDIATE (채번·재고 갱신 경합 방지. MySQL 의 FOR UPDATE 대체)
   S6. 스키마 변경은 테이블 재생성이 필요하므로, 이 파일의 테이블은 고정을 전제로 한다.

   [불변식 — DB 가 강제]
   I1. 수량은 양수. 방향은 이동 유형이 가진다.
   I2. stock_movements 는 append-only           → UPDATE / DELETE 트리거로 차단
   I3. inventory = stock_movements 합계         → 이동 INSERT 트리거가 자동 갱신. 앱은 inventory 를 직접 쓰지 않는다
                                                  음수가 되면 이동 INSERT 자체가 실패
   I4. LOT 이 있는 품목의 item_type 변경 금지   → 트리거
   I5. 미해제 HOLD 가 있는 LOT 은 사용 불가     → v_lot_availability (앱이 확인)

   [문서 도메인 접점 — 문서 기준으로 합의]
   C1. 이벤트 저장: 문서 도메인의 domain_event 테이블 (문서 마이그레이션이 생성)
         생산 이벤트는 document_id = NULL, 상세는 payload_json
         payload_json 공통: {"event_version":1,"subject_type":"LOT","subject_id":"<lots.id>", ...}
         생산 쪽은 domain_event.processed_at 을 건드리지 않는다 (문서 처리기 전용)
         생산 쪽 수신 처리 기록은 domain_event_inbox
   C2. subject_type = 문서 기준 값 (LOT / CCP_POINT / DATE)
         입고 육안검사·증빙  LOT  subject_id = 입고 LOT id
         → 입고 건 1 = LOT 1 (incoming_receipts.lot_id UNIQUE). P1 은 "입고일 기준"으로 진행
   C3. 이번 주 이벤트
         INCOMING_RECEIVED (생산 → 문서)  입고 등록 트랜잭션 안에서 domain_event INSERT
           payload: event_version, subject_type, subject_id, lot_id, lot_number, item_code, item_name,
                    item_type, supplier_name, supplier_lot_number, received_date,
                    quantity_e6, unit, manufactured_date, expiration_date
         INCOMING_RECEIPT_CANCELLED (생산 → 문서)  입고 취소 시
           payload: event_version, subject_type, subject_id, lot_id, reason
         INCOMING_JUDGED (문서 → 생산)  육안검사 제출 시 [합의 필요: 제출 시점]
           payload: event_version, subject_type, subject_id, document_id, result(PASS/FAIL/CONDITIONAL),
                    judged_by, judged_at, action_id(nullable), reason
           생산 처리: PASS → AVAILABLE / FAIL → REJECTED / CONDITIONAL → AVAILABLE + lot_holds
   C4. 문서 쪽 읽기 창구: v_doc_incoming_lot (입고 문서 자동 채움)
       원료수불대장은 생산 쪽 조회·출력 화면 (v_stock_ledger). 결재가 필요해지면 문서가 이 뷰를 스냅샷
   C5. staff 는 생산 쪽이 소유. 문서 쪽 assignee_id / recorded_by / approver_id 가 참조

   [Django 적용 메모]
   - 이 파일은 apps/inventory/migrations/0001_initial.py 가 문장 단위로 실행한다.
   - PRAGMA 문은 마이그레이션 트랜잭션 안에서 효과가 없으므로 실행기가 건너뛴다.
     S1(foreign_keys) 은 Django SQLite 백엔드가 연결마다 켜고, WAL 과 S5 는 settings 의 OPTIONS 가 처리한다.
   ========================================================= */

PRAGMA foreign_keys = ON;


/* =========================================================
   1. 참조 코드
   ========================================================= */

CREATE TABLE item_types (
    code        TEXT    NOT NULL PRIMARY KEY,
    name        TEXT    NOT NULL,
    code_prefix TEXT,
    sort_order  INTEGER NOT NULL DEFAULT 0
) STRICT;

INSERT INTO item_types (code, name, code_prefix, sort_order) VALUES
 ('RAW',       '원료',   '1', 1),
 ('PACKAGING', '포장재', '2', 2),
 ('SEMI',      '반제품', '3', 3),
 ('FINISHED',  '완제품', '4', 4);

CREATE TABLE stock_movement_types (
    code       TEXT    NOT NULL PRIMARY KEY,
    name       TEXT    NOT NULL,
    direction  INTEGER NOT NULL CHECK (direction IN (1, -1))
) STRICT;

INSERT INTO stock_movement_types (code, name, direction) VALUES
 ('RECEIPT',            '입고',                    1),
 ('PRODUCTION_USE',     '생산 투입',               -1),
 ('PRODUCTION_OUTPUT',  '생산 산출',                1),
 ('SHIPMENT',           '출하',                    -1),
 ('CUSTOMER_RETURN',    '고객 반품 입고',           1),
 ('RETURN_TO_SUPPLIER', '공급처 반품',              -1),
 ('DISPOSAL',           '폐기',                    -1),
 ('ADJUST_IN',          '재고조정(증가)',            1),
 ('ADJUST_OUT',         '재고조정(감소)',           -1),
 ('OPENING_BALANCE',    '기초재고 이관',             1),
 ('CORRECTION_IN',      '정정(증가)',               1),
 ('CORRECTION_OUT',     '정정(감소)',              -1);

CREATE TABLE hold_source_types (
    code               TEXT    NOT NULL PRIMARY KEY,
    name               TEXT    NOT NULL,
    requires_evidence  INTEGER NOT NULL DEFAULT 1 CHECK (requires_evidence IN (0, 1))
) STRICT;

INSERT INTO hold_source_types (code, name, requires_evidence) VALUES
 ('CCP',                 'CCP 이탈',      1),
 ('INCOMING_INSPECTION', '입고 검사',     1),
 ('FINISHED_INSPECTION', '완제품 실험',   1),
 ('PROPAGATED',          '상위 LOT 전파', 0),
 ('MANUAL',              '수동',         0);

CREATE TABLE hold_dispositions (
    code              TEXT NOT NULL PRIMARY KEY,
    name              TEXT NOT NULL,
    lot_status_after  TEXT
) STRICT;

INSERT INTO hold_dispositions (code, name, lot_status_after) VALUES
 ('RELEASE', '해제(정상 사용)', NULL),
 ('REWORK',  '재작업',         NULL),
 ('RETURN',  '반품',           'DISPOSED'),
 ('DISPOSE', '폐기',           'DISPOSED');


/* =========================================================
   2. 기준정보
   ========================================================= */

CREATE TABLE staff (
    id          INTEGER PRIMARY KEY,
    staff_code  TEXT    NOT NULL UNIQUE,
    name        TEXT    NOT NULL,
    is_active   INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
) STRICT;

CREATE TABLE suppliers (
    id             INTEGER PRIMARY KEY,
    supplier_code  TEXT    NOT NULL UNIQUE,
    name           TEXT    NOT NULL,
    is_active      INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at     TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
) STRICT;

CREATE TABLE items (
    id                INTEGER PRIMARY KEY,
    item_type         TEXT    NOT NULL REFERENCES item_types(code),
    item_code         TEXT    NOT NULL UNIQUE,          -- 1·2·3·4코드
    short_code        TEXT    UNIQUE,                   -- 약어(ABY 등). 용도 미결
    name              TEXT    NOT NULL,
    base_unit         TEXT    NOT NULL,                 -- kg / g / 개 / 장 …
    unit_weight_mg    INTEGER CHECK (unit_weight_mg IS NULL OR unit_weight_mg > 0),   -- 1 base_unit 표준 중량. 환 4g = 4000
    shelf_life_days   INTEGER CHECK (shelf_life_days IS NULL OR shelf_life_days > 0),
    origin_country    TEXT,
    food_type         TEXT,
    minimum_stock_e6  INTEGER NOT NULL DEFAULT 0 CHECK (minimum_stock_e6 >= 0),
    is_active         INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at        TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
) STRICT;

CREATE INDEX ix_items_type ON items (item_type);


/* =========================================================
   3. LOT
   ========================================================= */

CREATE TABLE lots (
    id                 INTEGER PRIMARY KEY,
    lot_number         TEXT    NOT NULL,
    item_id            INTEGER NOT NULL REFERENCES items(id),
    lot_kind           TEXT    NOT NULL CHECK (lot_kind IN ('INCOMING', 'PRODUCED')),
    status             TEXT    NOT NULL CHECK (status IN ('QUARANTINE', 'AVAILABLE', 'CONSUMED', 'REJECTED', 'DISPOSED')),
    manufactured_date  TEXT    CHECK (manufactured_date IS NULL OR manufactured_date IS date(manufactured_date)),
    expiration_date    TEXT    CHECK (expiration_date   IS NULL OR expiration_date   IS date(expiration_date)),
    created_at         TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at         TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE (item_id, lot_number)                        -- LOT 번호는 품목 안에서 유일
) STRICT;

CREATE INDEX ix_lots_number      ON lots (lot_number);
CREATE INDEX ix_lots_item_status ON lots (item_id, status);
CREATE INDEX ix_lots_fefo        ON lots (item_id, expiration_date);

CREATE TABLE lot_number_rules (
    id              INTEGER PRIMARY KEY,
    lot_kind        TEXT    NOT NULL CHECK (lot_kind IN ('INCOMING', 'PRODUCED')),
    item_type       TEXT    REFERENCES item_types(code),
    pattern         TEXT    NOT NULL,                   -- 예) {item_code}-{received:yyMMdd}{seq:A}
    effective_from  TEXT    NOT NULL CHECK (effective_from IS date(effective_from)),
    is_active       INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    notes           TEXT
) STRICT;

CREATE TABLE lot_number_sequences (
    seq_key      TEXT    NOT NULL PRIMARY KEY,          -- 예) 1000019-261008
    current_seq  INTEGER NOT NULL DEFAULT 0,
    updated_at   TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
) STRICT;


/* =========================================================
   4. 재고 / 수불 (I1~I3)
   ========================================================= */

CREATE TABLE stock_movements (
    id                    INTEGER PRIMARY KEY,
    lot_id                INTEGER NOT NULL REFERENCES lots(id),
    movement_type_code    TEXT    NOT NULL REFERENCES stock_movement_types(code),
    quantity_e6           INTEGER NOT NULL CHECK (quantity_e6 > 0),
    corrects_movement_id  INTEGER REFERENCES stock_movements(id),
    staff_id              INTEGER NOT NULL REFERENCES staff(id),
    occurred_at           TEXT    NOT NULL CHECK (occurred_at IS datetime(occurred_at)),   -- 실제 발생 시각 (소급 허용)
    reason                TEXT,
    idempotency_key       TEXT    NOT NULL UNIQUE,
    created_at            TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),     -- 시스템 기록 시각
    CHECK ((movement_type_code IN ('CORRECTION_IN', 'CORRECTION_OUT')) = (corrects_movement_id IS NOT NULL)),
    CHECK (movement_type_code NOT IN ('CORRECTION_IN', 'CORRECTION_OUT', 'ADJUST_IN', 'ADJUST_OUT') OR reason IS NOT NULL)
) STRICT;

CREATE INDEX ix_sm_lot_time ON stock_movements (lot_id, occurred_at);
CREATE INDEX ix_sm_time     ON stock_movements (occurred_at);
CREATE INDEX ix_sm_corrects ON stock_movements (corrects_movement_id);

CREATE TABLE inventory (
    lot_id       INTEGER NOT NULL PRIMARY KEY REFERENCES lots(id),
    quantity_e6  INTEGER NOT NULL DEFAULT 0 CHECK (quantity_e6 >= 0),
    updated_at   TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
) STRICT;


/* =========================================================
   5. 입고 건 (C2: 입고 건 1 = LOT 1)
   - 입고 등록 트랜잭션: lots → stock_movements(RECEIPT) → incoming_receipts → domain_event(INCOMING_RECEIVED)
   - 취소: CORRECTION_OUT(전량) + receipt_status = CANCELLED + INCOMING_RECEIPT_CANCELLED
   ========================================================= */

CREATE TABLE incoming_receipts (
    id                   INTEGER PRIMARY KEY,
    lot_id               INTEGER NOT NULL UNIQUE REFERENCES lots(id),   -- 1:1. 소비기한 기준 LOT 으로 바뀌면 UNIQUE 해제
    supplier_id          INTEGER NOT NULL REFERENCES suppliers(id),
    supplier_lot_number  TEXT,
    received_date        TEXT    NOT NULL CHECK (received_date IS date(received_date)),
    quantity_e6          INTEGER NOT NULL CHECK (quantity_e6 > 0),
    staff_id             INTEGER NOT NULL REFERENCES staff(id),
    stock_movement_id    INTEGER NOT NULL UNIQUE REFERENCES stock_movements(id),
    receipt_status       TEXT    NOT NULL DEFAULT 'COMPLETED' CHECK (receipt_status IN ('COMPLETED', 'CANCELLED')),
    cancelled_at         TEXT    CHECK (cancelled_at IS NULL OR cancelled_at IS datetime(cancelled_at)),
    cancel_reason        TEXT,
    created_at           TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    CHECK ((receipt_status = 'CANCELLED') = (cancelled_at IS NOT NULL)),
    CHECK (cancelled_at IS NULL OR cancel_reason IS NOT NULL)
) STRICT;

CREATE INDEX ix_ir_supplier_lot ON incoming_receipts (supplier_id, supplier_lot_number);
CREATE INDEX ix_ir_date         ON incoming_receipts (received_date);


/* =========================================================
   6. LOT HOLD (I5) — 이번 주는 CONDITIONAL 판정에만 사용
   - deviation_action_id / source_document_id : 문서 도메인 ID (같은 DB 지만 마이그레이션 순서 의존을 피해 FK 미설정)
   ========================================================= */

CREATE TABLE lot_holds (
    id                   INTEGER PRIMARY KEY,
    lot_id               INTEGER NOT NULL REFERENCES lots(id),
    source_type          TEXT    NOT NULL REFERENCES hold_source_types(code),
    deviation_action_id  INTEGER,
    source_document_id   INTEGER,
    parent_hold_id       INTEGER REFERENCES lot_holds(id),
    reason               TEXT    NOT NULL,
    held_by              INTEGER NOT NULL REFERENCES staff(id),
    held_at              TEXT    NOT NULL CHECK (held_at IS datetime(held_at)),
    released_by          INTEGER REFERENCES staff(id),
    released_at          TEXT    CHECK (released_at IS NULL OR released_at IS datetime(released_at)),
    disposition          TEXT    REFERENCES hold_dispositions(code),
    release_reason       TEXT,
    CHECK ((released_at IS NULL AND released_by IS NULL AND disposition IS NULL)
        OR (released_at IS NOT NULL AND released_by IS NOT NULL AND disposition IS NOT NULL AND release_reason IS NOT NULL)),
    CHECK ((source_type = 'PROPAGATED') = (parent_hold_id IS NOT NULL))
) STRICT;

CREATE INDEX ix_holds_lot_open  ON lot_holds (lot_id, released_at);
CREATE INDEX ix_holds_deviation ON lot_holds (deviation_action_id);
CREATE INDEX ix_holds_document  ON lot_holds (source_document_id);


/* =========================================================
   7. 이벤트 수신 기록 (C1) / 변경 이력
   ========================================================= */

/* 문서 domain_event 중 생산이 처리한 것. event_id = domain_event.event_id */
CREATE TABLE domain_event_inbox (
    event_id       INTEGER PRIMARY KEY,
    event_code     TEXT    NOT NULL,
    processed_at   TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    result         TEXT    NOT NULL CHECK (result IN ('APPLIED', 'SKIPPED', 'FAILED')),
    error_message  TEXT
) STRICT;

CREATE TABLE audit_logs (
    id               INTEGER PRIMARY KEY,
    table_name       TEXT    NOT NULL,
    record_id        TEXT    NOT NULL,
    action           TEXT    NOT NULL CHECK (action IN ('INSERT', 'UPDATE', 'DELETE')),
    before_json      TEXT    CHECK (before_json IS NULL OR json_valid(before_json)),
    after_json       TEXT    CHECK (after_json  IS NULL OR json_valid(after_json)),
    reason           TEXT,
    staff_id         INTEGER REFERENCES staff(id),
    source_event_id  INTEGER,
    occurred_at      TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    CHECK (staff_id IS NOT NULL OR source_event_id IS NOT NULL)
) STRICT;

CREATE INDEX ix_audit_record ON audit_logs (table_name, record_id);
CREATE INDEX ix_audit_time   ON audit_logs (occurred_at);


/* =========================================================
   8. 트리거
   ========================================================= */

/* I2. 이동 기록은 수정·삭제 불가 */
CREATE TRIGGER trg_sm_no_update BEFORE UPDATE ON stock_movements
BEGIN
    SELECT RAISE(ABORT, 'stock_movements is append-only: add a CORRECTION movement (I2)');
END;

CREATE TRIGGER trg_sm_no_delete BEFORE DELETE ON stock_movements
BEGIN
    SELECT RAISE(ABORT, 'stock_movements is append-only: add a CORRECTION movement (I2)');
END;

/* I3. 이동 INSERT 시 재고 자동 반영. 음수면 CHECK 위반으로 이동 INSERT 전체 실패
   (UPSERT 는 INSERT 후보 행에 CHECK 를 먼저 적용해 감소 이동이 항상 실패하므로 UPDATE → INSERT 순서로 처리) */
CREATE TRIGGER trg_sm_inventory AFTER INSERT ON stock_movements
BEGIN
    UPDATE inventory
       SET quantity_e6 = quantity_e6 + NEW.quantity_e6 *
                         (SELECT direction FROM stock_movement_types WHERE code = NEW.movement_type_code),
           updated_at  = datetime('now', 'localtime')
     WHERE lot_id = NEW.lot_id;

    INSERT INTO inventory (lot_id, quantity_e6, updated_at)
    SELECT NEW.lot_id,
           NEW.quantity_e6 * (SELECT direction FROM stock_movement_types WHERE code = NEW.movement_type_code),
           datetime('now', 'localtime')
     WHERE NOT EXISTS (SELECT 1 FROM inventory WHERE lot_id = NEW.lot_id);
END;

/* 정정 이동은 같은 LOT 의 원 이동만 가리킬 수 있음 */
CREATE TRIGGER trg_sm_correction_lot BEFORE INSERT ON stock_movements
WHEN NEW.corrects_movement_id IS NOT NULL
 AND (SELECT lot_id FROM stock_movements WHERE id = NEW.corrects_movement_id) IS NOT NEW.lot_id
BEGIN
    SELECT RAISE(ABORT, 'correction must target a movement of the same lot');
END;

/* I4. LOT 이 생긴 품목의 유형 변경 금지 */
CREATE TRIGGER trg_items_type_locked BEFORE UPDATE OF item_type ON items
WHEN NEW.item_type <> OLD.item_type AND EXISTS (SELECT 1 FROM lots WHERE item_id = OLD.id)
BEGIN
    SELECT RAISE(ABORT, 'item_type cannot change after lots exist: create a new item (R4)');
END;

/* lots.updated_at 갱신 (MySQL ON UPDATE CURRENT_TIMESTAMP 대체) */
CREATE TRIGGER trg_lots_updated_at AFTER UPDATE ON lots
WHEN NEW.updated_at = OLD.updated_at
BEGIN
    UPDATE lots SET updated_at = datetime('now', 'localtime') WHERE id = NEW.id;
END;


/* =========================================================
   9. 뷰
   ========================================================= */

/* LOT 사용 가능 여부 (I5) */
CREATE VIEW v_lot_availability AS
SELECT l.id AS lot_id,
       l.lot_number,
       i.item_code,
       i.item_type,
       l.lot_kind,
       l.status,
       (SELECT COUNT(*) FROM lot_holds h WHERE h.lot_id = l.id AND h.released_at IS NULL) AS active_hold_count,
       (l.status = 'AVAILABLE'
        AND NOT EXISTS (SELECT 1 FROM lot_holds h WHERE h.lot_id = l.id AND h.released_at IS NULL)) AS is_usable
FROM lots l
JOIN items i ON i.id = l.item_id;

/* C4. 문서 쪽 읽기 창구: 입고 문서 자동 채움 (subject_type = LOT, subject_id = lot_id)
   계약: 컬럼 삭제·의미 변경 금지, 추가만 허용 */
CREATE VIEW v_doc_incoming_lot AS
SELECT l.id                     AS lot_id,
       l.lot_number,
       i.item_code,
       i.name                   AS item_name,
       i.item_type,
       i.base_unit,
       s.name                   AS supplier_name,
       r.supplier_lot_number,
       r.received_date,
       r.quantity_e6,
       l.manufactured_date,
       l.expiration_date,
       l.status                 AS lot_status,
       r.receipt_status,
       i.item_code || ' ' || i.name || ' / ' || l.lot_number || ' / ' || r.received_date AS subject_label
FROM incoming_receipts r
JOIN lots l      ON l.id = r.lot_id
JOIN items i     ON i.id = l.item_id
JOIN suppliers s ON s.id = r.supplier_id;

/* 원료수불대장 (생산 쪽 조회·출력 화면). 기간·품목유형 필터는 조회 시 WHERE
   예) WHERE occurred_at >= '2026-10-01' AND occurred_at < '2026-11-01' AND item_type = 'RAW' */
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
       st.name                                  AS staff_name
FROM stock_movements m
JOIN lots l                 ON l.id = m.lot_id
JOIN items i                ON i.id = l.item_id
JOIN stock_movement_types t ON t.code = m.movement_type_code
JOIN staff st               ON st.id = m.staff_id;

/* 정합성 점검: 결과가 0행이어야 정상 (테스트·운영 점검용) */
CREATE VIEW v_inventory_mismatch AS
SELECT inv.lot_id, inv.quantity_e6, COALESCE(SUM(m.quantity_e6 * t.direction), 0) AS movement_sum_e6
FROM inventory inv
LEFT JOIN stock_movements m      ON m.lot_id = inv.lot_id
LEFT JOIN stock_movement_types t ON t.code = m.movement_type_code
GROUP BY inv.lot_id, inv.quantity_e6
HAVING inv.quantity_e6 <> COALESCE(SUM(m.quantity_e6 * t.direction), 0);
