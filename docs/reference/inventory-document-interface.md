# 생산·수불 ↔ 문서 연동 인터페이스

문서 앱이 생산·수불(inventory) 앱에서 쓰는 테이블·뷰·함수를 한곳에 모았습니다. 10/11 ERD 협의 반영본에 2026-10-23 생산일지 읽기 계약(0009)을 추가했습니다. 결정 근거는 [inventory-decisions.md](inventory-decisions.md).

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
| `items` | `id`, `item_code`(UNIQUE), `short_code`(LOT 약어), `name`, `item_type`, `base_unit`, `unit_weight_mg`, `origin_country`, `shelf_life_months` / `shelf_life_days`, `is_stock_managed` | `item_type`: RAW 원료 / PACKAGING 포장재 / SEMI 반제품 / FINISHED 완제품. `is_stock_managed = 0` 은 정제수 같은 재고 비관리 품목 (LOT 없음, 10/14) |
| `lots` | `id`, `lot_number`(**품목 안에서 UNIQUE**), `item_id`, `lot_kind`, `status`, `manufactured_date`, `expiration_date`, `expiration_status` | `lot_kind`: INCOMING / PRODUCED |
| `production_batches` | `id`, `batch_number`(UNIQUE), `process_type`, `item_id`, `status`, `manufactured_date`, `shift`, … | `process_type`: MANUFACTURE / PACKAGING — 10/15 부터 새 배치는 MANUFACTURE 만 (포장배치는 MVP 범위 밖, 예전 행만 PACKAGING). `manufactured_date` = 생산 시작일. `shift` 는 10/14 폐지 (열만 남고 항상 NULL) |

**LOT 번호**: 원료는 소비기한 있음이면 `LOT 약어 + 소비기한`, 없음이면 `LOT 약어 + 입고일` (0007). 포장재 `LOT 약어 + 입고일`, 구매 반제품 `입고일 + 순번` (가정). 같은 기준일이 또 생기면 `-2`, `-3`. 반제품 LOT 은 제조 시작일 + 품목별 순번 (`261014A`, `261014B`). 근무조는 10/14 폐지.
반제품 LOT 은 제품이 달라도 번호가 같을 수 있으므로 (완제품 LOT 의 품목 약어는 완제품 채번을 다룰 때 — 10/14 PM 미팅 A1) **LOT 은 `lot_id` 로 식별**하고, 화면·라벨에는 품목코드와 함께 표시합니다 (`4000001 / 261011A`). `document_ref.label` 같은 표시용 값으로 LOT 을 찾지 마세요.

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
| `quantity_e6` | 입고 등록 수량 (`_e6`) | 입고 건 없으면 NULL |
| `manufactured_date`, `expiration_date` | 제조일, 소비기한 | 있음 |
| `lot_status` | QUARANTINE / AVAILABLE / REJECTED | |
| `receipt_status` | COMPLETED / CANCELLED (입고 취소) | 입고 건 없으면 NULL |
| `subject_label` | `품목코드 품명 / LOT번호 / 입고일(또는 제조일)` 표시용 | |
| `net_quantity_e6` | 입고 수량 − 입고 정정·취소분 (10/14 추가, 0005). 취소된 입고는 0 | 입고 건 없으면 NULL |
| `expiration_status` | 소비기한 유무 KNOWN 있음 / NONE 없음 / UNKNOWN 미확인 (0007). 날짜가 없을 때 "없음"과 "미확인"을 이 값으로 구분 | 항상 있음 |

- 생산 LOT, 기초재고 이관 LOT 은 입고 건이 없어 공급처·입고일·입고 수량이 NULL
- 입고가 취소돼도 행은 남고 `receipt_status = CANCELLED`
- 입고 수량을 일부 정정하면 `quantity_e6` 는 그대로, `net_quantity_e6` 가 줄어듦 (10/14 PM 미팅 D3)

문서 쪽 요청 대비 바뀐 이름: `quantity` → `quantity_e6`, `unit` → `base_unit`, `material_kind` → `item_type` / `item_type_name`, `origin` → `origin_country`

### `v_doc_batch` — 생산일지·CCP 일지 자동 채움 (`sql/0002_production.sql`)

배치 1행씩. `production_batch_id` 로 조회.

