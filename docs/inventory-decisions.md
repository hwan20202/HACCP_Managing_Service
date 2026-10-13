# 생산·수불(inventory) 결정 사항

`backend/apps/inventory` 의 동작 기준을 모았습니다. **확정**은 합의된 것, **가정**은 합의 전이지만 기본값으로 구현해 둔 것, **대기**는 결정이 나야 진행할 수 있는 것입니다. 가정이 바뀌면 "바꿀 곳"만 고치면 되도록 만들어 두었습니다. 진행 현황은 [inventory-roadmap.md](inventory-roadmap.md), 문서 앱 연동 명세는 [inventory-document-interface.md](inventory-document-interface.md).

## 확정

| 항목 | 내용 | 근거 |
|---|---|---|
| 프로젝트 구조 | 한 Django 프로젝트·한 SQLite DB. 테이블은 `sql/0001_core.sql`·`sql/0002_production.sql` 이 만들고 모델은 `managed=False` | 질의 1 |
| 공통 모델 소유 | `staff`, `lots`, `items`, `production_batches` 는 inventory 앱 소유. 문서 앱은 `("inventory", "0002_production")` 에 의존하고 `inventory.Staff`·`Lot`·`Item`·`ProductionBatch` 로 FK. 문서 쪽 임시 `staff` 는 수불 스키마로 옮길 예정 (문서는 staff id 만 사용) | 질의 1, 10/11 ERD |
| HOLD 근거 문서 | `holds.source_document_id` = 문서 `document.document_id` (버전·스냅샷 아님). 마이그레이션 순환을 피해 FK 미설정. 최신 내용·승인본은 문서 쪽 메소드로 조회 | 질의 2, 10/11 ERD |
| 개선조치 | 문서 영역 내부(`deviation_action`)에서만 관리. 수불은 문서 참조까지만 → `lot_holds.deviation_action_id` 삭제 | 10/11 ERD |
| 문서 ↔ 업무 대상 | 문서 쪽 `document_ref` 테이블이 `lot_id`·`production_batch_id`·`item_id` 를 종류별 FK 로 가짐 (`subject_type`/`subject_id` 방식 폐기) | 10/11 ERD |
| LOT 번호 형식 | BOM v4 멘토안 채택. 원료·포장재 = LOT 약어 + 입고일 (`AHN261005`), 반제품 = 제조일 + 품목별 생산 순번 (`261013A`, 근무조와 별개), 완제품 = 제조일 + 근무조 (`261011A`, 완제품코드와 함께 읽음). LOT 약어는 `items.short_code` (A** 원료 / B** 반제품 / C** 포장재), 근무조는 `production_batches.shift` | 10/12, BOM v4 (10/5 멘토 피드백) |
| LOT 번호 유일성 | 품목 안에서만 UNIQUE (`UNIQUE(item_id, lot_number)`). 완제품 LOT 은 제품이 달라도 같은 날·근무조면 번호가 같음 → LOT 식별은 `lots.id`, 사람이 읽을 때는 품목코드 + LOT 번호. (10/12 오전 전체 UNIQUE 로 바꿨다가 멘토안 채택으로 되돌림) | 10/12 |
| 근무조 | A조·B조 두 개, 둘 다 주간 (`production_batches.shift`, 완제품 LOT 끝 글자). DB CHECK 는 'C' 도 허용하지만 예비로 두고 서비스·API 는 A/B 만 받음 | 10/13, BOM v4 확인필요 17 (기존 답변) |
| LOT 상태 | 품질 판정만: QUARANTINE / AVAILABLE / REJECTED. 소진·폐기(CONSUMED / DISPOSED) 삭제 — 재고 유무는 `inventory`, 비운 경위는 수불 이동이 나타냄 | 10/12 |
| 문서용 뷰 형식 | 이름·행 범위는 문서 쪽 요청에 맞추고 수량·단위·코드는 수불 규칙 유지. `v_doc_incoming_lot` 은 모든 LOT (입고 정보는 LEFT JOIN, `lot_kind`·`item_id`·`item_type_name`·`origin_country` 추가). `v_doc_batch` 는 `production_batch_id`·`status` 로 이름 변경, 수량은 `output_quantity_e6` + `base_unit` (kg 아님) | 10/12 |
| `domain_event_inbox` | 삭제 (문서 이벤트를 받지 않음). `audit_logs.source_event_id` 도 삭제, `staff_id` 필수 | 10/11 ERD |
| 육안검사 판정 | PASS / FAIL 두 가지. CONDITIONAL 은 이번 범위 제외 | 질의 3 |
| 로그인 | MVP 범위 아님. 처리자는 요청 본문의 `staff_id` 로 받음 | 팀 결정 |
| 기준정보 | 저장소에는 가상 샘플만. 실제 자료는 `data/` 아래 CSV 로 `seed_master` | CONTRIBUTING |
| 생산 테이블 이름 | 생산지시가 아닌 제조배치 중심 `production_batches` (다음 마이그레이션) | 팀 결정 |
| 입고 LOT 분리 | 같은 날 같은 원료라도 입고 건별 별도 LOT 허용 (성적서가 다를 수 있음) | 10/7 현업 |
| 원산지 | 원산지가 다르면 별도 품목코드 | 10/7 현업 |
| 부적합 원료 | 육안검사 FAIL 은 전량 반품 (수불 기록 방식은 대기) | 10/7 현업 |
| 생산 기록 시점 | 작업 종료 후 사후 입력 중심 (실시간 MES 아님) | 9/30 현업 |
| BOM vs 실제 투입 | 표준 소요량과 실제 투입량은 별도 기록 | 9/30 현업 |
| 다단계 BOM | 원료 → 반제품 → 완제품. 반제품도 판매·재투입 가능, 품목 유형으로 기능 제한 안 함 | 10/7 멘토링 |
| 완제품 재투입 | 자체 생산품이 다른 제품의 원료가 될 수 있음 (다단계 추적 필요) | 10/7 현업 |
| 보관·출고 단위 | 보관 박스·출고 포장 단위가 달라도 새 LOT 아님. 환은 개수 단위 차감 | 10/7 현업 |
| 포장 규격 | 10g·100g·1kg·10kg 등 규격이 달라도 같은 제품·같은 품목코드. 재고는 품목 기준 단위로 차감, 규격별 포장재 사용량은 실제 투입으로 기록 | 10/7 현업 |
| 출하·고객 반품 | MVP 범위 밖 (생산 이력·HACCP 중심). `SHIPMENT`, `CUSTOMER_RETURN` 이동 유형은 스키마에만 둠 | 팀 결정 |
| CCP 영향 범위 | 제조배치 단위로 판단·보류. 배치 없는 독립 점검도 있음 | 10/7 현업 |
| 소급 작성 | 전날 날짜로 작성·수정 허용 | 10/7 현업 |
| 문서 연동 방식 | 앱 간 직접 함수 호출, 식별자만 전달하고 문서 쪽이 조회. 입고 문서는 `lot_id` 로 `v_doc_incoming_lot`, 원료수불대장(D04)은 `ledger.stock_ledger()` (이월·입출고·누적·기말 계산 포함) | 질의 5 |
| `domain_event` | 문서 앱의 외부 알림 API 용 Outbox. 앱 간 데이터 전달 용도 아님. 수불은 쓰지 않음 | 질의 5 |
| 승인본 보존 | 문서 쪽이 결재 시점 스냅샷 보존. 수불은 변경 감지 조회(`stock_ledger_changes_since`) 제공 | 질의 5 |
| 판정 반영 시점 | 입고 화면에서 판정을 함께 보내면 입고 트랜잭션 안에서 바로 반영 (커밋 시 AVAILABLE / REJECTED). 미확정이면 QUARANTINE 으로 저장하고, 육안검사일지 작성완료 시 문서 앱이 `judgment.apply_incoming_judgment()` 호출. 결재 승인·반려는 LOT 상태 무관 | 질의 3, 10/10 협의 |
| FAIL 입고 | 입고는 등록하고 LOT 를 REJECTED 로 둔 뒤 전량 반품을 수불로 기록 (PM 확인 대기) | 10/10 협의 |

