# ERD — 뷰

DB 뷰 10개입니다. 모두 수불 쪽 SQL 파일(`backend/apps/inventory/sql/`)이 만듭니다. 문서 쪽 앱은 수불 표를 직접 읽지 않고 **`v_doc_*` 뷰 4개로만** 읽습니다 — 이 4개가 두 영역 사이의 계약입니다.

> 현재 기준 2026-10-27 · 기준 코드 `2234f02`(main) · 컬럼은 실제 스키마에서 뽑음. 뷰 정의 SQL은 [schema.sql](schema.sql)

## 문서 쪽이 읽는 뷰 (계약)

컬럼 이름·뜻을 바꾸면 문서 쪽 코드가 깨집니다. 바꿀 때는 [수불 → 문서 인터페이스](../../reference/inventory-document-interface.md)와 함께 고치고 양쪽 담당이 확인합니다.

<a id="v_doc_incoming_lot"></a>
### `v_doc_incoming_lot`

| | |
|---|---|
| 내용 | 입고 LOT 한 줄 = 문서 머리·D03 입고 정보에 쓰는 값 |
| 읽는 곳 | `doc_requirements/sources.py` · `inventory/document_bridge.py` |
| 만드는 곳 | `0001_core.sql` → `0005`·`0007`에서 다시 만듦 |
| 컬럼 | `lot_id`, `lot_number`, `lot_kind`, `item_id`, `item_code`, `item_name`, `item_type`, `item_type_name`, `base_unit`, `origin_country`, `supplier_name`, `supplier_lot_number`, `received_date`, `quantity_e6`, `manufactured_date`, `expiration_date`, `lot_status`, `receipt_status`, `subject_label`, `net_quantity_e6`, `expiration_status` |

<a id="v_doc_batch"></a>
### `v_doc_batch`

| | |
|---|---|
| 내용 | 제조 배치 한 줄 = CCP 일지·생산일지 기본정보 |
| 읽는 곳 | `doc_requirements/sources.py` · `production_log/logbook.py` · `inventory/document_bridge.py` |
| 만드는 곳 | `0002_production.sql` → `0006`·`0009` |
| 컬럼 | `production_batch_id`, `batch_number`, `process_type`, `status`, `shift`, `item_id`, `item_code`, `item_name`, `item_type`, `base_unit`, `unit_weight_mg`, `bom_id`, `bom_version`, `planned_date`, `planned_quantity_e6`, `manufactured_date`, `started_at`, `completed_at`, `output_quantity_e6`, `output_lot_count`, `input_line_count`, `staff_name`, `subject_label`, `output_lot_number`, `food_type`, `manufacturing_report_number` |

<a id="v_doc_batch_bom_line"></a>
### `v_doc_batch_bom_line`

| | |
|---|---|
| 내용 | 배치의 BOM 줄 = 생산일지 원료칭량(비율·투입량) |
| 읽는 곳 | `doc_requirements/sources.py` |
| 만드는 곳 | `0009_document_production_sources.sql` |
| 컬럼 | `production_batch_id`, `bom_id`, `bom_version`, `bom_line_id`, `line_no`, `item_id`, `item_code`, `item_name`, `origin_country`, `base_unit`, `is_stock_managed`, `bom_base_quantity_e6`, `bom_quantity_e6`, `planned_quantity_e6`, `standard_quantity_e6` |

<a id="v_doc_batch_usage"></a>
### `v_doc_batch_usage`

| | |
|---|---|
| 내용 | 배치의 실제 투입 = 생산일지 사용량·대체 원료·투입일 |
| 읽는 곳 | `doc_requirements/sources.py` |
| 만드는 곳 | `0009_document_production_sources.sql` |
| 컬럼 | `production_batch_id`, `usage_id`, `bom_line_id`, `line_no`, `bom_item_id`, `bom_item_code`, `bom_item_name`, `bom_base_unit`, `item_id`, `item_code`, `item_name`, `origin_country`, `base_unit`, `is_stock_managed`, `lot_id`, `lot_number`, `quantity_e6`, `net_quantity_e6`, `stock_movement_id`, `occurred_at`, `input_date` |

## 수불 쪽 안에서 쓰는 뷰

| 뷰 | 내용 | 읽는 곳 | 만드는 곳(`inventory/sql/`) |
|---|---|---|---|
| `v_lot_availability` | LOT 사용 가능 여부(활성 보류 수 포함) | `inventory/holds.py`·`stock.py`·`production.py` | `0001`·`0003` |
| `v_stock_ledger` | 원료수불대장 줄(잔량 누적) | `inventory/ledger.py`·`sql_runner.py` | `0001`·`0002` |
| `v_batch_usages` | 배치별 투입 | `inventory/production.py` | `0002` |
| `v_batch_outputs` | 배치별 산출 | `inventory/production.py` | `0002` |
| `v_lot_trace` | LOT 추적(원료 LOT → 산출 LOT, 깊이) | 앱 코드에서 안 씀(조회용) | `0002` |
| `v_inventory_mismatch` | 현재고와 수불 합계가 다른 LOT | `check_inventory` 관리 명령 | `0001` |

- 수량 컬럼(`*_e6`)은 백만 배 정수입니다.
- 생산일지는 수불 값을 못 읽으면(뷰가 없거나 오류) 연동 실패로 안내하고 작성완료를 막습니다(`SOURCE_UNAVAILABLE` · `PLG_LINKED_UNAVAILABLE`).
