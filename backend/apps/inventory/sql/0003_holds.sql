/* =========================================================
   HACCP 생산·수불 — 마이그레이션 003: 보류(HOLD) 재정의 (SQLite 3.37+)
   전제: 0001_core.sql, 0002_production.sql 적용 후. 규칙 S1~S6, 불변식 I1~I5 그대로.

   [결정 — 10/11 미팅 A1 '다' 안, 10/13 가정으로 채택]
   0001 의 lot_holds(LOT 전용)를 보류 테이블 하나(holds)로 바꾼다. 대상은 LOT 또는 제조배치 중 하나.
   - 배치 보류(CCP 이탈은 배치 단위, 10/7 현업) → 그 배치의 산출 LOT 에 전파 보류(PROPAGATED, parent_hold_id)
   - 보류 중인 배치에는 투입·산출을 추가하지 않는다 (서비스가 확인)
   - 배치 보류를 해제하면 열린 전파 보류도 같은 처분으로 해제 (LOT 별로 먼저 해제 가능)
   - 근거 문서가 필요한 사유(hold_source_types.requires_evidence)는 source_document_id 필수 (서비스가 확인)
   - source_document_id = 문서 document.document_id. 마이그레이션 순환을 피해 FK 없음 (0001 C6)
   - 처분(disposition)은 기록일 뿐. 반품·폐기 재고 차감은 수불 이동(RETURN_TO_SUPPLIER / DISPOSAL)으로 한다

   lot_holds 는 사용처가 없어(데이터 없음) 지우고 새로 만든다. 되돌리면 0001 정의로 복구된다.
   ========================================================= */

DROP VIEW v_lot_availability;
DROP TABLE lot_holds;

CREATE TABLE holds (
    id                   INTEGER PRIMARY KEY,
    lot_id               INTEGER REFERENCES lots(id),
    batch_id             INTEGER REFERENCES production_batches(id),
    source_type          TEXT    NOT NULL REFERENCES hold_source_types(code),
    source_document_id   INTEGER,                                   -- 근거 문서 document.document_id
    parent_hold_id       INTEGER REFERENCES holds(id),              -- 전파 보류의 원 보류 (배치 → 산출 LOT)
    reason               TEXT    NOT NULL,
    held_by              INTEGER NOT NULL REFERENCES staff(id),
    held_at              TEXT    NOT NULL CHECK (held_at IS datetime(held_at)),
    released_by          INTEGER REFERENCES staff(id),
    released_at          TEXT    CHECK (released_at IS NULL OR released_at IS datetime(released_at)),
    disposition          TEXT    REFERENCES hold_dispositions(code),
    release_reason       TEXT,
    CHECK ((lot_id IS NULL) <> (batch_id IS NULL)),                  -- 대상은 하나
    CHECK ((source_type = 'PROPAGATED') = (parent_hold_id IS NOT NULL)),
    CHECK (parent_hold_id IS NULL OR lot_id IS NOT NULL),             -- 전파 대상은 LOT
    CHECK ((released_at IS NULL AND released_by IS NULL AND disposition IS NULL)
        OR (released_at IS NOT NULL AND released_by IS NOT NULL AND disposition IS NOT NULL AND release_reason IS NOT NULL))
) STRICT;

CREATE INDEX ix_holds_lot_open   ON holds (lot_id, released_at);
CREATE INDEX ix_holds_batch_open ON holds (batch_id, released_at);
CREATE INDEX ix_holds_parent     ON holds (parent_hold_id);
CREATE INDEX ix_holds_document   ON holds (source_document_id);

/* 보류 기록은 지우지 않는다 (해제로 끝낸다) */
CREATE TRIGGER trg_holds_no_delete BEFORE DELETE ON holds
BEGIN
    SELECT RAISE(ABORT, 'holds are not deleted: release instead');
END;

/* 해제된 보류는 다시 바꾸지 않는다 */
CREATE TRIGGER trg_holds_released_locked BEFORE UPDATE ON holds
WHEN OLD.released_at IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'a released hold cannot change');
END;

/* I5. LOT 사용 가능 여부: 0001 과 같은 컬럼, 보류는 holds 의 LOT 보류(전파 포함) */
CREATE VIEW v_lot_availability AS
SELECT l.id AS lot_id,
       l.lot_number,
       i.item_code,
       i.item_type,
       l.lot_kind,
       l.status,
       (SELECT COUNT(*) FROM holds h WHERE h.lot_id = l.id AND h.released_at IS NULL) AS active_hold_count,
       (l.status = 'AVAILABLE'
        AND NOT EXISTS (SELECT 1 FROM holds h WHERE h.lot_id = l.id AND h.released_at IS NULL)) AS is_usable
FROM lots l
JOIN items i ON i.id = l.item_id;