| 컬럼 | 뜻 |
|---|---|
| `production_batch_id` | `production_batches.id` |
| `batch_number`, `process_type`, `status` | 배치 번호, MANUFACTURE / PACKAGING(예전 행만), 상태 |
| `shift` | 근무조 — 10/14 폐지, 항상 NULL (계약 때문에 열만 유지) |
| `item_id`, `item_code`, `item_name`, `item_type`, `base_unit` | 산출 품목 |
| `unit_weight_mg` | 기준단위 1개 무게(mg, NULL 가능). kg 환산: 개수 × `unit_weight_mg` ÷ 1,000,000 (예: 환 10,000개 × 4,000mg = 40kg). 문서 요청 V1 |
| `bom_id`, `bom_version` | 기준 BOM (없으면 NULL) |
| `planned_date`, `planned_quantity_e6` | 계획 (NULL 가능 — 사후 입력) |
| `manufactured_date`, `started_at`, `completed_at` | 제조일, 시작·완료 시각 |
| `output_quantity_e6` | 산출 합계 (정정 반영, `base_unit` 기준) |
| `output_lot_count`, `input_line_count` | 산출 LOT 수(서로 다른 LOT, 0006 부터 0 또는 1), 투입 줄 수 |
| `staff_name` | 작업 책임자 |
| `output_lot_number` | 배치의 산출 LOT 번호 (10/15 추가, 0006). 산출 전 NULL, 예전 다중 LOT 배치는 쉼표로 나열 |
| `subject_label` | `품목코드 품명 / 배치번호 / 제조일` 표시용 |
| `food_type` | 식품 유형 (예: 기타가공품). 품목 구분인 `item_type`과 다름. 미등록이면 NULL (0009) |
| `manufacturing_report_number` | 외부 품목제조보고번호. 미등록이면 NULL (0009) |

문서 쪽 요청 대비: `quantity_kg` 대신 `output_quantity_e6` + `base_unit` (완제품은 단위가 `개`). kg 가 필요하면 `unit_weight_mg` 로 환산

### 생산일지 추가 계약 (2026-10-23, 0009)

M8a 후속 확인(2026-10-24): 기존에 저장한 배합비가 없으므로 별도 비율 저장 필드 없이, 문서 영역에서 계산할 수 있도록 원료별 수량과 기준단위를 제공합니다. 아래 BOM 뷰의 `bom_quantity_e6`는 BOM 기준 소요량, `standard_quantity_e6`는 배치 계획량으로 환산한 기준량, `base_unit`은 해당 원료의 기준단위입니다. 문서에서는 표시 목적에 맞는 수량을 선택해 단위를 통일한 뒤 계산합니다. BOM 배합 비율을 산출할 때는 계획량 NULL·환산 올림의 영향을 받지 않는 `bom_quantity_e6`를 사용할 수 있습니다. kg/g 외 서로 환산할 근거가 없는 단위는 중량 비율로 임의 합산하지 않습니다. 비율의 분모·포함 원료·표시 자릿수는 문서 영역에서 정하며, 수불 뷰는 비율을 계산하거나 저장하지 않습니다.

기존 `v_doc_batch` 컬럼은 유지하고 끝에 두 컬럼만 추가합니다. 품목제조보고번호는 내부 품목·배치 번호로 생성하지 않는 외부 기준정보이며, NULL 허용 문자열로 저장합니다. 여러 내부 품목이 같은 번호를 가질 수 있어 UNIQUE 제약은 없습니다.

| 뷰 | 행 기준 | 역할 |
|---|---|---|
| `v_doc_batch` | 배치 1개 = 1행 | 제품·배치·계획량·정정 반영 산출량·산출 LOT·식품 유형·보고번호 |
| `v_doc_batch_bom_line` | 배치 × BOM 구성 행 = 1행 | 미투입 원료를 포함한 BOM 전체 구성과 계획 기준량 |
| `v_doc_batch_usage` | 투입 기록 1개 = 1행 | 실제 원료·LOT·원래 BOM 행 연결·정정 반영 수량·투입일 |

모두 `production_batch_id`로 조회합니다. 문서 영역의 `sources.py` 수정과 일지 반영은 문서 담당 영역에서 진행합니다. 뷰는 현재 기준정보·수불을 조회하므로, 작성완료/승인본의 스냅샷 보존은 문서 영역의 책임입니다.

#### `v_doc_batch_bom_line`

