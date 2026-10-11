# 생산·수불 ↔ 문서 연동 인터페이스

문서 앱이 생산·수불(inventory) 앱에서 쓰는 테이블·뷰·함수를 한곳에 모았습니다. 10/11 ERD 협의 반영본 기준 (`feature/inventory`, 0001·0002 확정). 결정 근거는 [inventory-decisions.md](inventory-decisions.md).

## 1. 기본 규칙

| 항목 | 규칙 |
|---|---|
| 연동 방식 | 앱 간 직접 함수 호출. 식별자(id)만 넘기고 받는 쪽이 조회. 이벤트 테이블을 주고받지 않음 |
| 마이그레이션 의존 | 문서 앱 첫 마이그레이션이 `("inventory", "0002_production")` 에 의존 |
| FK 대상 모델 | `inventory.Staff`, `inventory.Item`, `inventory.Lot`, `inventory.ProductionBatch` (모두 `managed=False`, 테이블은 SQL 파일이 만듦) |
| 삭제 | LOT·배치·품목은 삭제하지 않음 (배치는 취소). 문서 쪽 FK 는 `PROTECT`/RESTRICT 로 충분 |
| 수량 | 정수 `*_e6` = 기준단위 × 1,000,000 (`50 kg → 50000000`). 화면·스냅샷 표시는 `apps.inventory.quantity.from_e6()` |
| 단위 | 품목 기준단위 `items.base_unit` (kg / g / 개 / 장 …). kg 로 바꿔 주지 않음 |
| 일자·일시 | 일자 `YYYY-MM-DD`, 일시 `YYYY-MM-DD HH:MM:SS` (KST, 타임존 표기 없음) |
| 쓰기 | 문서 쪽은 수불 테이블에 직접 쓰지 않음. LOT 상태 변경은 판정 함수로만 |

## 2. 수불 소유 테이블 (문서 쪽이 FK 로 참조)

| 테이블 | 주요 컬럼 | 비고 |
|---|---|---|
| `staff` | `id`, `staff_code`(UNIQUE), `name`, `is_active` | 작성자·결재자 등은 `staff.id` 참조 |
| `items` | `id`, `item_code`(UNIQUE), `short_code`(LOT 약어), `name`, `item_type`, `base_unit`, `origin_country`, `shelf_life_days` | `item_type`: RAW 원료 / PACKAGING 포장재 / SEMI 반제품 / FINISHED 완제품 |
| `lots` | `id`, `lot_number`(**품목 안에서 UNIQUE**), `item_id`, `lot_kind`, `status`, `manufactured_date`, `expiration_date` | `lot_kind`: INCOMING / PRODUCED |
| `production_batches` | `id`, `batch_number`(UNIQUE), `process_type`, `item_id`, `status`, `manufactured_date`, `shift`, … | `process_type`: MANUFACTURE / PACKAGING, `shift`: A 주간 / B 야간 / C 오후 |

**LOT 번호** (BOM v4 멘토안): 원료·포장재 `LOT 약어 + 입고일` (`AHN261005`), 반제품 `LOT 약어 + 제조일` (`BNY261007`), 완제품 `제조일 + 근무조` (`261011A`). 같은 날 같은 품목이 또 생기면 `-2`, `-3`.
완제품은 제품이 달라도 번호가 같을 수 있으므로 **LOT 은 `lot_id` 로 식별**하고, 화면·라벨에는 품목코드와 함께 표시합니다 (`4000001 / 261011A`). `document_ref.label` 같은 표시용 값으로 LOT 을 찾지 마세요.

**`lots.status`** — 품질 판정만 나타냄

| 값 | 뜻 |
|---|---|
| QUARANTINE | 검사대기 (입고 시 판정 미확정) |
| AVAILABLE | 적합 (PASS) |
| REJECTED | 부적합 (FAIL). 반품해도 REJECTED 유지 |

재고가 남았는지는 재고(`inventory`), 어떻게 비었는지(투입·반품·폐기)는 수불 기록이 나타냅니다. 소진·폐기 상태는 없습니다.

**`production_batches.status`**: PLANNED 계획 / IN_PROGRESS 진행 / COMPLETED 완료 / CANCELLED 취소. 문서 쪽은 CANCELLED 배치에 문서를 만들지 않습니다.

## 3. 읽기 뷰