## 가정 (기본값으로 구현, 확정 시 수정)

| 항목 | 현재 동작 | 바꿀 곳 |
|---|---|---|
| 배치 번호 | `B-{품목코드}-{제조일 yyMMdd}{A,B..}` (10/11 미팅 A4 제안) | `production._next_batch_number` |
| 산출 LOT 상태 | 바로 AVAILABLE (완제품 실험·출하 검사 흐름은 아직 없음) | `production.add_output` |
| 산출 LOT 소비기한 | 입력값, 없으면 배치 제조일 + 품목 소비기한(개월 또는 일, 아래 행) | `production.add_output` |
| 보류 구조 | 10/11 A1 '다' 안: `holds` 테이블 하나(LOT 또는 배치). 배치 보류 → 산출 LOT 전파(PROPAGATED), 보류 중 배치는 투입·산출 불가(완료는 가능), 배치 보류 해제 시 열린 전파 보류도 같은 처분으로 해제, LOT 별 먼저 해제 가능. 근거 필요 사유는 `source_document_id` 필수. 이미 쓰인 하위 LOT(다음 배치 투입분)으로는 전파 안 함 | `holds.py`, `sql/0003_holds.sql` |
| 소비기한 계산 | `items.shelf_life_months`(개월, 제조방법설명서 "제조일로부터 24개월") 또는 `shelf_life_days`(일) 중 하나. 제조일 + 개월, 같은 날짜(말일은 그 달 마지막 날). 표시일이 하루 전인지 PM 확인 대기 | `shelf_life.END_DAY_OFFSET` |
| 투입 가능 LOT | AVAILABLE·보류 없음·투입일 기준 소비기한 안 지남·산출 품목과 다른 품목. 소급 투입은 그 시점 이후 잔량 검사 | `production.add_usage` |
| 배치 완료 | 산출(정정 반영) 1건 이상 필요. 계획 상태에서 바로 완료 가능(사후 입력) | `production.complete_batch` |
| 배치 취소 | 계획·진행 중이고 투입·산출이 정정으로 모두 0일 때만. 완료된 배치는 정정으로 처리 | `production.cancel_batch` |
| 입고 가능 품목 유형 | 원료(RAW)·포장재(PACKAGING) | `receiving.RECEIVABLE_ITEM_TYPES` |
| 지난 날짜 입고 | 그날 00:00:00 으로 기록 (그날 다른 이동보다 앞에 오도록) | `receiving._occurred_at` |
| 입고 취소 | 입고 후 사용·조정이 없을 때만. 전량 CORRECTION_OUT, LOT 상태는 그대로 | `receiving.cancel_receipt` |
| FAIL 입고 처리 | 판정 함수는 상태(REJECTED)만 바꾸고, 반품은 `return_to_supplier` 별도 호출 (상태는 REJECTED 유지) | `judgment.py` |
| 판정 변경 | 같은 판정 재전송은 무시. 바꾸려면 사유 필수. PASS → FAIL 은 RECEIPT 외 이동이 없을 때만, FAIL → PASS 는 반품·폐기 전만 | `judgment.apply_incoming_judgment` |
| 변경 감지 조건 | 승인 시각 이후(같은 초 포함) 등록, 발생 일시가 기간 종료일 이전. 기간 전이면 이월 영향(OPENING), 기간 안이면 PERIOD. LOT·품목 정보 변경은 미포함 | `ledger.stock_ledger_changes_since` |
| 정정 대상 | 입고(RECEIPT)는 정정 대신 입고 취소. 정정 기록 자체는 다시 정정 불가 | `movements.NOT_CORRECTABLE` |
| 정정 일시 | 원 기록과 같은 일시 (수불대장에서 그 시점부터 바로잡힘) | `movements.correct_movement` |
| 소급 출고 | 그 시점 이후 잔량이 한 번이라도 음수가 되면 거부 | `movements._check_outflow` |
| 기초재고 | 반제품·완제품은 기존 LOT 번호 필수. 원료·포장재는 비우면 입고 규칙으로 채번 | `movements.record_opening_balance` |
| LOT 약어 없는 품목 | 원료·포장재는 `short_code` 가 없으면 입고·채번 거부 (기준정보에 약어 필수) | `lot_numbers.render` |
| 수불대장 조회 기간 | 최대 1년 | `api.ledger_params` |
| 사용 가능 재고 | 상태 AVAILABLE 이고 미해제 HOLD 없음 (I5) | `stock.py` |

