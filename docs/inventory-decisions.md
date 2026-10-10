# 생산·수불(inventory) 결정 사항

`backend/apps/inventory` 의 동작 기준을 모았습니다. **확정**은 합의된 것, **가정**은 합의 전이지만 기본값으로 구현해 둔 것, **대기**는 결정이 나야 진행할 수 있는 것입니다. 가정이 바뀌면 "바꿀 곳"만 고치면 되도록 만들어 두었습니다. 진행 현황은 [inventory-roadmap.md](inventory-roadmap.md).

## 확정

| 항목 | 내용 | 근거 |
|---|---|---|
| 프로젝트 구조 | 한 Django 프로젝트·한 SQLite DB. 생산 코어 테이블은 `sql/0001_core.sql` 이 만들고 모델은 `managed=False` | 질의 1 |
| 공통 모델 소유 | `staff`, `lots` 등은 inventory 앱 소유. 문서 앱은 `("inventory", "0001_initial")` 에 의존하고 `inventory.Staff`, `inventory.Lot` 로 FK | 질의 1 |
| HOLD 근거 문서 | `lot_holds.source_document_id` 는 문서 **기록** PK (버전 아님). FK 는 ERD 확정 후 | 질의 2 |
| 육안검사 판정 | PASS / FAIL 두 가지. CONDITIONAL 은 이번 범위 제외 | 질의 3 |
| 로그인 | MVP 범위 아님. 처리자는 요청 본문의 `staff_id` 로 받음 | 팀 결정 |
| 입고 LOT 번호 | `{item_code}-{received:yyMMdd}{seq:A}`, 같은 품목·날짜 안에서 A→Z→AA→AB… | 팀 결정 |
| 기준정보 | 저장소에는 가상 샘플만. 실제 자료는 `data/` 아래 CSV 로 `seed_master` | CONTRIBUTING |
| 생산 테이블 이름 | 생산지시가 아닌 제조배치 중심 `production_batches` (다음 마이그레이션) | 팀 결정 |

## 가정 (기본값으로 구현, 확정 시 수정)

| 항목 | 현재 동작 | 바꿀 곳 |
|---|---|---|
| 입고 가능 품목 유형 | 원료(RAW)·포장재(PACKAGING) | `receiving.RECEIVABLE_ITEM_TYPES` |
| 지난 날짜 입고 | 그날 00:00:00 으로 기록 (그날 다른 이동보다 앞에 오도록) | `receiving._occurred_at` |
| 입고 취소 | 입고 후 사용·조정이 없을 때만. 전량 CORRECTION_OUT, LOT 상태는 그대로 | `receiving.cancel_receipt` |
| 입고 직후 LOT 상태 | QUARANTINE (판정 반영 전). 통합 입고(육안검사 동시 저장)가 붙으면 판정에 따라 바로 AVAILABLE / REJECTED | 판정 반영 개발 시 |
| FAIL 입고 처리 | 입고는 등록하고 LOT 를 REJECTED 로 둔 뒤 반품·폐기를 수불로 기록 (현업 확인 필요) | 판정 반영 개발 시 |
| 반품·폐기 후 LOT 상태 | 재고가 0 이 되면 DISPOSED. 일부만이면 상태 유지. 정정으로 재고가 되살아나면 직전 상태로 복구 | `movements._outflow_or_adjust`, `correct_movement` |
| 정정 대상 | 입고(RECEIPT)는 정정 대신 입고 취소. 정정 기록 자체는 다시 정정 불가 | `movements.NOT_CORRECTABLE` |
| 정정 일시 | 원 기록과 같은 일시 (수불대장에서 그 시점부터 바로잡힘) | `movements.correct_movement` |
| 소급 출고 | 그 시점 이후 잔량이 한 번이라도 음수가 되면 거부 | `movements._check_outflow` |
| 기초재고 | 반제품·완제품은 기존 LOT 번호 필수. 원료·포장재는 비우면 입고 규칙으로 채번 | `movements.record_opening_balance` |
| 수불대장 조회 기간 | 최대 1년 | `api.ledger_params` |
| 사용 가능 재고 | 상태 AVAILABLE 이고 미해제 HOLD 없음 (I5) | `stock.py` |

## 대기

| 항목 | 기다리는 것 | 현재 상태 |
|---|---|---|
| 문서 쪽 알림 전달 방식 | 질의 5 (이벤트 vs 직접 호출) | `document_bridge.py` 빈 함수. 페이로드는 C3 형식으로 생성 |
| 통합 입고 (육안검사 동시 저장) | 문서 쪽 `get_incoming_inspection_form()`, `create_incoming_inspection(...)` 형식 합의 | 미착수 |
| 판정 수정·결재 반려 시 처리 | 위와 함께 | 미착수 |
| `lot_holds` 문서 FK, HOLD 서비스 | 10/11 ERD, CCP 개발 시점 | 테이블만 있음 |
| 수불대장 결재·스냅샷 | 문서 쪽 담당 | 조회·CSV 만 제공 |
| BOM·제조배치·투입·CCP | 다음 마이그레이션 | 미착수 |
| 화면 | 기존 시제품 활용 여부 | API 까지 완료 |

## API 요약 (`/api/v1/inventory/`)

규칙은 `api.py` 머리말 참고. 수량은 기준 단위의 10진 문자열, 오류는 `{"error": {"message": ...}}`, POST/PATCH 는 `X-CSRFToken` 헤더 필요.

| 경로 | 메서드 | 내용 |
|---|---|---|
| `item-types/`, `movement-types/` | GET | 코드 목록 |
| `staff/`, `suppliers/`, `items/` | GET, POST | 목록(`active`, `q`, `item_type`) / 등록 |
| `staff/<id>/`, `suppliers/<id>/`, `items/<id>/` | GET, PATCH | 조회 / 수정 (코드 변경 불가) |
| `receipts/` | GET, POST | 입고 목록(`from`, `to`, `supplier_id`, `item_id`, `status`, `limit`, `offset`) / 입고 등록 |
| `receipts/<id>/`, `receipts/<id>/cancel/` | GET / POST | 입고 상세 / 입고 취소 |
| `lots/<id>/` | GET | LOT 상세 + 수불 이력 |
| `stock/lots/` | GET | LOT별 재고 (`item_type`, `item_id`, `status`, `include_empty`, `expiring_within_days`) |
| `stock/items/` | GET | 품목별 재고 (`below_minimum=1` 이면 최소재고 미달만) |
| `ledger/`, `ledger/export.csv` | GET | 원료수불대장 (`from`, `to` 필수) / CSV 내려받기 |
| `movements/opening-balance/` | POST | 기초재고 이관 |
| `movements/adjust/` | POST | 재고조정 (`direction`: IN / OUT) |
| `movements/return/`, `movements/disposal/` | POST | 공급처 반품 / 폐기 (`quantity` 생략 시 전량) |
| `movements/<id>/correct/` | POST | 정정 (`quantity` 생략 시 남은 전량) |

## 운영 명령

| 명령 | 내용 |
|---|---|
| `manage.py seed_master --sample` | 가상 기준정보 + 기본 입고 LOT 규칙 |
| `manage.py seed_master --items data/import/items.csv --encoding cp949 [--dry-run]` | 실제 기준정보 CSV 가져오기 |
| `manage.py check_inventory` | 재고·수불 정합성 점검 (문제 있으면 오류 종료) |