| 컬럼 | 뜻 |
|---|---|
| `production_batch_id`, `bom_id`, `bom_version` | 배치에 실제 연결된 BOM 버전. 최신 활성 BOM으로 바꿔 읽지 않음 |
| `bom_line_id`, `line_no` | 원료 행 연결 키·저장된 BOM 순서 |
| `item_id`, `item_code`, `item_name` | BOM 구성 품목 (원료 외 반제품·포장재도 구조상 포함 가능) |
| `origin_country`, `base_unit`, `is_stock_managed` | 품목 원산지(NULL 가능)·원료 기준단위·재고 관리 여부 |
| `bom_base_quantity_e6` | BOM 기준 생산량. 산출 품목 단위이며, 그 단위는 `v_doc_batch.base_unit` |
| `bom_quantity_e6` | BOM 기준 생산량당 원료 소요량. 이 행의 `base_unit` 기준 |
| `planned_quantity_e6` | 배치 계획량. 산출 품목 단위, NULL 가능 |
| `standard_quantity_e6` | 원료 소요량 × 계획량 ÷ BOM 기준 생산량. 원료 기준단위의 소수점 6자리까지 올림. 계획량 NULL이면 NULL |

투입·산출 여부와 무관하게 모든 BOM 행이 나옵니다. 실산출 후에도 **계획량 기준**을 유지합니다. BOM이 없는 배치는 행이 없습니다. 정제수 등 `is_stock_managed = 0`인 구성도 포함하지만 실제 사용량은 수불에서 집계할 수 없으므로 문서에서 직접 입력합니다. SQL 결과 순서는 자동 보장되지 않으며 조회에서 `ORDER BY line_no`를 명시합니다.

#### `v_doc_batch_usage`

| 컬럼 | 뜻 |
|---|---|
| `production_batch_id`, `usage_id` | 배치·개별 투입 기록 키 |
| `bom_line_id`, `line_no` | 원래 BOM 행 연결·순서. 과거 미연결 기본 원료는 배치 BOM의 동일 품목으로 매칭; 매칭 불가 시 NULL |
| `bom_item_id`, `bom_item_code`, `bom_item_name`, `bom_base_unit` | 원래 BOM 원료와 그 기준단위. 연결이 없으면 NULL |
| `item_id`, `item_code`, `item_name`, `origin_country` | 실제 투입 원료 (대체 시 BOM 원료와 다름). 원산지 NULL 가능 |
| `base_unit`, `is_stock_managed` | 실제 투입 품목의 기준단위·재고 관리 여부 |
| `lot_id`, `lot_number` | 실제 투입 LOT. 식별에는 번호 대신 id 사용 |
| `quantity_e6`, `net_quantity_e6` | 원 투입량·정정 반영 순투입량. **실제 투입 품목의 기준단위** 기준 |
| `stock_movement_id`, `occurred_at`, `input_date` | 원 투입 수불 키·발생 일시(KST)·투입일(YYYY-MM-DD). 등록 시각이 아님 |

전량 정정된 행도 `net_quantity_e6 = 0`으로 남습니다. 문서의 최초 작업일은 **`net_quantity_e6 > 0`인 행만** 대상으로 BOM 행별 `MIN(input_date)`를 사용합니다. 미투입 원료는 투입 뷰에 행이 없으며, BOM 뷰를 기준으로 연결해 표시합니다. 여러 LOT·여러 대체 원료 투입은 여러 행이므로 BOM 기준량을 중복 합산하지 않도록 주의합니다. 대체 원료의 단위가 kg/g으로 다르면 문서에서 원래 BOM 원료 단위로 환산 후 사용량을 합산합니다. 재고 비관리 원료의 미집계는 미투입 0과 구분합니다.

```sql
SELECT * FROM v_doc_batch_bom_line
WHERE production_batch_id = ? ORDER BY line_no;

SELECT * FROM v_doc_batch_usage
WHERE production_batch_id = ? ORDER BY input_date, usage_id;

SELECT bom_line_id, MIN(input_date) AS first_input_date
FROM v_doc_batch_usage
WHERE production_batch_id = ? AND net_quantity_e6 > 0
GROUP BY bom_line_id;
```