## 대기

| 항목 | 기다리는 것 | 현재 상태 |
|---|---|---|
| 문서 쪽 훅 내용 | 문서 앱 함수 제공 | `document_bridge.incoming_received(lot_id)`, `incoming_receipt_cancelled(lot_id, reason, staff_id)` — 지금은 아무것도 안 함 |
| 통합 입고 (육안검사 동시 저장) | 문서 쪽 `get_incoming_inspection_form()`, `create_incoming_inspection(...)` 형식 합의 | 판정 동시 반영(`ReceiptInput.judgment`)은 완료. 체크리스트 저장은 문서 함수 대기 |
| CCP 이탈 보류 연결 | 문서 쪽이 이탈 기록 때 `hold_batch` 를 부를지, 해제 조건(개선조치 완료·근거 문서 승인) | 수불 함수·API 준비됨 (`holds.py`, `/holds/`) |
| 결재 후 과거 수불 정정 | 승인된 달의 소급 수불을 막고 정정 이동으로만 받을지 (기간 잠금 안), 문서 쪽 "월별 D04 승인 여부" 함수 필요 | 미정 (10/11 ERD Q5-3) |
| 수불대장 결재·스냅샷 | 문서 쪽 담당 | 조회·CSV 만 제공 |
| BOM·제조배치·투입 서비스, CCP | 생산 서비스 개발 | 생산 서비스·API 구현 완료. CCP 문서 연동은 문서 브랜치 병합 후 협의 |
| 화면 | 기존 시제품 활용 여부 | API 까지 완료 |
| 같은 날 같은 품목 두 번 (BOM v4 확인필요 7·22·23) | PM 확인: 순번을 붙일지, 근무조로 나눌지 | 반제품은 v6.1 기준 A/B/C 생산 순번 (`{seq:A}`). 원료·포장재·완제품은 기존 규칙 유지, PM 확인 후 변경 |
| 품목코드 재정리 | 7자리, 맨 앞 1 원료·2 포장재·3 반제품·4 완제품. 기존 4코드 중 반제품은 3코드로, 완제품 4코드 새로 받음 | 코드는 TEXT 로 저장만 함. 유형은 `item_type` 열이 결정(코드 앞자리와 무관) |
| 반제품·완제품 겸용 | 같은 배치를 3코드(투입용)·4코드(판매용)로 나눌 때 LOT 연결 방법 | 한 배치는 한 산출 품목의 여러 LOT만 생성 가능. 제조배치에서 3코드 산출 → 포장배치에 투입 → 4코드 산출 |
| 원료수불대장 출력 | 기존 양식(`data/reference/slack-2026-10/원료수불대장.xlsx`): 원료별 시트, 입고일·입고처·입고(kg)·출고일자·출고(kg)·재고(kg)·투입 제품명·비고·육안 | `stock_ledger()` 로 계산 가능. 투입 제품명은 0002 생산 투입 연결 후, 양식 맞춘 출력은 화면 작업 때 |
| 생산 공정 단계 | 생산일지는 칭량→분쇄→쇳가루 제거→혼합·제환→건조→내포장→금속검출→외포장, 단계별 작업일·적합 여부. 배치가 여러 날에 걸침 | 0002 초안은 배치 시작·종료만. 단계 기록은 문서(생산일지) 쪽인지 확인 |

