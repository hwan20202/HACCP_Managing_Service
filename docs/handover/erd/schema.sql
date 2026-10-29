-- HACCP 관리 프로그램 현재 DB 스키마 (SQLite)
-- 기준 코드: feature/p16-admin-settings 61d4b9f (2026-10-29) — 빈 DB에 `python backend/manage.py migrate`를 실행한 결과를 그대로 옮김
-- 다시 만들기: docs/handover/erd/README.md "다시 뽑는 법"
-- 직접 실행하지 말 것: 표는 migrate가 만든다. 이 파일은 읽기용이다.

-- ============================================================ 표 48개

-- admin_change_log
CREATE TABLE "admin_change_log" ("log_id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "target" text NOT NULL, "target_id" integer NOT NULL, "action" text NOT NULL, "before_json" text NULL CHECK ((JSON_VALID("before_json") OR "before_json" IS NULL)), "after_json" text NULL CHECK ((JSON_VALID("after_json") OR "after_json" IS NULL)), "reason" text NULL, "at" datetime NOT NULL, "actor_id" bigint NOT NULL REFERENCES "staff" ("id") DEFERRABLE INITIALLY DEFERRED, CONSTRAINT "ck_admin_log_target" CHECK ("target" IN ('item_ccp', 'staff', 'role_leader', 'role_form', 'roles_import')), CONSTRAINT "ck_admin_log_action" CHECK ("action" IN ('set', 'default', 'create', 'rename', 'deactivate', 'activate', 'change', 'import', 'bootstrap_create', 'bootstrap_activate')), CONSTRAINT "ck_admin_log_reason" CHECK (("reason" IS NULL OR (LENGTH("reason") >= 1 AND LENGTH("reason") <= 100))));

-- approval
CREATE TABLE "approval" ("approval_id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "slot_no" integer NOT NULL, "label" text NULL, "state" text DEFAULT 'pending' NOT NULL, "comment" text NULL, "decided_at" datetime NULL, "approver_id" bigint NULL REFERENCES "staff" ("id") DEFERRABLE INITIALLY DEFERRED, "request_id" integer NOT NULL REFERENCES "approval_request" ("request_id") DEFERRABLE INITIALLY DEFERRED, "role" text NULL, CONSTRAINT "uq_approval_slot" UNIQUE ("request_id", "slot_no"), CONSTRAINT "ck_approval_slot_no" CHECK ("slot_no" >= 1), CONSTRAINT "ck_approval_state" CHECK ("state" IN ('pending', 'approved', 'rejected', 'skipped')), CONSTRAINT "ck_approval_decided" CHECK ((("decided_at" IS NULL AND "state" = 'pending') OR (NOT ("state" = 'pending') AND "decided_at" IS NOT NULL))), CONSTRAINT "ck_approval_reject_comment" CHECK ((NOT ("state" = 'rejected') OR ("comment" IS NOT NULL AND NOT (TRIM("comment") = '' AND "comment" IS NOT NULL)))), CONSTRAINT "ck_approval_role" CHECK (("role" IS NULL OR "role" IN ('owner', 'leader'))), CONSTRAINT "ck_approval_approver" CHECK ((("approver_id" IS NOT NULL AND "role" IS NULL) OR ("approver_id" IS NOT NULL AND "role" IS NOT NULL AND "state" IN ('approved', 'rejected')) OR ("approver_id" IS NULL AND "role" IS NOT NULL AND NOT ("state" IN ('approved', 'rejected'))))));

-- approval_candidate
CREATE TABLE "approval_candidate" ("approval_id" integer NOT NULL REFERENCES "approval" ("approval_id") DEFERRABLE INITIALLY DEFERRED, "staff_id" bigint NOT NULL REFERENCES "staff" ("id") DEFERRABLE INITIALLY DEFERRED, PRIMARY KEY ("approval_id", "staff_id"));

-- approval_request
CREATE TABLE "approval_request" ("request_id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "attempt" integer NOT NULL, "status" text NOT NULL, "document_version" integer NOT NULL, "subject" text NULL, "work_date" date NOT NULL, "snapshot_json" text NOT NULL CHECK ((JSON_VALID("snapshot_json") OR "snapshot_json" IS NULL)), "requested_at" datetime NOT NULL, "closed_at" datetime NULL, "document_id" integer NOT NULL REFERENCES "document" ("document_id") DEFERRABLE INITIALLY DEFERRED, "requested_by" bigint NOT NULL REFERENCES "staff" ("id") DEFERRABLE INITIALLY DEFERRED, "template_id" integer NOT NULL REFERENCES "document_template" ("template_id") DEFERRABLE INITIALLY DEFERRED, CONSTRAINT "uq_request_attempt" UNIQUE ("document_id", "attempt"), CONSTRAINT "ck_request_attempt" CHECK ("attempt" >= 1), CONSTRAINT "ck_request_closed" CHECK ((("closed_at" IS NULL AND "status" = 'in_progress') OR (NOT ("status" = 'in_progress') AND "closed_at" IS NOT NULL))), CONSTRAINT "ck_request_status" CHECK ("status" IN ('in_progress', 'approved', 'rejected', 'cancelled')));

-- audit_logs
CREATE TABLE audit_logs (
    id               INTEGER PRIMARY KEY,
    table_name       TEXT    NOT NULL,
    record_id        TEXT    NOT NULL,
    action           TEXT    NOT NULL CHECK (action IN ('INSERT', 'UPDATE', 'DELETE')),
    before_json      TEXT    CHECK (before_json IS NULL OR json_valid(before_json)),
    after_json       TEXT    CHECK (after_json  IS NULL OR json_valid(after_json)),
    reason           TEXT,
    staff_id         INTEGER NOT NULL REFERENCES staff(id),
    occurred_at      TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
) STRICT;

-- batch_ccp_applied
CREATE TABLE "batch_ccp_applied" ("ccp_1p" bool NOT NULL, "ccp_2b" bool NOT NULL, "ccp_3p" bool NOT NULL, "id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "decided_at" datetime NOT NULL, "batch_id" bigint NOT NULL UNIQUE REFERENCES "production_batches" ("id") DEFERRABLE INITIALLY DEFERRED, CONSTRAINT "ck_batch_ccp_1p" CHECK ("ccp_1p" IN (0, 1)), CONSTRAINT "ck_batch_ccp_2b" CHECK ("ccp_2b" IN (0, 1)), CONSTRAINT "ck_batch_ccp_3p" CHECK ("ccp_3p" IN (0, 1)));

-- bom_line_alternatives
CREATE TABLE bom_line_alternatives (
    id INTEGER PRIMARY KEY,
    bom_line_id INTEGER NOT NULL REFERENCES bom_lines(id),
    item_id INTEGER NOT NULL REFERENCES items(id),
    UNIQUE (bom_line_id, item_id)
) STRICT;

-- bom_lines
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

-- boms
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

-- ccp_default
CREATE TABLE "ccp_default" ("ccp_1p" bool NOT NULL, "ccp_2b" bool NOT NULL, "ccp_3p" bool NOT NULL, "process_type" text NOT NULL PRIMARY KEY, "updated_at" datetime NOT NULL, CONSTRAINT "ck_ccp_default_type" CHECK ("process_type" IN ('MANUFACTURE', 'PACKAGING')), CONSTRAINT "ck_ccp_default_1p" CHECK ("ccp_1p" IN (0, 1)), CONSTRAINT "ck_ccp_default_2b" CHECK ("ccp_2b" IN (0, 1)), CONSTRAINT "ck_ccp_default_3p" CHECK ("ccp_3p" IN (0, 1)));

-- deviation_action
CREATE TABLE "deviation_action" ("deviation_id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "description" text NOT NULL, "action_result" text NULL, "checked_at" datetime NULL, "created_at" datetime NOT NULL, "updated_at" datetime NOT NULL, "version" integer DEFAULT 1 NOT NULL, "deleted_at" datetime NULL, "actor_id" bigint NULL REFERENCES "staff" ("id") DEFERRABLE INITIALLY DEFERRED, "checked_by" bigint NULL REFERENCES "staff" ("id") DEFERRABLE INITIALLY DEFERRED, "created_by" bigint NOT NULL REFERENCES "staff" ("id") DEFERRABLE INITIALLY DEFERRED, "deleted_by" bigint NULL REFERENCES "staff" ("id") DEFERRABLE INITIALLY DEFERRED, "updated_by" bigint NOT NULL REFERENCES "staff" ("id") DEFERRABLE INITIALLY DEFERRED, "section_id" integer NULL REFERENCES "doc_section" ("section_id") DEFERRABLE INITIALLY DEFERRED, "document_id" integer NOT NULL REFERENCES "document" ("document_id") DEFERRABLE INITIALLY DEFERRED, CONSTRAINT "ck_deviation_description" CHECK ((LENGTH("description") >= 1 AND LENGTH("description") <= 500 AND NOT (TRIM("description", ' ' || char(9) || char(10) || char(13)) = ''))), CONSTRAINT "ck_deviation_result" CHECK (("action_result" IS NULL OR LENGTH("action_result") <= 1000)), CONSTRAINT "ck_deviation_checked_pair" CHECK ((("checked_at" IS NULL AND "checked_by" IS NULL) OR ("checked_at" IS NOT NULL AND "checked_by" IS NOT NULL))), CONSTRAINT "ck_deviation_deleted_pair" CHECK ((("deleted_at" IS NULL AND "deleted_by" IS NULL) OR ("deleted_at" IS NOT NULL AND "deleted_by" IS NOT NULL))), CONSTRAINT "ck_deviation_version" CHECK ("version" >= 1));

-- deviation_checker
CREATE TABLE "deviation_checker" ("deviation_id" integer NOT NULL REFERENCES "deviation_action" ("deviation_id") DEFERRABLE INITIALLY DEFERRED, "staff_id" bigint NOT NULL REFERENCES "staff" ("id") DEFERRABLE INITIALLY DEFERRED, PRIMARY KEY ("deviation_id", "staff_id"));

-- django_content_type
CREATE TABLE "django_content_type" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "app_label" varchar(100) NOT NULL, "model" varchar(100) NOT NULL);

-- django_migrations
CREATE TABLE "django_migrations" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "app" varchar(255) NOT NULL, "name" varchar(255) NOT NULL, "applied" datetime NOT NULL);

-- doc_section
CREATE TABLE "doc_section" ("section_id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "section_def" text NOT NULL, "row_no" integer NOT NULL, "values_json" text NOT NULL CHECK ((JSON_VALID("values_json") OR "values_json" IS NULL)), "recorded_at" datetime NULL, "recorded_by" bigint NULL REFERENCES "staff" ("id") DEFERRABLE INITIALLY DEFERRED, "document_id" integer NOT NULL REFERENCES "document" ("document_id") DEFERRABLE INITIALLY DEFERRED, CONSTRAINT "uq_section_row" UNIQUE ("document_id", "section_def", "row_no"), CONSTRAINT "ux_section_document" UNIQUE ("section_id", "document_id"));

-- document
CREATE TABLE "document" ("document_id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "subject" text NULL, "work_date" date NOT NULL, "due_at" datetime NULL, "status" text NOT NULL, "submitted_at" datetime NULL, "created_at" datetime NOT NULL, "updated_at" datetime NOT NULL, "record_key" text NULL, "completed_at" datetime NULL, "version" integer DEFAULT 1 NOT NULL, "deleted_at" datetime NULL, "assignee_id" bigint NULL REFERENCES "staff" ("id") DEFERRABLE INITIALLY DEFERRED, "completed_by" bigint NULL REFERENCES "staff" ("id") DEFERRABLE INITIALLY DEFERRED, "created_by" bigint NOT NULL REFERENCES "staff" ("id") DEFERRABLE INITIALLY DEFERRED, "deleted_by" bigint NULL REFERENCES "staff" ("id") DEFERRABLE INITIALLY DEFERRED, "template_id" integer NOT NULL REFERENCES "document_template" ("template_id") DEFERRABLE INITIALLY DEFERRED, "skip_reason" text NULL, "skipped_at" datetime NULL, "skipped_by" bigint NULL REFERENCES "staff" ("id") DEFERRABLE INITIALLY DEFERRED, CONSTRAINT "ck_document_deleted_pair" CHECK ((("deleted_at" IS NULL AND "deleted_by" IS NULL) OR ("deleted_at" IS NOT NULL AND "deleted_by" IS NOT NULL))), CONSTRAINT "ck_document_completed_pair" CHECK ((("completed_at" IS NULL AND "completed_by" IS NULL) OR ("completed_at" IS NOT NULL AND "completed_by" IS NOT NULL))), CONSTRAINT "ck_document_completed_required" CHECK ((NOT ("status" = 'completed') OR "completed_at" IS NOT NULL)), CONSTRAINT "ck_document_status" CHECK ("status" IN ('draft', 'completed', 'submitted', 'approved', 'rejected', 'correcting', 'skipped')), CONSTRAINT "ck_document_draft_not_completed" CHECK ((NOT ("status" IN ('draft', 'correcting', 'skipped')) OR "completed_at" IS NULL)), CONSTRAINT "ck_document_skipped_status" CHECK ((("skipped_at" IS NOT NULL AND "status" = 'skipped') OR (NOT ("status" = 'skipped') AND "skipped_at" IS NULL))), CONSTRAINT "ck_document_skipped_pair" CHECK ((("skip_reason" IS NULL AND "skipped_at" IS NULL AND "skipped_by" IS NULL) OR ("skip_reason" IS NOT NULL AND "skipped_at" IS NOT NULL AND "skipped_by" IS NOT NULL))), CONSTRAINT "ck_document_skip_reason" CHECK (("skip_reason" IS NULL OR (LENGTH("skip_reason") >= 1 AND LENGTH("skip_reason") <= 200 AND NOT (TRIM("skip_reason", ' ' || char(9) || char(10) || char(13)) = '' AND "skip_reason" IS NOT NULL)))));

-- document_correction
CREATE TABLE "document_correction" ("correction_id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "started_at" datetime NOT NULL, "reason" text NOT NULL, "start_version" integer NOT NULL, "prev_completed_at" datetime NULL, "closed_at" datetime NULL, "outcome" text NULL, "document_id" integer NOT NULL REFERENCES "document" ("document_id") DEFERRABLE INITIALLY DEFERRED, "prev_completed_by" bigint NULL REFERENCES "staff" ("id") DEFERRABLE INITIALLY DEFERRED, "started_by" bigint NOT NULL REFERENCES "staff" ("id") DEFERRABLE INITIALLY DEFERRED, CONSTRAINT "ck_correction_reason" CHECK ((LENGTH("reason") >= 1 AND LENGTH("reason") <= 200 AND NOT (TRIM("reason", ' ' || char(9) || char(10) || char(13)) = ''))), CONSTRAINT "ck_correction_start_version" CHECK ("start_version" >= 1), CONSTRAINT "ck_correction_prev_pair" CHECK ((("prev_completed_at" IS NULL AND "prev_completed_by" IS NULL) OR ("prev_completed_at" IS NOT NULL AND "prev_completed_by" IS NOT NULL))), CONSTRAINT "ck_correction_closed_pair" CHECK ((("closed_at" IS NULL AND "outcome" IS NULL) OR ("closed_at" IS NOT NULL AND "outcome" IN ('approved', 'cancelled') AND "outcome" IS NOT NULL))));

-- document_file
CREATE TABLE "document_file" ("linked_at" datetime NOT NULL, "document_id" integer NOT NULL REFERENCES "document" ("document_id") DEFERRABLE INITIALLY DEFERRED, "linked_by" bigint NOT NULL REFERENCES "staff" ("id") DEFERRABLE INITIALLY DEFERRED, "file_id" integer NOT NULL REFERENCES "file" ("file_id") DEFERRABLE INITIALLY DEFERRED, PRIMARY KEY ("document_id", "file_id"));

-- document_ref
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
);

-- document_template
CREATE TABLE "document_template" ("template_id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "type_code" text NOT NULL, "version" integer NOT NULL, "name" text NOT NULL, "schema_json" text NOT NULL CHECK ((JSON_VALID("schema_json") OR "schema_json" IS NULL)), "is_active" bool NOT NULL, "created_at" datetime NOT NULL, CONSTRAINT "uq_template_type_version" UNIQUE ("type_code", "version"));

-- file
CREATE TABLE "file" ("file_id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "storage_path" text NOT NULL UNIQUE, "original_name" text NOT NULL, "mime_type" text NOT NULL, "size_bytes" integer NOT NULL, "sha256" text NOT NULL, "uploaded_at" datetime NOT NULL, "retained_at" datetime NULL, "uploaded_by" bigint NOT NULL REFERENCES "staff" ("id") DEFERRABLE INITIALLY DEFERRED, CONSTRAINT "ck_file_name" CHECK ((LENGTH("original_name") >= 1 AND LENGTH("original_name") <= 255)), CONSTRAINT "ck_file_mime" CHECK ("mime_type" IN ('application/pdf', 'image/jpeg', 'image/png')), CONSTRAINT "ck_file_size" CHECK (("size_bytes" >= 1 AND "size_bytes" <= 20971520)), CONSTRAINT "ck_file_sha256" CHECK (LENGTH("sha256") = 64));

-- hold_dispositions
CREATE TABLE hold_dispositions (
    code  TEXT NOT NULL PRIMARY KEY,
    name  TEXT NOT NULL
) STRICT;

-- hold_source_types
CREATE TABLE hold_source_types (
    code               TEXT    NOT NULL PRIMARY KEY,
    name               TEXT    NOT NULL,
    requires_evidence  INTEGER NOT NULL DEFAULT 1 CHECK (requires_evidence IN (0, 1))
) STRICT;

-- holds
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

-- incoming_receipts
CREATE TABLE incoming_receipts (
    id                   INTEGER PRIMARY KEY,
    lot_id               INTEGER NOT NULL UNIQUE REFERENCES lots(id),   -- 1:1 (입고 건별 LOT, 10/7 현업)
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

-- inventory
CREATE TABLE inventory (
    lot_id       INTEGER NOT NULL PRIMARY KEY REFERENCES lots(id),
    quantity_e6  INTEGER NOT NULL DEFAULT 0 CHECK (quantity_e6 >= 0),
    updated_at   TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
) STRICT;

-- inventory_purge_scope
CREATE TABLE inventory_purge_scope (lot_id INTEGER PRIMARY KEY REFERENCES lots(id)) STRICT;

-- item_ccp
CREATE TABLE "item_ccp" (
  "ccp_1p" bool NOT NULL CHECK ("ccp_1p" IN (0, 1)),
  "ccp_2b" bool NOT NULL CHECK ("ccp_2b" IN (0, 1)),
  "ccp_3p" bool NOT NULL CHECK ("ccp_3p" IN (0, 1)),
  "id" integer NOT NULL PRIMARY KEY AUTOINCREMENT,
  "mode" text NOT NULL CHECK ("mode" IN ('default', 'own')),
  "version" integer NOT NULL CHECK ("version" >= 1),
  "updated_at" datetime NOT NULL,
  "item_id" bigint NOT NULL UNIQUE REFERENCES "items" ("id") ON DELETE CASCADE,
  CHECK ("mode" = 'own' OR (NOT "ccp_1p" AND NOT "ccp_2b" AND NOT "ccp_3p"))
);

-- item_types
CREATE TABLE item_types (
    code        TEXT    NOT NULL PRIMARY KEY,
    name        TEXT    NOT NULL,
    code_prefix TEXT,
    sort_order  INTEGER NOT NULL DEFAULT 0
) STRICT;

-- items
CREATE TABLE items (
    id                INTEGER PRIMARY KEY,
    item_type         TEXT    NOT NULL REFERENCES item_types(code),
    item_code         TEXT    NOT NULL UNIQUE,          -- 1·2·3·4코드
    short_code        TEXT    UNIQUE,                   -- LOT 약어 (A** 원료, B** 반제품, C** 포장재). 원료·반제품·포장재 LOT 앞자리
    name              TEXT    NOT NULL,
    base_unit         TEXT    NOT NULL,                 -- kg / g / 개 / 장 …
    unit_weight_mg    INTEGER CHECK (unit_weight_mg IS NULL OR unit_weight_mg > 0),   -- 1 base_unit 표준 중량. 환 4g = 4000
    shelf_life_days   INTEGER CHECK (shelf_life_days IS NULL OR shelf_life_days > 0),
    shelf_life_months INTEGER CHECK (shelf_life_months IS NULL OR shelf_life_months > 0),   -- 소비기한 개월 (제조방법설명서 '제조일로부터 24개월'). 일수와 둘 중 하나만
    origin_country    TEXT,
    food_type         TEXT,
    minimum_stock_e6  INTEGER NOT NULL DEFAULT 0 CHECK (minimum_stock_e6 >= 0),
    is_active         INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at        TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')), is_stock_managed INTEGER NOT NULL DEFAULT 1 CHECK (is_stock_managed IN (0, 1)), manufacturing_report_number TEXT,
    CHECK (shelf_life_days IS NULL OR shelf_life_months IS NULL)
) STRICT;

-- lot_number_rules
CREATE TABLE lot_number_rules (
    id              INTEGER PRIMARY KEY,
    lot_kind        TEXT    NOT NULL CHECK (lot_kind IN ('INCOMING', 'PRODUCED')),
    item_type       TEXT    REFERENCES item_types(code),
    pattern         TEXT    NOT NULL,                   -- 예) {short_code}{date:yyMMdd}{seq:-N}
    effective_from  TEXT    NOT NULL CHECK (effective_from IS date(effective_from)),
    is_active       INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    notes           TEXT
) STRICT;

-- lot_number_sequences
CREATE TABLE lot_number_sequences (
    seq_key      TEXT    NOT NULL PRIMARY KEY,          -- 예) 1000019-261008
    current_seq  INTEGER NOT NULL DEFAULT 0,
    updated_at   TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
) STRICT;

-- lots
CREATE TABLE lots (
    id                 INTEGER PRIMARY KEY,
    lot_number         TEXT    NOT NULL,
    item_id            INTEGER NOT NULL REFERENCES items(id),
    lot_kind           TEXT    NOT NULL CHECK (lot_kind IN ('INCOMING', 'PRODUCED')),
    status             TEXT    NOT NULL CHECK (status IN ('QUARANTINE', 'AVAILABLE', 'REJECTED')),   -- 품질 판정만 (머리말 [LOT 상태])
    manufactured_date  TEXT    CHECK (manufactured_date IS NULL OR manufactured_date IS date(manufactured_date)),
    expiration_date    TEXT    CHECK (expiration_date   IS NULL OR expiration_date   IS date(expiration_date)),
    created_at         TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at         TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')), expiration_status TEXT NOT NULL DEFAULT 'UNKNOWN'
    CHECK (expiration_status IN ('KNOWN', 'NONE', 'UNKNOWN')),
    UNIQUE (item_id, lot_number)    -- 품목 안에서 유일. 완제품 LOT(제조일+근무조)은 제품끼리 같을 수 있음
) STRICT;

-- master_change_log
CREATE TABLE "master_change_log" ("log_id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "target" text NOT NULL, "target_id" integer NOT NULL, "action" text NOT NULL, "before_json" text NULL CHECK ((JSON_VALID("before_json") OR "before_json" IS NULL)), "after_json" text NULL CHECK ((JSON_VALID("after_json") OR "after_json" IS NULL)), "at" datetime NOT NULL, "actor_id" bigint NOT NULL REFERENCES "staff" ("id") DEFERRABLE INITIALLY DEFERRED, "document_id" integer NULL REFERENCES "document" ("document_id") DEFERRABLE INITIALLY DEFERRED, CONSTRAINT "ck_master_log_target" CHECK ("target" IN ('process', 'template')), CONSTRAINT "ck_master_log_action" CHECK ("action" IN ('create', 'update', 'deactivate', 'reactivate', 'delete', 'copy', 'register', 'overwrite')), CONSTRAINT "ck_master_log_target_id" CHECK ("target_id" >= 1));

-- process
CREATE TABLE "process" ("process_id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "name" text NOT NULL, "name_key" text NOT NULL, "kind" text NOT NULL, "mode" text NULL, "is_builtin" bool NOT NULL, "description" text NULL, "std_duration_value" real NULL, "std_duration_unit" text NULL, "is_active" bool NOT NULL, "created_at" datetime NOT NULL, "updated_at" datetime NOT NULL, "version" integer DEFAULT 1 NOT NULL, "created_by" bigint NULL REFERENCES "staff" ("id") DEFERRABLE INITIALLY DEFERRED, "updated_by" bigint NULL REFERENCES "staff" ("id") DEFERRABLE INITIALLY DEFERRED, CONSTRAINT "ck_process_name" CHECK ((LENGTH("name") >= 1 AND LENGTH("name") <= 40 AND NOT (TRIM("name", ' ' || char(9) || char(10) || char(13)) = ''))), CONSTRAINT "ck_process_name_key" CHECK (LENGTH("name_key") >= 1), CONSTRAINT "ck_process_kind" CHECK ("kind" IN ('CCP-1P', 'CCP-2B', 'CCP-3P', 'INNER', 'OUTER', 'GEN')), CONSTRAINT "ck_process_mode" CHECK (("mode" IS NULL OR "mode" IN ('JUDGE', 'TEMP_TIME', 'QTY'))), CONSTRAINT "ck_process_kind_mode" CHECK ((("kind" = 'GEN' AND "mode" IS NOT NULL) OR (NOT ("kind" = 'GEN') AND "mode" IS NULL))), CONSTRAINT "ck_process_builtin" CHECK ((("kind" = 'GEN' AND NOT "is_builtin") OR (NOT ("kind" = 'GEN') AND "is_builtin"))), CONSTRAINT "ck_process_builtin_active" CHECK ((NOT "is_builtin" OR "is_active")), CONSTRAINT "ck_process_description" CHECK (("description" IS NULL OR LENGTH("description") <= 300)), CONSTRAINT "ck_process_std_duration" CHECK ((("std_duration_value" IS NULL AND "std_duration_unit" IS NULL) OR ("std_duration_value" > 0.0 AND "std_duration_value" IS NOT NULL AND "std_duration_unit" IN ('분', '시간', '일') AND "std_duration_unit" IS NOT NULL))), CONSTRAINT "ck_process_version" CHECK ("version" >= 1));

-- process_template
CREATE TABLE "process_template" ("process_template_id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "name" text NOT NULL, "name_key" text NOT NULL, "is_active" bool NOT NULL, "used_count" integer DEFAULT 0 NOT NULL, "last_used_at" datetime NULL, "created_at" datetime NOT NULL, "updated_at" datetime NOT NULL, "version" integer DEFAULT 1 NOT NULL, "created_by" bigint NOT NULL REFERENCES "staff" ("id") DEFERRABLE INITIALLY DEFERRED, "updated_by" bigint NOT NULL REFERENCES "staff" ("id") DEFERRABLE INITIALLY DEFERRED, CONSTRAINT "ck_process_template_name" CHECK ((LENGTH("name") >= 1 AND LENGTH("name") <= 40 AND NOT (TRIM("name", ' ' || char(9) || char(10) || char(13)) = ''))), CONSTRAINT "ck_process_template_name_key" CHECK (LENGTH("name_key") >= 1), CONSTRAINT "ck_process_template_used" CHECK ("used_count" >= 0), CONSTRAINT "ck_process_template_last_used" CHECK (("used_count" = 0 OR "last_used_at" IS NOT NULL)), CONSTRAINT "ck_process_template_version" CHECK ("version" >= 1));

-- process_template_step
CREATE TABLE "process_template_step" ("step_id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "seq" integer NOT NULL, "overrides_json" text NOT NULL CHECK ((JSON_VALID("overrides_json") OR "overrides_json" IS NULL)), "process_id" integer NOT NULL REFERENCES "process" ("process_id") DEFERRABLE INITIALLY DEFERRED, "process_template_id" integer NOT NULL REFERENCES "process_template" ("process_template_id") DEFERRABLE INITIALLY DEFERRED, CONSTRAINT "ck_template_step_seq" CHECK ("seq" >= 1), CONSTRAINT "uq_template_step_seq" UNIQUE ("process_template_id", "seq"), CONSTRAINT "uq_template_step_process" UNIQUE ("process_template_id", "process_id"));

-- production_batches
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
    shift                TEXT    CHECK (shift IS NULL OR shift IN ('A', 'B', 'C')),   -- 근무조: 10/14 폐지 (0005). v_doc_batch 계약 때문에 열만 남김, 항상 NULL
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

-- production_material_usages
CREATE TABLE production_material_usages (
    id                 INTEGER PRIMARY KEY,
    batch_id           INTEGER NOT NULL REFERENCES production_batches(id),
    lot_id             INTEGER NOT NULL REFERENCES lots(id),
    quantity_e6        INTEGER NOT NULL CHECK (quantity_e6 > 0),              -- 실제 투입량 (투입 LOT 품목 기준단위)
    stock_movement_id  INTEGER NOT NULL UNIQUE REFERENCES stock_movements(id),
    bom_line_id        INTEGER REFERENCES bom_lines(id),                       -- 대응하는 BOM 줄 (BOM 밖 투입이면 NULL)
    created_at         TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
) STRICT;

-- production_outputs
CREATE TABLE production_outputs (
    id                 INTEGER PRIMARY KEY,
    batch_id           INTEGER NOT NULL REFERENCES production_batches(id),
    lot_id             INTEGER NOT NULL REFERENCES lots(id),
    quantity_e6        INTEGER NOT NULL CHECK (quantity_e6 > 0),              -- 산출량 (산출 품목 기준단위)
    stock_movement_id  INTEGER NOT NULL UNIQUE REFERENCES stock_movements(id),
    created_at         TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
) STRICT;

-- role_config
CREATE TABLE "role_config" (
  "id" integer NOT NULL PRIMARY KEY CHECK ("id" = 1),
  "version" integer NOT NULL DEFAULT 1 CHECK ("version" >= 1),
  "updated_at" datetime NOT NULL
);

-- role_form
CREATE TABLE "role_form" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "type_code" text NOT NULL UNIQUE, "slots" text NOT NULL, "label_owner" text NULL, "label_leader" text NULL, "created_at" datetime NOT NULL, CONSTRAINT "ck_role_form_type_code" CHECK ((LENGTH("type_code") >= 1 AND LENGTH("type_code") <= 40)), CONSTRAINT "ck_role_form_slots" CHECK ("slots" IN ('owner', 'owner_leader', 'leader', 'none')), CONSTRAINT "ck_role_form_label_owner" CHECK (("label_owner" IS NULL OR ("label_owner" = (TRIM("label_owner")) AND LENGTH("label_owner") >= 1 AND LENGTH("label_owner") <= 20))), CONSTRAINT "ck_role_form_label_leader" CHECK (("label_leader" IS NULL OR ("label_leader" = (TRIM("label_leader")) AND LENGTH("label_leader") >= 1 AND LENGTH("label_leader") <= 20))));

-- role_form_member
CREATE TABLE "role_form_member" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "role" text NOT NULL, "role_form_id" integer NOT NULL REFERENCES "role_form" ("id") DEFERRABLE INITIALLY DEFERRED, "staff_id" bigint NOT NULL REFERENCES "staff" ("id") DEFERRABLE INITIALLY DEFERRED, CONSTRAINT "ck_role_member_role" CHECK ("role" IN ('owner', 'writer')), CONSTRAINT "ux_role_form_member" UNIQUE ("role_form_id", "role", "staff_id"));

-- role_leader
CREATE TABLE "role_leader" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "staff_id" bigint NOT NULL UNIQUE REFERENCES "staff" ("id") DEFERRABLE INITIALLY DEFERRED);

-- staff
CREATE TABLE staff (
    id          INTEGER PRIMARY KEY,
    staff_code  TEXT    NOT NULL UNIQUE,
    name        TEXT    NOT NULL,
    is_active   INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
) STRICT;

-- stock_movement_types
CREATE TABLE stock_movement_types (
    code       TEXT    NOT NULL PRIMARY KEY,
    name       TEXT    NOT NULL,
    direction  INTEGER NOT NULL CHECK (direction IN (1, -1))
) STRICT;

-- stock_movements
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
    created_at            TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')), ea_count INTEGER CHECK (ea_count IS NULL OR ea_count >= 0),     -- 시스템 기록 시각
    CHECK ((movement_type_code IN ('CORRECTION_IN', 'CORRECTION_OUT')) = (corrects_movement_id IS NOT NULL)),
    CHECK (movement_type_code NOT IN ('CORRECTION_IN', 'CORRECTION_OUT', 'ADJUST_IN', 'ADJUST_OUT') OR reason IS NOT NULL)
) STRICT;

-- suppliers
CREATE TABLE suppliers (
    id             INTEGER PRIMARY KEY,
    supplier_code  TEXT    NOT NULL UNIQUE,
    name           TEXT    NOT NULL,
    is_active      INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at     TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
) STRICT;

-- ============================================================ 인덱스 51개

-- ix_admin_log_actor (on admin_change_log)
CREATE INDEX "ix_admin_log_actor" ON "admin_change_log" ("actor_id", "at");

-- ix_admin_log_target (on admin_change_log)
CREATE INDEX "ix_admin_log_target" ON "admin_change_log" ("target", "target_id", "at" DESC);

-- ix_approval_inbox (on approval)
CREATE INDEX "ix_approval_inbox" ON "approval" ("approver_id", "state");

-- ix_approval_candidate_staff (on approval_candidate)
CREATE INDEX "ix_approval_candidate_staff" ON "approval_candidate" ("staff_id");

-- ux_request_open (on approval_request)
CREATE UNIQUE INDEX "ux_request_open" ON "approval_request" ("document_id") WHERE "status" = 'in_progress';

-- ix_audit_record (on audit_logs)
CREATE INDEX ix_audit_record ON audit_logs (table_name, record_id);

-- ix_audit_time (on audit_logs)
CREATE INDEX ix_audit_time   ON audit_logs (occurred_at);

-- ix_bom_lines_component (on bom_lines)
CREATE INDEX ix_bom_lines_component ON bom_lines (component_item_id);

-- ix_boms_item_active (on boms)
CREATE INDEX ix_boms_item_active ON boms (item_id, is_active, effective_from);

-- ix_deviation_document (on deviation_action)
CREATE INDEX "ix_deviation_document" ON "deviation_action" ("document_id") WHERE "deleted_at" IS NULL;

-- ix_deviation_checker_staff (on deviation_checker)
CREATE INDEX "ix_deviation_checker_staff" ON "deviation_checker" ("staff_id");

-- django_content_type_app_label_model_76bd3d3b_uniq (on django_content_type)
CREATE UNIQUE INDEX "django_content_type_app_label_model_76bd3d3b_uniq" ON "django_content_type" ("app_label", "model");

-- ux_section_round (on doc_section)
CREATE UNIQUE INDEX ux_section_round ON doc_section (
  document_id, section_def, json_extract(values_json, '$.round')
) WHERE json_extract(values_json, '$.round') IS NOT NULL
    AND COALESCE(json_extract(values_json, '$.retake'), 0) = 0;

-- ix_document_list (on document)
CREATE INDEX "ix_document_list" ON "document" ("work_date" DESC, "document_id" DESC) WHERE "deleted_at" IS NULL;

-- ux_document_record_key (on document)
CREATE UNIQUE INDEX "ux_document_record_key" ON "document" ("record_key") WHERE "record_key" IS NOT NULL;

-- ix_correction_document (on document_correction)
CREATE INDEX "ix_correction_document" ON "document_correction" ("document_id", "started_at");

-- ux_correction_open (on document_correction)
CREATE UNIQUE INDEX "ux_correction_open" ON "document_correction" ("document_id") WHERE "closed_at" IS NULL;

-- ix_document_file_file (on document_file)
CREATE INDEX "ix_document_file_file" ON "document_file" ("file_id");

-- ix_document_ref_batch (on document_ref)
CREATE INDEX ix_document_ref_batch ON document_ref (production_batch_id, process_code) WHERE production_batch_id IS NOT NULL;

-- ix_document_ref_item (on document_ref)
CREATE INDEX ix_document_ref_item ON document_ref (item_id) WHERE item_id IS NOT NULL;

-- ix_document_ref_label (on document_ref)
CREATE INDEX ix_document_ref_label ON document_ref (label) WHERE label IS NOT NULL;

-- ix_document_ref_lot (on document_ref)
CREATE INDEX ix_document_ref_lot ON document_ref (lot_id) WHERE lot_id IS NOT NULL;

-- ix_document_ref_process (on document_ref)
CREATE INDEX ix_document_ref_process ON document_ref (process_code) WHERE process_code IS NOT NULL;

-- ux_document_ref (on document_ref)
CREATE UNIQUE INDEX ux_document_ref ON document_ref (
  document_id, COALESCE(section_id, 0), COALESCE(lot_id, 0), COALESCE(production_batch_id, 0),
  COALESCE(item_id, 0), COALESCE(process_code, ''));

-- ix_holds_batch_open (on holds)
CREATE INDEX ix_holds_batch_open ON holds (batch_id, released_at);

-- ix_holds_document (on holds)
CREATE INDEX ix_holds_document   ON holds (source_document_id);

-- ix_holds_lot_open (on holds)
CREATE INDEX ix_holds_lot_open   ON holds (lot_id, released_at);

-- ix_holds_parent (on holds)
CREATE INDEX ix_holds_parent     ON holds (parent_hold_id);

-- ix_ir_date (on incoming_receipts)
CREATE INDEX ix_ir_date         ON incoming_receipts (received_date);

-- ix_ir_supplier_lot (on incoming_receipts)
CREATE INDEX ix_ir_supplier_lot ON incoming_receipts (supplier_id, supplier_lot_number);

-- ix_items_type (on items)
CREATE INDEX ix_items_type ON items (item_type);

-- ix_lots_fefo (on lots)
CREATE INDEX ix_lots_fefo        ON lots (item_id, expiration_date);

-- ix_lots_item_status (on lots)
CREATE INDEX ix_lots_item_status ON lots (item_id, status);

-- ix_lots_number (on lots)
CREATE INDEX ix_lots_number      ON lots (lot_number);

-- ix_master_log_target (on master_change_log)
CREATE INDEX "ix_master_log_target" ON "master_change_log" ("target", "target_id", "at" DESC);

-- ux_process_builtin (on process)
CREATE UNIQUE INDEX "ux_process_builtin" ON "process" ("kind") WHERE NOT ("kind" = 'GEN');

-- ux_process_name (on process)
CREATE UNIQUE INDEX "ux_process_name" ON "process" ("name_key") WHERE "is_active";

-- ux_process_template_name (on process_template)
CREATE UNIQUE INDEX "ux_process_template_name" ON "process_template" ("name_key") WHERE "is_active";

-- ix_template_step_process (on process_template_step)
CREATE INDEX "ix_template_step_process" ON "process_template_step" ("process_id");

-- ix_batches_item_date (on production_batches)
CREATE INDEX ix_batches_item_date ON production_batches (item_id, manufactured_date);

-- ix_batches_status (on production_batches)
CREATE INDEX ix_batches_status    ON production_batches (status);

-- ix_usages_batch (on production_material_usages)
CREATE INDEX ix_usages_batch ON production_material_usages (batch_id);

-- ix_usages_lot (on production_material_usages)
CREATE INDEX ix_usages_lot   ON production_material_usages (lot_id);

-- ix_outputs_batch (on production_outputs)
CREATE INDEX ix_outputs_batch ON production_outputs (batch_id);

-- ix_outputs_lot (on production_outputs)
CREATE INDEX ix_outputs_lot   ON production_outputs (lot_id);

-- ix_role_form_member_staff (on role_form_member)
CREATE INDEX "ix_role_form_member_staff" ON "role_form_member" ("staff_id");

-- role_form_member_role_form_id_b563ea0f (on role_form_member)
CREATE INDEX "role_form_member_role_form_id_b563ea0f" ON "role_form_member" ("role_form_id");

-- role_form_member_staff_id_aa7be003 (on role_form_member)
CREATE INDEX "role_form_member_staff_id_aa7be003" ON "role_form_member" ("staff_id");

-- ix_sm_corrects (on stock_movements)
CREATE INDEX ix_sm_corrects ON stock_movements (corrects_movement_id);

-- ix_sm_lot_time (on stock_movements)
CREATE INDEX ix_sm_lot_time ON stock_movements (lot_id, occurred_at);

-- ix_sm_time (on stock_movements)
CREATE INDEX ix_sm_time     ON stock_movements (occurred_at);

-- ============================================================ 뷰 10개

-- v_batch_outputs
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

-- v_batch_usages
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

-- v_doc_batch
CREATE VIEW v_doc_batch AS
SELECT b.id AS production_batch_id,
       b.batch_number,
       b.process_type,
       b.status,
       b.shift,
       i.id AS item_id,
       i.item_code,
       i.name AS item_name,
       i.item_type,
       i.base_unit,
       i.unit_weight_mg,
       b.bom_id,
       bm.version AS bom_version,
       b.planned_date,
       b.planned_quantity_e6,
       b.manufactured_date,
       b.started_at,
       b.completed_at,
       (SELECT COALESCE(SUM(o.net_quantity_e6), 0) FROM v_batch_outputs o WHERE o.batch_id = b.id) AS output_quantity_e6,
       (SELECT COUNT(DISTINCT o.lot_id) FROM v_batch_outputs o WHERE o.batch_id = b.id) AS output_lot_count,
       (SELECT COUNT(*) FROM v_batch_usages u WHERE u.batch_id = b.id) AS input_line_count,
       st.name AS staff_name,
       i.item_code || ' ' || i.name || ' / ' || b.batch_number
           || ' / ' || COALESCE(b.manufactured_date, b.planned_date, '') AS subject_label,
       (SELECT GROUP_CONCAT(DISTINCT o.lot_number) FROM v_batch_outputs o WHERE o.batch_id = b.id) AS output_lot_number,
       i.food_type,
       i.manufacturing_report_number
FROM production_batches b
JOIN items i ON i.id = b.item_id
JOIN staff st ON st.id = b.staff_id
LEFT JOIN boms bm ON bm.id = b.bom_id;

-- v_doc_batch_bom_line
CREATE VIEW v_doc_batch_bom_line AS
WITH RECURSIVE scale (
    production_batch_id, bom_line_id, remaining, divisor, add_q, add_r, total_q, total_r
) AS (
    SELECT b.id, l.id, b.planned_quantity_e6, bm.base_quantity_e6,
           l.quantity_e6 / bm.base_quantity_e6, l.quantity_e6 % bm.base_quantity_e6,
           0, 0
    FROM production_batches b
    JOIN boms bm ON bm.id = b.bom_id
    JOIN bom_lines l ON l.bom_id = bm.id
    UNION ALL
    SELECT production_batch_id, bom_line_id, remaining / 2, divisor,
           CASE WHEN remaining > 1 THEN add_q * 2 + (add_r >= divisor - add_r) ELSE 0 END,
           CASE WHEN remaining <= 1 THEN 0
                WHEN add_r >= divisor - add_r THEN add_r - (divisor - add_r)
                ELSE add_r + add_r END,
           total_q + CASE WHEN remaining % 2 = 1
                          THEN add_q + (total_r >= divisor - add_r) ELSE 0 END,
           CASE WHEN remaining % 2 = 0 THEN total_r
                WHEN total_r >= divisor - add_r THEN total_r - (divisor - add_r)
                ELSE total_r + add_r END
    FROM scale WHERE remaining > 0
)
SELECT b.id AS production_batch_id,
       bm.id AS bom_id,
       bm.version AS bom_version,
       l.id AS bom_line_id,
       l.line_no,
       i.id AS item_id,
       i.item_code,
       i.name AS item_name,
       i.origin_country,
       i.base_unit,
       i.is_stock_managed,
       bm.base_quantity_e6 AS bom_base_quantity_e6,
       l.quantity_e6 AS bom_quantity_e6,
       b.planned_quantity_e6,
       CASE WHEN b.planned_quantity_e6 IS NULL THEN NULL
            ELSE s.total_q + (s.total_r > 0) END AS standard_quantity_e6
FROM scale s
JOIN production_batches b ON b.id = s.production_batch_id
JOIN boms bm ON bm.id = b.bom_id
JOIN bom_lines l ON l.id = s.bom_line_id
JOIN items i ON i.id = l.component_item_id
WHERE s.remaining = 0 OR s.remaining IS NULL;

-- v_doc_batch_usage
CREATE VIEW v_doc_batch_usage AS
SELECT b.id AS production_batch_id,
       u.usage_id,
       COALESCE(u.bom_line_id, bl.id) AS bom_line_id,
       COALESCE(linked.line_no, bl.line_no) AS line_no,
       COALESCE(linked.component_item_id, bl.component_item_id) AS bom_item_id,
       original.item_code AS bom_item_code,
       original.name AS bom_item_name,
       original.base_unit AS bom_base_unit,
       u.item_id,
       i.item_code,
       i.name AS item_name,
       i.origin_country,
       i.base_unit,
       i.is_stock_managed,
       u.lot_id,
       u.lot_number,
       u.quantity_e6,
       u.net_quantity_e6,
       u.stock_movement_id,
       m.occurred_at,
       date(m.occurred_at) AS input_date
FROM v_batch_usages u
JOIN production_batches b ON b.id = u.batch_id
JOIN items i ON i.id = u.item_id
JOIN stock_movements m ON m.id = u.stock_movement_id
LEFT JOIN bom_lines linked ON linked.id = u.bom_line_id
LEFT JOIN bom_lines bl ON u.bom_line_id IS NULL AND bl.bom_id = b.bom_id
                          AND bl.component_item_id = u.item_id
LEFT JOIN items original ON original.id = COALESCE(linked.component_item_id, bl.component_item_id);

-- v_doc_incoming_lot
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

-- v_inventory_mismatch
CREATE VIEW v_inventory_mismatch AS
SELECT inv.lot_id, inv.quantity_e6, COALESCE(SUM(m.quantity_e6 * t.direction), 0) AS movement_sum_e6
FROM inventory inv
LEFT JOIN stock_movements m      ON m.lot_id = inv.lot_id
LEFT JOIN stock_movement_types t ON t.code = m.movement_type_code
GROUP BY inv.lot_id, inv.quantity_e6
HAVING inv.quantity_e6 <> COALESCE(SUM(m.quantity_e6 * t.direction), 0);

-- v_lot_availability
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

-- v_lot_trace
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

-- v_stock_ledger
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

-- ============================================================ 트리거 41개

-- trg_alternatives_locked_delete (on bom_line_alternatives)
CREATE TRIGGER trg_alternatives_locked_delete BEFORE DELETE ON bom_line_alternatives
WHEN EXISTS (SELECT 1 FROM production_batches b JOIN bom_lines l ON l.bom_id = b.bom_id WHERE l.id = OLD.bom_line_id)
BEGIN
    SELECT RAISE(ABORT, 'BOM is used by a production batch: create a new version');
END;

-- trg_alternatives_locked_insert (on bom_line_alternatives)
CREATE TRIGGER trg_alternatives_locked_insert BEFORE INSERT ON bom_line_alternatives
WHEN EXISTS (SELECT 1 FROM production_batches b JOIN bom_lines l ON l.bom_id = b.bom_id WHERE l.id = NEW.bom_line_id)
BEGIN
    SELECT RAISE(ABORT, 'BOM is used by a production batch: create a new version');
END;

-- trg_alternatives_no_update (on bom_line_alternatives)
CREATE TRIGGER trg_alternatives_no_update BEFORE UPDATE ON bom_line_alternatives
BEGIN
    SELECT RAISE(ABORT, 'replace alternatives before using the BOM; create a new version after use');
END;

-- trg_alternatives_valid (on bom_line_alternatives)
CREATE TRIGGER trg_alternatives_valid BEFORE INSERT ON bom_line_alternatives
WHEN NEW.item_id = (SELECT component_item_id FROM bom_lines WHERE id = NEW.bom_line_id)
 OR NEW.item_id = (SELECT b.item_id FROM boms b JOIN bom_lines l ON l.bom_id = b.id WHERE l.id = NEW.bom_line_id)
BEGIN
    SELECT RAISE(ABORT, 'alternative cannot be the primary component or output item');
END;

-- trg_bom_lines_locked_delete (on bom_lines)
CREATE TRIGGER trg_bom_lines_locked_delete BEFORE DELETE ON bom_lines
WHEN EXISTS (SELECT 1 FROM production_batches WHERE bom_id = OLD.bom_id)
BEGIN
    SELECT RAISE(ABORT, 'BOM is used by a production batch: create a new version');
END;

-- trg_bom_lines_locked_insert (on bom_lines)
CREATE TRIGGER trg_bom_lines_locked_insert BEFORE INSERT ON bom_lines
WHEN EXISTS (SELECT 1 FROM production_batches WHERE bom_id = NEW.bom_id)
BEGIN
    SELECT RAISE(ABORT, 'BOM is used by a production batch: create a new version');
END;

-- trg_bom_lines_locked_update (on bom_lines)
CREATE TRIGGER trg_bom_lines_locked_update BEFORE UPDATE ON bom_lines
WHEN EXISTS (SELECT 1 FROM production_batches WHERE bom_id IN (OLD.bom_id, NEW.bom_id))
BEGIN
    SELECT RAISE(ABORT, 'BOM is used by a production batch: create a new version');
END;

-- trg_bom_lines_no_self (on bom_lines)
CREATE TRIGGER trg_bom_lines_no_self BEFORE INSERT ON bom_lines
WHEN NEW.component_item_id = (SELECT item_id FROM boms WHERE id = NEW.bom_id)
BEGIN
    SELECT RAISE(ABORT, 'a BOM cannot contain its own item');
END;

-- trg_boms_locked (on boms)
CREATE TRIGGER trg_boms_locked BEFORE UPDATE OF item_id, base_quantity_e6 ON boms
WHEN EXISTS (SELECT 1 FROM production_batches WHERE bom_id = OLD.id)
BEGIN
    SELECT RAISE(ABORT, 'BOM is used by a production batch: create a new version');
END;

-- trg_holds_no_delete (on holds)
CREATE TRIGGER trg_holds_no_delete BEFORE DELETE ON holds
BEGIN
    SELECT RAISE(ABORT, 'holds are not deleted: release instead');
END;

-- trg_holds_released_locked (on holds)
CREATE TRIGGER trg_holds_released_locked BEFORE UPDATE ON holds
WHEN OLD.released_at IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'a released hold cannot change');
END;

-- trg_receipts_raw_expiration_known (on incoming_receipts)
CREATE TRIGGER trg_receipts_raw_expiration_known BEFORE INSERT ON incoming_receipts
WHEN (SELECT i.item_type FROM lots l JOIN items i ON i.id = l.item_id WHERE l.id = NEW.lot_id) = 'RAW'
 AND (SELECT expiration_status FROM lots WHERE id = NEW.lot_id) = 'UNKNOWN'
BEGIN
    SELECT RAISE(ABORT, 'raw material receipt needs expiration_status KNOWN or NONE (0007)');
END;

-- trg_items_stock_managed_locked (on items)
CREATE TRIGGER trg_items_stock_managed_locked BEFORE UPDATE OF is_stock_managed ON items
WHEN NEW.is_stock_managed = 0 AND OLD.is_stock_managed = 1
 AND EXISTS (SELECT 1 FROM lots WHERE item_id = OLD.id)
BEGIN
    SELECT RAISE(ABORT, 'item has lots: it cannot become non stock-managed');
END;

-- trg_items_type_locked (on items)
CREATE TRIGGER trg_items_type_locked BEFORE UPDATE OF item_type ON items
WHEN NEW.item_type <> OLD.item_type AND EXISTS (SELECT 1 FROM lots WHERE item_id = OLD.id)
BEGIN
    SELECT RAISE(ABORT, 'item_type cannot change after lots exist: create a new item (R4)');
END;

-- trg_lots_expiration_status_insert (on lots)
CREATE TRIGGER trg_lots_expiration_status_insert BEFORE INSERT ON lots
WHEN (NEW.expiration_status = 'KNOWN') <> (NEW.expiration_date IS NOT NULL)
BEGIN
    SELECT RAISE(ABORT, 'expiration_status KNOWN needs expiration_date, and only KNOWN has one (0007)');
END;

-- trg_lots_expiration_status_update (on lots)
CREATE TRIGGER trg_lots_expiration_status_update BEFORE UPDATE OF expiration_status, expiration_date ON lots
WHEN (NEW.expiration_status = 'KNOWN') <> (NEW.expiration_date IS NOT NULL)
BEGIN
    SELECT RAISE(ABORT, 'expiration_status KNOWN needs expiration_date, and only KNOWN has one (0007)');
END;

-- trg_lots_stock_managed (on lots)
CREATE TRIGGER trg_lots_stock_managed BEFORE INSERT ON lots
WHEN (SELECT is_stock_managed FROM items WHERE id = NEW.item_id) = 0
BEGIN
    SELECT RAISE(ABORT, 'item is not stock-managed: no lots (C1)');
END;

-- trg_lots_updated_at (on lots)
CREATE TRIGGER trg_lots_updated_at AFTER UPDATE ON lots
WHEN NEW.updated_at = OLD.updated_at
BEGIN
    UPDATE lots SET updated_at = datetime('now', 'localtime') WHERE id = NEW.id;
END;

-- trg_batches_bom_item_insert (on production_batches)
CREATE TRIGGER trg_batches_bom_item_insert BEFORE INSERT ON production_batches
WHEN NEW.bom_id IS NOT NULL AND (SELECT item_id FROM boms WHERE id = NEW.bom_id) IS NOT NEW.item_id
BEGIN
    SELECT RAISE(ABORT, 'batch BOM must belong to the batch item');
END;

-- trg_batches_bom_item_update (on production_batches)
CREATE TRIGGER trg_batches_bom_item_update BEFORE UPDATE OF bom_id, item_id ON production_batches
WHEN NEW.bom_id IS NOT NULL AND (SELECT item_id FROM boms WHERE id = NEW.bom_id) IS NOT NEW.item_id
BEGIN
    SELECT RAISE(ABORT, 'batch BOM must belong to the batch item');
END;

-- trg_batches_item_locked (on production_batches)
CREATE TRIGGER trg_batches_item_locked BEFORE UPDATE OF item_id ON production_batches
WHEN NEW.item_id <> OLD.item_id
 AND (EXISTS (SELECT 1 FROM production_material_usages WHERE batch_id = OLD.id)
      OR EXISTS (SELECT 1 FROM production_outputs WHERE batch_id = OLD.id))
BEGIN
    SELECT RAISE(ABORT, 'batch item cannot change after inputs or outputs exist');
END;

-- trg_batches_no_delete (on production_batches)
CREATE TRIGGER trg_batches_no_delete BEFORE DELETE ON production_batches
BEGIN
    SELECT RAISE(ABORT, 'production batches are not deleted: cancel instead');
END;

-- trg_batches_no_packaging (on production_batches)
CREATE TRIGGER trg_batches_no_packaging BEFORE INSERT ON production_batches
WHEN NEW.process_type = 'PACKAGING'
BEGIN
    SELECT RAISE(ABORT, 'packaging batches are out of the MVP scope (0006)');
END;

-- trg_batches_no_packaging_update (on production_batches)
CREATE TRIGGER trg_batches_no_packaging_update BEFORE UPDATE OF process_type ON production_batches
WHEN NEW.process_type = 'PACKAGING' AND OLD.process_type <> 'PACKAGING'
BEGIN
    SELECT RAISE(ABORT, 'packaging batches are out of the MVP scope (0006)');
END;

-- trg_batches_updated_at (on production_batches)
CREATE TRIGGER trg_batches_updated_at AFTER UPDATE ON production_batches
WHEN NEW.updated_at = OLD.updated_at
BEGIN
    UPDATE production_batches SET updated_at = datetime('now', 'localtime') WHERE id = NEW.id;
END;

-- trg_usages_batch_open (on production_material_usages)
CREATE TRIGGER trg_usages_batch_open BEFORE INSERT ON production_material_usages
WHEN (SELECT status FROM production_batches WHERE id = NEW.batch_id) = 'CANCELLED'
BEGIN
    SELECT RAISE(ABORT, 'batch is cancelled');
END;

-- trg_usages_movement (on production_material_usages)
CREATE TRIGGER trg_usages_movement BEFORE INSERT ON production_material_usages
WHEN NOT EXISTS (
    SELECT 1 FROM stock_movements m
     WHERE m.id = NEW.stock_movement_id AND m.lot_id = NEW.lot_id
       AND m.quantity_e6 = NEW.quantity_e6 AND m.movement_type_code = 'PRODUCTION_USE')
BEGIN
    SELECT RAISE(ABORT, 'usage must point to a PRODUCTION_USE movement of the same lot and quantity');
END;

-- trg_usages_no_delete (on production_material_usages)
CREATE TRIGGER trg_usages_no_delete BEFORE DELETE ON production_material_usages
BEGIN
    SELECT RAISE(ABORT, 'production_material_usages is append-only: correct the stock movement');
END;

-- trg_usages_no_update (on production_material_usages)
CREATE TRIGGER trg_usages_no_update BEFORE UPDATE ON production_material_usages
BEGIN
    SELECT RAISE(ABORT, 'production_material_usages is append-only: correct the stock movement');
END;

-- trg_outputs_batch_open (on production_outputs)
CREATE TRIGGER trg_outputs_batch_open BEFORE INSERT ON production_outputs
WHEN (SELECT status FROM production_batches WHERE id = NEW.batch_id) = 'CANCELLED'
BEGIN
    SELECT RAISE(ABORT, 'batch is cancelled');
END;

-- trg_outputs_lot_item (on production_outputs)
CREATE TRIGGER trg_outputs_lot_item BEFORE INSERT ON production_outputs
WHEN (SELECT l.item_id FROM lots l WHERE l.id = NEW.lot_id)
         IS NOT (SELECT b.item_id FROM production_batches b WHERE b.id = NEW.batch_id)
  OR (SELECT l.lot_kind FROM lots l WHERE l.id = NEW.lot_id) <> 'PRODUCED'
BEGIN
    SELECT RAISE(ABORT, 'output lot must be a PRODUCED lot of the batch item');
END;

-- trg_outputs_movement (on production_outputs)
CREATE TRIGGER trg_outputs_movement BEFORE INSERT ON production_outputs
WHEN NOT EXISTS (
    SELECT 1 FROM stock_movements m
     WHERE m.id = NEW.stock_movement_id AND m.lot_id = NEW.lot_id
       AND m.quantity_e6 = NEW.quantity_e6 AND m.movement_type_code = 'PRODUCTION_OUTPUT')
BEGIN
    SELECT RAISE(ABORT, 'output must point to a PRODUCTION_OUTPUT movement of the same lot and quantity');
END;

-- trg_outputs_no_delete (on production_outputs)
CREATE TRIGGER trg_outputs_no_delete BEFORE DELETE ON production_outputs
BEGIN
    SELECT RAISE(ABORT, 'production_outputs is append-only: correct the stock movement');
END;

-- trg_outputs_no_update (on production_outputs)
CREATE TRIGGER trg_outputs_no_update BEFORE UPDATE ON production_outputs
BEGIN
    SELECT RAISE(ABORT, 'production_outputs is append-only: correct the stock movement');
END;

-- trg_outputs_one_batch_per_lot (on production_outputs)
CREATE TRIGGER trg_outputs_one_batch_per_lot BEFORE INSERT ON production_outputs
WHEN EXISTS (SELECT 1 FROM production_outputs WHERE lot_id = NEW.lot_id AND batch_id <> NEW.batch_id)
BEGIN
    SELECT RAISE(ABORT, 'an output lot belongs to one batch (0006)');
END;

-- trg_outputs_one_lot_per_batch (on production_outputs)
CREATE TRIGGER trg_outputs_one_lot_per_batch BEFORE INSERT ON production_outputs
WHEN EXISTS (SELECT 1 FROM production_outputs WHERE batch_id = NEW.batch_id AND lot_id <> NEW.lot_id)
BEGIN
    SELECT RAISE(ABORT, 'a batch has one output lot: add output to that lot (0006)');
END;

-- trg_role_config_no_delete (on role_config)
CREATE TRIGGER "trg_role_config_no_delete" BEFORE DELETE ON "role_config"
BEGIN
  SELECT RAISE(ABORT, 'role_config row is required');
END;

-- trg_sm_correction_lot (on stock_movements)
CREATE TRIGGER trg_sm_correction_lot BEFORE INSERT ON stock_movements
WHEN NEW.corrects_movement_id IS NOT NULL
 AND (SELECT lot_id FROM stock_movements WHERE id = NEW.corrects_movement_id) IS NOT NEW.lot_id
BEGIN
    SELECT RAISE(ABORT, 'correction must target a movement of the same lot');
END;

-- trg_sm_inventory (on stock_movements)
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

-- trg_sm_no_delete (on stock_movements)
CREATE TRIGGER trg_sm_no_delete BEFORE DELETE ON stock_movements
WHEN NOT EXISTS (SELECT 1 FROM inventory_purge_scope WHERE lot_id = OLD.lot_id)
 OR EXISTS (SELECT 1 FROM production_material_usages WHERE lot_id = OLD.lot_id)
 OR EXISTS (SELECT 1 FROM production_outputs WHERE lot_id = OLD.lot_id)
 OR EXISTS (SELECT 1 FROM holds WHERE lot_id = OLD.lot_id)
 OR EXISTS (SELECT 1 FROM stock_movements WHERE lot_id = OLD.lot_id
            AND movement_type_code NOT IN ('RECEIPT', 'CORRECTION_IN', 'CORRECTION_OUT'))
BEGIN
    SELECT RAISE(ABORT, 'stock_movements is append-only: only unused item removal is allowed');
END;

-- trg_sm_no_update (on stock_movements)
CREATE TRIGGER trg_sm_no_update BEFORE UPDATE ON stock_movements
BEGIN
    SELECT RAISE(ABORT, 'stock_movements is append-only: add a CORRECTION movement (I2)');
END;