계약: 컬럼 삭제·의미 변경 없음, 추가만 함. 확인 방법은 [6절](#6-직접-확인하기).

### `v_doc_incoming_lot` — LOT 대상 문서 자동 채움 (`sql/0001_core.sql`)

모든 LOT 1행씩 (입고·생산·기초재고). `lot_id` 로 조회.

| 컬럼 | 뜻 | NULL |
|---|---|---|
| `lot_id` | `lots.id` | |
| `lot_number` | LOT 번호 | |
| `lot_kind` | INCOMING / PRODUCED | |
| `item_id`, `item_code`, `item_name` | 품목 | |
| `item_type` | RAW / PACKAGING / SEMI / FINISHED | |
| `item_type_name` | 원료 / 포장재 / 반제품 / 완제품 | |
| `base_unit` | 기준단위 | |
| `origin_country` | 원산지 국가명 (국내/수입 판단은 문서 쪽) | 있음 |
| `supplier_name` | 공급처 | 입고 건 없으면 NULL |
| `supplier_lot_number` | 공급처 LOT 번호 | 있음 |
| `received_date` | 입고일 (입고 문서 업무일) | 입고 건 없으면 NULL |
| `quantity_e6` | 입고 수량 (`_e6`) | 입고 건 없으면 NULL |
| `manufactured_date`, `expiration_date` | 제조일, 소비기한 | 있음 |
| `lot_status` | QUARANTINE / AVAILABLE / REJECTED | |
| `receipt_status` | COMPLETED / CANCELLED (입고 취소) | 입고 건 없으면 NULL |
| `subject_label` | `품목코드 품명 / LOT번호 / 입고일(또는 제조일)` 표시용 | |

- 생산 LOT, 기초재고 이관 LOT 은 입고 건이 없어 공급처·입고일·입고 수량이 NULL
- 입고가 취소돼도 행은 남고 `receipt_status = CANCELLED`

문서 쪽 요청 대비 바뀐 이름: `quantity` → `quantity_e6`, `unit` → `base_unit`, `material_kind` → `item_type` / `item_type_name`, `origin` → `origin_country`

### `v_doc_batch` — 생산일지·CCP 일지 자동 채움 (`sql/0002_production.sql`)

배치 1행씩. `production_batch_id` 로 조회.

| 컬럼 | 뜻 |
|---|---|
| `production_batch_id` | `production_batches.id` |
| `batch_number`, `process_type`, `status` | 배치 번호, MANUFACTURE / PACKAGING, 상태 |
| `shift` | 근무조 A 주간 / B 야간 / C 오후 (NULL 가능) |
| `item_id`, `item_code`, `item_name`, `item_type`, `base_unit` | 산출 품목 |
| `bom_id`, `bom_version` | 기준 BOM (없으면 NULL) |
| `planned_date`, `planned_quantity_e6` | 계획 (NULL 가능 — 사후 입력) |
| `manufactured_date`, `started_at`, `completed_at` | 제조일, 시작·완료 시각 |
| `output_quantity_e6` | 산출 합계 (정정 반영, `base_unit` 기준) |
| `output_lot_count`, `input_line_count` | 산출 LOT 수, 투입 줄 수 |
| `staff_name` | 작업 책임자 |
| `subject_label` | `품목코드 품명 / 배치번호 / 제조일` 표시용 |

문서 쪽 요청 대비: `quantity_kg` 대신 `output_quantity_e6` + `base_unit` (완제품은 단위가 `개`)

## 4. 수불이 제공하는 함수 (문서 → 수불 호출)

### `apps.inventory.judgment.apply_incoming_judgment(...)`

육안검사 판정을 LOT 상태에 반영. 육안검사일지 **작성완료** 때 호출 (결재 승인·반려 때는 호출하지 않음).

```python
apply_incoming_judgment(
    lot_id=...,  # lots.id (입고 LOT)
    result="PASS",  # "PASS" | "FAIL"
    staff_id=...,  # staff.id
    document_id=None,  # 육안검사일지 document_id (감사 기록용)
    judged_at=None,  # datetime, 생략 시 지금
    reason=None,  # 이미 판정된 LOT 의 판정을 바꿀 때 필수
)  # -> Lot
```

| 상황 | 결과 |
|---|---|
| QUARANTINE → PASS / FAIL | AVAILABLE / REJECTED |
| 같은 판정 다시 호출 | 변화 없음 (재작성완료해도 안전) |
| 판정 변경 (PASS ↔ FAIL) | `reason` 필수. 입고 외 수불(사용·조정·반품·폐기)이 생긴 LOT 은 거부 |
| 입고 LOT 이 아님 / 입고 취소된 LOT / 없는 LOT·담당자 | 거부 |

거부는 `apps.inventory.errors.InventoryError` (메시지는 사용자에게 보여줄 한국어). 호출한 문서 쪽 트랜잭션도 함께 롤백됩니다.

**입고 시 판정**: 입고 화면에서 판정을 함께 보내면 수불이 입고 트랜잭션 안에서 이 함수를 직접 호출합니다 (`ReceiptInput.judgment`, API `judgment`). 이 경우 LOT 은 처음부터 AVAILABLE / REJECTED 로 저장되고, 이후 일지 작성완료 때 같은 판정으로 호출하면 변화가 없습니다.

### `apps.inventory.ledger.stock_ledger(date_from, date_to, *, item_type=None, item_id=None, lot_id=None)`

원료수불대장(D04). 기간(양 끝 포함)의 품목별·LOT별 이월, 입출고, 누적 잔량, 기말을 계산해 `list[LedgerItem]` 반환. 원료만이면 `item_type="RAW"`.

- `LedgerItem`: `item_id`, `item_code`, `item_name`, `item_type`, `base_unit`, `lots`, 합계 `opening_e6`·`in_e6`·`out_e6`·`closing_e6`
- `LedgerLot`: `lot_id`, `lot_number`, `status`, `expiration_date`, `opening_e6`, `in_e6`, `out_e6`, `closing_e6`, `lines`
- `LedgerLine`: `movement_id`, `occurred_at`, `movement_code`, `movement_name`, `signed_quantity_e6`, `balance_e6`, `reason`, `staff_name`, `corrects_movement_id`

### `apps.inventory.ledger.stock_ledger_changes_since(since, date_from, date_to, *, item_type=None, item_id=None, lot_id=None)`

승인본 이후 대장이 바뀌었는지 확인. `since`(승인 시각) 이후 기록된 수불 중 그 기간 대장에 영향을 주는 것을 `list[LedgerChange]` 로 반환. `affects` 가 `OPENING`(기간 이전 → 이월 변경) 또는 `PERIOD`.

## 5. 수불 → 문서 호출 (문서 쪽 함수 요청)

`apps/inventory/document_bridge.py` 에서 호출합니다. 수불 트랜잭션 안에서 불리므로 문서 쪽에서 오류가 나면 입고·취소도 롤백됩니다. 지금은 빈 함수이고, 문서 쪽 함수가 정해지면 연결합니다.

| 시점 | 수불 쪽 훅 | 문서 쪽에 필요한 것 |
|---|---|---|
| 입고 화면 그리기 | — | `get_incoming_inspection_form()` — 체크리스트 항목·검증 기준 |
| 입고 등록 | `incoming_received(lot_id=...)` | `create_incoming_inspection(lot_id, answers, staff_id)` — 그날 육안검사일지에 LOT 행 추가 (작성완료·결재중이면 새 일지?) |
| 입고 취소 | `incoming_receipt_cancelled(lot_id=..., reason=..., staff_id=...)` | 육안검사일지의 해당 LOT 행 처리 방식 |
| HOLD 근거 문서 | `lot_holds.source_document_id` 에 `document_id` 저장 | 최신 내용·최신 승인본 조회 메소드 이름·반환 형태 |

## 6. 직접 확인하기

개발 DB 에서 뷰의 컬럼과 데이터를 봅니다 (`seed_master --sample` 후 입고를 몇 건 넣으면 행이 보임).

```powershell
python backend\manage.py show_view                             # 뷰 목록
python backend\manage.py show_view v_doc_incoming_lot          # 컬럼 + 10행
python backend\manage.py show_view v_doc_batch --limit 3
python backend\manage.py show_view v_doc_incoming_lot --sql    # 뷰 정의
```

뷰 정의 원본: `backend/apps/inventory/sql/0001_core.sql` (`v_doc_incoming_lot`), `sql/0002_production.sql` (`v_doc_batch`). VS Code 의 SQLite 확장이나 DB Browser for SQLite 로 `data/db/app.sqlite3` 를 열어 봐도 됩니다.

## 7. 아직 정해지지 않은 것

| 항목 | 상태 |
|---|---|
| 배치 HOLD 와 산출 LOT 전파 | 방식 결정 후 새 마이그레이션 (`lot_holds` 재정의) |
| 결재 후 과거 수불 정정 | 제안: 승인된 달은 소급 수불 금지, 정정 이동으로만 기록 → 문서 쪽 "월별 D04 승인 여부" 함수 필요 |
| 통합 입고 체크리스트 | 5절 문서 쪽 함수 형식 |