## API 요약 (`/api/v1/inventory/`)

규칙은 `api.py` 머리말 참고. 수량은 기준 단위의 10진 문자열, 오류는 `{"error": {"message": ...}}`, POST/PATCH 는 `X-CSRFToken` 헤더 필요.

| 경로 | 메서드 | 내용 |
|---|---|---|
| `item-types/`, `movement-types/` | GET | 코드 목록 |
| `staff/`, `suppliers/`, `items/` | GET, POST | 목록(`active`, `q`, `item_type`) / 등록 |
| `staff/<id>/`, `suppliers/<id>/`, `items/<id>/` | GET, PATCH | 조회 / 수정 (코드 변경 불가) |
| `receipts/` | GET, POST | 입고 목록(`from`, `to`, `supplier_id`, `item_id`, `status`, `limit`, `offset`) / 입고 등록 (`judgment`: PASS / FAIL, 생략 시 검사대기) |
| `receipts/<id>/`, `receipts/<id>/cancel/` | GET / POST | 입고 상세 / 입고 취소 |
| `lots/<id>/` | GET | LOT 상세 + 수불 이력 |
| `lots/<id>/judgment/` | POST | 입고 육안검사 판정 반영 (`result`: PASS / FAIL, 변경 시 `reason`) |
| `stock/lots/` | GET | LOT별 재고 (`item_type`, `item_id`, `status`, `include_empty`, `expiring_within_days`) |
| `stock/items/` | GET | 품목별 재고 (`below_minimum=1` 이면 최소재고 미달만) |
| `ledger/`, `ledger/export.csv` | GET | 원료수불대장 (`from`, `to` 필수) / CSV 내려받기 |
| `ledger/changes/` | GET | 승인 이후 변경 감지 (`since`, `from`, `to` 필수) |
| `movements/opening-balance/` | POST | 기초재고 이관 |
| `movements/adjust/` | POST | 재고조정 (`direction`: IN / OUT) |
| `movements/return/`, `movements/disposal/` | POST | 공급처 반품 / 폐기 (`quantity` 생략 시 전량) |
| `movements/<id>/correct/` | POST | 정정 (`quantity` 생략 시 남은 전량) |
| `batches/` | GET, POST | 배치 목록(`status`, `process_type`, `item_id`, `from`, `to`=제조일·계획일, `limit`, `offset`) / 등록(`item_id`, `process_type`, `staff_id`, 선택 `planned_date`·`planned_quantity`·`manufactured_date`·`shift`·`bom_id`·`notes`) |
| `batches/<id>/` | GET | 배치 상세: 투입·산출(정정 반영 순수량), BOM 표준 대비 실제(`bom_check`) |
| `batches/<id>/start/`, `complete/`, `cancel/` | POST | 시작(`shift`·`manufactured_date` 지정 가능) / 완료 / 취소(`reason` 필수) |
| `batches/<id>/usages/`, `outputs/` | POST | 투입(`lot_id`, `quantity`, `bom_line_id` 선택) / 산출(`quantity`, `lot_number`·`expiration_date` 선택). `idempotency_key` 필수 |
| `batches/fefo/` | GET | 투입 LOT 추천 (`item_id`, `quantity`, `on_date`) — 소비기한 빠른 순, 부족분 `shortfall` |
| `boms/` | GET | BOM 조회 (`item_id`, `include_inactive`) — 등록은 데이터 이관으로 |
| `holds/` | GET, POST | 보류 목록(`open`, `lot_id`, `batch_id`, `parent_hold_id`) / 보류(`lot_id` 또는 `batch_id`, `source_type`, `reason`, `staff_id`, `source_document_id`) |
| `holds/<id>/`, `holds/<id>/release/` | GET / POST | 보류 상세 / 해제(`disposition`, `reason`, `staff_id`) |