보고번호는 품목 API의 `manufacturing_report_number`로 등록·수정하거나 `seed_master --items` CSV의 같은 컬럼으로 가져올 수 있습니다. 빈 문자열은 NULL로 저장합니다. 해당 컬럼이 없는 기존 CSV는 등록된 보고번호를 보존하며, 컬럼을 포함하고 값을 비우면 NULL로 지웁니다. 품목 전용 화면의 신규 입력 UI는 이번 작업에 포함하지 않습니다.

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

### 보류 (`apps.inventory.holds`, 0003 — 2026-10-24 운영 기준 반영)

제조배치 보류 해제는 현업의 **대안 방식**으로 결정됐습니다: 개선조치 → 담당자 확인 및 수동 해제, 문서 결재는 별도로 진행합니다. 결재 완료는 해제의 필수 조건이 아닙니다.

현재 범위에서는 문서 쪽 CCP 이탈 통보를 전제로 자동 보류·자동 해제를 연결하지 않습니다. 담당자가 수불·생산에서 보류를 직접 등록하고, 개선조치 확인 후 해제 사유를 기록해 수동 해제합니다. 개선조치 확인은 운영 절차이며 문서 상태를 API로 검증하지 않습니다. 제조배치 상세에서 보류 등록·해제·이력 조회를 제공하며, 해제 화면에서는 개선조치 확인 체크와 사유 입력을 요구합니다. 담당자·처리 시각·사유는 기존 보류 기록과 감사 로그에 남습니다.

```python
hold_batch(batch_id=..., source_type="MANUAL", reason="금속검출 이탈 확인", staff_id=...)
hold_lot(lot_id=..., source_type="MANUAL", reason=..., staff_id=...)
release_hold(hold_id=..., disposition="RELEASE", reason=..., staff_id=...)
```

- 한 제조배치의 산출 LOT 은 하나 (10/15, 0006). 산출을 나눠 입력하면 `production_outputs` 행은 늘지만 `lot_id` 는 같음
- 보류 테이블 하나(`holds`)에 대상은 LOT 또는 배치. 배치를 보류하면 그 배치의 산출 LOT 에 전파 보류가 생기고, 보류 중인 배치는 시작·투입·산출·완료 불가
- `source_type`: CCP / INCOMING_INSPECTION / FINISHED_INSPECTION 은 `source_document_id`(document_id) 필수, MANUAL 은 선택
- 문서와 독립적으로 등록하는 보류는 MANUAL을 사용하고 실제 이탈 내용은 사유에 기록. 기존 CCP 유형의 근거 문서 필수 규칙은 유지하며, 근거 문서 연결과 결재 완료 여부는 별개
- `disposition`: RELEASE / REWORK / RETURN / DISPOSE. 처분은 기록이고 반품·폐기 재고 차감은 수불 이동으로 따로
- 배치 보류 해제 시 열린 전파 보류도 같이 해제. LOT 별로 먼저 해제 가능
- 이미 열린 보류가 있으면 새로 만들지 않고 그 보류를 돌려줌
- 화면 표시: 일반 계획 배치에는 보류 UI 없음. 일반 진행 배치는 하단 ‘보류 관리’를 펼쳐 등록. 보류 중에는 상단 경고·해제 기능을 표시하고 해제 후에는 상단에 접힌 이력을 표시. 기존에 계획 상태에서 등록한 활성 보류는 해제할 수 있도록 표시 유지

## 5. 수불 → 문서 호출

`apps/inventory/document_bridge.py` 에서 문서 쪽 함수(`apps.doc_requirements.services`)를 부릅니다. 계약은 문서 쪽 [document-inventory-interface.md](document-inventory-interface.md). 수불 트랜잭션 안에서 수불 쓰기를 먼저 한 뒤 부르므로, 문서 쪽 오류(`ApiError`)가 나면 입고·취소·생산 시작도 롤백됩니다. API 응답은 문서 쪽 상태 코드와 `error.code`(예: `VALIDATION_ERROR`, `TEMPLATE_NOT_FOUND`)를 그대로 돌려줍니다.

| 시점 | 수불 쪽 훅 | 문서 쪽 함수 |
|---|---|---|
| 입고 등록 | `incoming_received(lot_id=..., staff_id=..., inspection=None)` | `require_for_lot(staff_id, lot_id, inspection)` — LOT 마다 D01·D02·D03 (작성중). `inspection` 은 새 D03 에만 채움 |
| 입고 등록 + 육안검사 | `ReceiptInput.inspection` / API `inspection` | 문서 생성 뒤 판정을 수불이 반영(`apply_incoming_judgment`, `document_id` = D03). `judgment` 를 안 주면 `inspection.verdict` 를 판정으로 씀. 둘 다 주면 같아야 함 |
| 입고 취소 전 | `receipt_cancel_blockers(lot_id=...)` | `docs_for_lot(lot_id)` — LOT 문서가 `submitted`·`approved`·`correcting`(정정 중) 이면 취소 거부. 작성중·작성완료·반려는 취소 가능 |
| 입고 취소 | `incoming_receipt_cancelled(lot_id=..., reason=..., staff_id=...)` | `delete_lot_documents(staff_id, lot_id)` — 같은 트랜잭션에서 입고 서류 소프트 딜리트. 오류 시 입고 취소도 롤백 |
| HOLD 근거 문서 | `holds.source_document_id` 에 `document_id` 저장 (0003 에서 `lot_holds` → `holds`) | 현재 전용 조회 함수 `get_source_document`는 미구현. 문서 공개 조회 서비스를 사용하고 보류 서비스는 결재 상태를 조회하지 않음 |
| 생산 시작 (계획 없이 바로 완료한 경우는 완료 때) | `batch_started(batch_id=..., staff_id=...)` | `require_for_batch(staff_id, batch_id)` — 제조 배치면 CCP-1P·2B·3P 일지 (ERD v7 ③) |

주의

- 문서 양식(D01·D02·D03, CCP-1P·2B·3P)이 DB 에 있어야 입고·생산 시작이 됩니다. 없으면 `TEMPLATE_NOT_FOUND` 로 입고가 롤백됩니다. 개발 DB 는 `seed_dev_p4`·`seed_dev_workflow` 가 넣고, 운영 DB 기본 양식은 `install_document_templates`로 등록합니다. 실제 기준·활성 상태는 설치 시 확인합니다.
- 담당자(`staff_id`)는 문서 쪽에서도 활성 직원이어야 합니다(`INVALID_STAFF`).
- 문서 쪽 명세의 `create_incoming_inspection`·`get_incoming_inspection_form`·`get_source_document`·`ledger_approved_until` 은 아직 코드에 없습니다. 지금 연결한 것은 실제로 있는 `require_for_lot`·`require_for_batch`·`docs_for_lot`·`docs_for_batch`·`delete_lot_documents`입니다. 수불대장 잠금(`ledger_approved_until` 이하 날짜의 수불 등록·정정 막기, 문서 쪽 4장 요청)은 **이번 범위에서 제외**합니다 — 10/14 PM 미팅 D3(결재 여부와 무관하게 소급 수정 허용, 기간 잠금 없음)·D4(수불대장은 시스템 결재 없이 출력까지만). 함수가 생겨도 수불은 부르지 않습니다.

## 6. 직접 확인하기

개발 DB 에서 뷰의 컬럼과 데이터를 봅니다 (`seed_master --sample` 후 입고를 몇 건 넣으면 행이 보임).

```powershell
python backend\manage.py show_view                             # 뷰 목록
python backend\manage.py show_view v_doc_incoming_lot          # 컬럼 + 10행
python backend\manage.py show_view v_doc_batch --limit 3
python backend\manage.py show_view v_doc_incoming_lot --sql    # 뷰 정의
```

최신 뷰 정의: `backend/apps/inventory/sql/0007_expiration_status.sql` (`v_doc_incoming_lot`), `sql/0009_document_production_sources.sql` (`v_doc_batch`, `v_doc_batch_bom_line`, `v_doc_batch_usage`). VS Code 의 SQLite 확장이나 DB Browser for SQLite 로 `data/db/app.sqlite3` 를 열어 봐도 됩니다.

## 7. 아직 정해지지 않은 것

결재 후 과거 수불 정정은 정해짐 — 10/14 PM 미팅 D3·D4: 소급 수정 허용, 기간 잠금 없음, 수불대장은 출력까지만. 문서 쪽 수불대장 잠금 요청은 이번 범위에서 제외(5절).

| 항목 | 상태 |
|---|---|
| 통합 입고 체크리스트 | 입고 + 육안검사 값 저장은 연결 완료(5절). 화면 항목 조회 `get_incoming_inspection_form()`은 미구현 설계 항목이며 현재 입고는 기존 화면과 `require_for_lot`을 사용 |