## 운영 명령

| 명령 | 내용 |
|---|---|
| `manage.py seed_master --sample` | 가상 기준정보 + 기본 입고·생산 LOT 규칙 |
| `manage.py seed_master --items data/import/items.csv --encoding cp949 [--dry-run]` | 실제 기준정보 CSV 가져오기 |
| `manage.py check_inventory` | 재고·수불 정합성 점검 (문제 있으면 오류 종료) |
| `manage.py show_view [뷰이름] [--limit N] [--sql]` | 조회 뷰(`v_*`) 목록·컬럼·데이터·정의 보기 (문서 연동 확인용) |

## 10/13 v6.1 생산 반영

- 반제품 신규 LOT는 제조일 + 품목별 생산 순번. 기존 LOT 번호는 유지하며 0004 규칙은 2026-10-13부터 적용한다. 근무조와 문서 조회 뷰는 유지한다.
- `bom_line_alternatives`는 BOM 줄별 허용 대체 품목을 관리한다. 사용한 BOM의 대체 관계는 변경할 수 없으며 새 버전을 만든다.
- 대체 투입은 `bom_line_id`를 지정해야 표준 대비 실적에 포함된다. kg/g는 환산하고 그 밖의 단위는 동일해야 한다. BOM 밖 투입은 대체 실적으로 자동 합산하지 않는다.
