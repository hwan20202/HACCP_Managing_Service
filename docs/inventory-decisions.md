# 생산·수불(inventory) 결정 사항

`backend/apps/inventory` 의 동작 기준을 모았습니다. **확정**은 합의된 것, **가정**은 합의 전이지만 기본값으로 구현해 둔 것, **대기**는 결정이 나야 진행할 수 있는 것입니다. 가정이 바뀌면 "바꿀 곳"만 고치면 되도록 만들어 두었습니다. 진행 현황은 [inventory-roadmap.md](inventory-roadmap.md), 문서 앱 연동 명세는 [inventory-document-interface.md](inventory-document-interface.md).

## 확정

| 항목 | 내용 | 근거 |
|---|---|---|
| 프로젝트 구조 | 한 Django 프로젝트·한 SQLite DB. 테이블은 `sql/0001_core.sql`·`sql/0002_production.sql` 이 만들고 모델은 `managed=False` | 질의 1 |
| MVP 범위 | 입고부터 제조 완료된 벌크(반제품) 산출까지. 물류 소분·포장·출고와 포장배치는 구현 범위에서 제외. 판매 포장용 완제품(4코드)으로 바꾸는 흐름은 요구하지 않음 | 10/15 |
| 제조배치와 산출 LOT | 한 제조배치 = 제조 시작일로 채번한 산출 LOT 하나. 산출을 나눠 입력해도 같은 LOT 에 더함 (`production_outputs` 는 여러 행, `lot_id` 하나). 한 LOT 은 한 배치의 산출. 0002 P6(1:N)을 대신함 — 0006 트리거로 강제 | 10/15 |
| 포장배치 | 새로 만들 수 없음 (서비스 + 0006 트리거). `process_type` 의 `PACKAGING` 값과 예전 행은 조회·문서 참조용으로 유지. 예전 포장배치는 시작·투입·산출 불가, 취소·완료로 닫기만 | 10/15 |
| 공통 모델 소유 | `staff`, `lots`, `items`, `production_batches` 는 inventory 앱 소유. 문서 앱은 `("inventory", "0002_production")` 에 의존하고 `inventory.Staff`·`Lot`·`Item`·`ProductionBatch` 로 FK. 문서 쪽 임시 `staff` 는 수불 스키마로 옮길 예정 (문서는 staff id 만 사용) | 질의 1, 10/11 ERD |
| HOLD 근거 문서 | `holds.source_document_id` = 문서 `document.document_id` (버전·스냅샷 아님). 마이그레이션 순환을 피해 FK 미설정. 최신 내용·승인본은 문서 쪽 메소드로 조회 | 질의 2, 10/11 ERD |
| 개선조치 | 문서 영역 내부(`deviation_action`)에서만 관리. 수불은 문서 참조까지만 → `lot_holds.deviation_action_id` 삭제 | 10/11 ERD |
| 문서 ↔ 업무 대상 | 문서 쪽 `document_ref` 테이블이 `lot_id`·`production_batch_id`·`item_id` 를 종류별 FK 로 가짐 (`subject_type`/`subject_id` 방식 폐기) | 10/11 ERD |
| LOT 번호 형식 | **원료** 입고 LOT = LOT 약어 + **소비기한**(소비기한 있음) / LOT 약어 + **입고일**(소비기한 없음으로 확인) (0007, ERD 점검 10/14 확정). 포장재·구매 반제품 입고 LOT 은 입고일 기준. **반제품** LOT = **제조 시작일** + **품목별 순번** (`261014A`, `261014B`) — 이번에 바꾸지 않음. 분할 포장은 기존 LOT 유지. 근무조 없음. **완제품** LOT 은 MVP 범위 밖이며, 완제품 채번을 다룰 때 PM 답변 A1(품목 약어 사용 동의, 품목끼리 중복 방지)을 적용. 약어 값·세부 표기는 그때 기준정보(`items.short_code`)에 맞춤 | 10/12 BOM v4, 10/14 PM 미팅(A1·B1·C2), 10/15 정정, ERD 점검 |
| 소비기한 유무 | `lots.expiration_status`: KNOWN 있음(날짜 필수) / NONE 없음으로 확인 / UNKNOWN 미확인. 날짜가 비었다고 NONE 으로 보지 않음. 원료 입고는 KNOWN·NONE 중 하나를 정해야 함(서비스 + 트리거). 기존 LOT 은 날짜 있으면 KNOWN, 없으면 UNKNOWN 으로 이관. 화면·CSV 는 날짜가 없을 때 "소비기한 없음"·"미확인"을 구분 표시 | 0007, `docs/inventory-erd-review-20261014.md` |
| 반제품 LOT 단위 | 제조배치별 LOT 유지 (1 배치 = 1 LOT). 같은 날 여러 배치를 한 LOT 으로 묶지 않음 — 0006 트리거 그대로 | 10/15 범위 정리 |
| 원료 입고 LOT 단위 | **현재 MVP의 구현 선택**: 입고 건별 LOT 유지 (입고 1건 = LOT 1개). 채번 기준(소비기한 있음 → 소비기한, 없음 → 입고일)이 같은 날짜로 또 나오면 `-2`, `-3`. PM이 건별 분리를 의무화한 것은 아님. 동일 LOT 관리도 허용하되 성적서 등 차이를 구분할 수 있어야 하므로 구현 편의로 분리한 것 | 10/15 범위 정리, 10/18 사용자 설명·9/30·10/7 회의 정리 재확인 |
| 소비기한 없음·미확인 LOT 사용 | 상태 필드만 구현. 품목별 소비기한 정책 컬럼과 새 사용 차단 정책은 이번 범위 제외 — NONE·UNKNOWN LOT 은 이전처럼 사용 가능, 원료 신규 입고만 UNKNOWN 불가(채번 기준이 없으므로) | 10/15 범위 정리 |
| LOT 번호 유일성 | DB 는 품목 안에서 UNIQUE (`UNIQUE(item_id, lot_number)`), 순번도 품목별 — 전체 공통 순번은 쓰지 않음. 반제품 LOT 은 같은 날 다른 품목이면 번호가 같을 수 있어 `lots.id` 로 식별하고, 사람이 읽을 때는 품목코드 + LOT 번호. 완제품 LOT 의 품목 간 중복 방지(A1)는 완제품 채번 때 품목 약어로 해결 | 10/12, 10/15 A1 정정 |
| 근무조 | 폐지 (10/14). 야간 없음, 같은 날 두 번이면 생산 순번 A·B. `production_batches.shift` 열은 `v_doc_batch` 계약(열 삭제 금지) 때문에 남기고 항상 NULL. 서비스·API 는 받지 않음 | 10/11 v5 미팅, 10/14 PM 미팅 |
| LOT 상태 | 품질 판정만: QUARANTINE / AVAILABLE / REJECTED. 소진·폐기(CONSUMED / DISPOSED) 삭제 — 재고 유무는 `inventory`, 비운 경위는 수불 이동이 나타냄 | 10/12 |
| 문서용 뷰 형식 | 이름·행 범위는 문서 쪽 요청에 맞추고 수량·단위·코드는 수불 규칙 유지. `v_doc_incoming_lot` 은 모든 LOT (입고 정보는 LEFT JOIN, `lot_kind`·`item_id`·`item_type_name`·`origin_country` 추가). `v_doc_batch` 는 `production_batch_id`·`status` 로 이름 변경, 수량은 `output_quantity_e6` + `base_unit` (kg 아님) | 10/12 |
| `domain_event_inbox` | 삭제 (문서 이벤트를 받지 않음). `audit_logs.source_event_id` 도 삭제, `staff_id` 필수 | 10/11 ERD |
| 육안검사 판정 | PASS / FAIL 두 가지. CONDITIONAL 은 이번 범위 제외 | 질의 3 |
| 로그인 | MVP 범위 아님. 처리자는 요청 본문의 `staff_id` 로 받음 | 팀 결정 |
| 기준정보 | 저장소에는 가상 샘플만. 실제 자료는 `data/` 아래 CSV 로 `seed_master` | CONTRIBUTING |
| 생산 테이블 이름 | 생산지시가 아닌 제조배치 중심 `production_batches` (다음 마이그레이션) | 팀 결정 |
| 입고 LOT 분리 | 같은 날 같은 원료라도 입고 건별 별도 LOT 허용 (성적서가 다를 수 있음) | 10/7 현업 |
| 원산지 | 원산지가 다르면 별도 품목코드 | 10/7 현업 |
| 부적합 원료 | 육안검사 FAIL 은 전량 반품. 입고하지 않고 바로 반품하는 경우(수불·육안검사일지 기록 없음)와 입고 후 반품하는 경우가 모두 있음 | 10/7 현업, 10/14 PM 미팅 D1 |
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
| 수불대장 결재 | 시스템 결재 없음. 수불대장은 출력까지만 하고 결재는 출력물로 따로. 생산일지도 결재 없음 | 10/14 PM 미팅 D4 |
| 판정 반영 시점 | 입고 화면에서 판정을 함께 보내면 입고 트랜잭션 안에서 바로 반영 (커밋 시 AVAILABLE / REJECTED). 미확정이면 QUARANTINE 으로 저장하고, 육안검사일지 작성완료 시 문서 앱이 `judgment.apply_incoming_judgment()` 호출. 결재 승인·반려는 LOT 상태 무관 | 질의 3, 10/10 협의 |
| FAIL 입고 | 입고 후 반품: 입고 등록 → LOT REJECTED → 전량 반품(`return_to_supplier`). 입고 전 반품: 시스템에 아무것도 남기지 않음 | 10/10 협의, 10/14 PM 미팅 D1 |
| 제조일 | 생산 시작일. LOT 번호·소비기한 모두 이 날짜 기준. 사후 입력(계획 상태에서 바로 산출)은 배치에 제조일을 넣어야 산출 가능 | 10/14 PM 미팅 B1·B2·C2 |
| 소비기한 표시 | 제조일 + 기간의 하루 전 (2026-10-13 제조, 24개월 → 2028-10-12). 같은 날로 해도 법적 문제는 없음 | 10/14 PM 미팅 B3 |
| 나눠 포장 | 같은 제조분을 여러 날 나눠 포장해도 LOT 번호는 처음 부여된 것 그대로. 물류 소포장도 새 LOT 없음(선입선출만). 포장·물류는 MVP 범위 밖. **이 답변을 배치 간 LOT 통합으로 해석하지 않음** (10/15 범위 정리) | 10/14 PM 미팅 C2·A5, 10/15 |
| 공정용수 | 정제수 등은 재고가 아님 → `items.is_stock_managed = 0`: LOT·입고·기초재고·투입 기록 없음(트리거로 막음). BOM 에는 남고 `bom_check` 실제값은 비움, 사용량은 생산일지에 | 10/14 PM 미팅 C1 |
| 입고 대상 | 원료·포장재·반제품 (`receiving.RECEIVABLE_ITEM_TYPES`) | 10/14 PM 미팅 D2 |
| 과거 수불 수정 | 결재 여부와 무관하게 소급 수정 허용 (기간 잠금 없음). 정정은 원 기록 일시로 들어감. 입고 수량도 일부 정정 가능. 문서 쪽이 요청한 수불대장 잠금(`ledger_approved_until()` 이하 날짜 등록·정정 막기)은 D3·D4 에 따라 이번 범위에서 제외 | 10/14 PM 미팅 D3 |
| BOM 기준 문서 | 문서끼리 다르면 제조방법설명서 우선 | 10/14 PM 미팅 C4 |

## 가정 (기본값으로 구현, 확정 시 수정)

| 항목 | 현재 동작 | 바꿀 곳 |
|---|---|---|
| 배치 번호 | `B-{품목코드}-{제조일 yyMMdd}{A,B..}` (10/11 미팅 A4 제안) | `production._next_batch_number` |
| 산출 LOT 상태 | 바로 AVAILABLE (실험 검사 흐름 없음) | `production.add_output` |
| 산출 LOT 소비기한 | 첫 산출 때 입력값, 없으면 배치 제조일(생산 시작일) + 품목 소비기한 − 1일. 산출 추가는 그 LOT 의 소비기한을 따름 (다른 값이면 거부) | `production.add_output`, `shelf_life.py` |
| 제조 산출 품목 | 지금은 반제품(SEMI) 품목만 제조배치를 만들 수 있음. **현재 기준정보 분류에 따른 구현 제한**(v6.1: 자사 제조품은 모두 3코드 반제품, 4코드 완제품은 판매 단위)이며, 제조 완료품이 반드시 반제품 유형이어야 한다는 확정 업무 규칙은 아님. 분류가 바뀌면 여기만 고침 | `production.PRODUCIBLE_ITEM_TYPES` |
| 수동 LOT 번호 | 첫 산출에만 지정 가능. 산출 추가는 같은 번호를 다시 보내거나 생략. 오입력은 지금은 산출을 정정으로 0 → 배치 취소 → 새 배치. 후속 참조가 없을 때 이력을 남기고 번호만 고치는 방안은 아래 "LOT 번호 정정 검토" | `production.add_output` |
| 보류 구조 | 10/11 A1 '다' 안: `holds` 테이블 하나(LOT 또는 배치). 배치 보류 → 산출 LOT 전파(PROPAGATED), 보류 중 배치는 투입·산출 불가(완료는 가능), 배치 보류 해제 시 열린 전파 보류도 같은 처분으로 해제, LOT 별 먼저 해제 가능. 근거 필요 사유는 `source_document_id` 필수. 이미 쓰인 하위 LOT(다음 배치 투입분)으로는 전파 안 함 | `holds.py`, `sql/0003_holds.sql` |
| 소비기한 계산 | `items.shelf_life_months`(개월) 또는 `shelf_life_days`(일) 중 하나. 제조일 + 개월(말일은 그 달 마지막 날) − 1일 | `shelf_life.END_DAY_OFFSET` |
| 투입 가능 LOT | AVAILABLE·보류 없음·투입일 기준 소비기한 안 지남·산출 품목과 다른 품목. 소급 투입은 그 시점 이후 잔량 검사 | `production.add_usage` |
| 배치 완료 | 산출(정정 반영) 1건 이상 필요. 계획 상태에서 바로 완료 가능(사후 입력, 제조일 필수) | `production.complete_batch` |
| 배치 취소 | 계획·진행 중이고 투입·산출이 정정으로 모두 0일 때만. 완료된 배치는 정정으로 처리 | `production.cancel_batch` |
| 구매 반제품 LOT | 입고일 + 순번 (`261014A`, 0005 가정 규칙). 소비기한 유무는 기록만 하고 채번에는 쓰지 않음 | `lot_number_rules` INCOMING SEMI (0005), `master_import.DEFAULT_INCOMING_SEMI_PATTERN` |
| 지난 날짜 입고 | 그날 00:00:00 으로 기록 (그날 다른 이동보다 앞에 오도록) | `receiving._occurred_at` |
| 입고 취소 | 입고 후 사용·조정이 없을 때만. 남은 입고 수량(일부 정정 반영)을 CORRECTION_OUT, LOT 상태는 그대로 | `receiving.cancel_receipt` |
| FAIL 입고 처리 | 판정 함수는 상태(REJECTED)만 바꾸고, 반품은 `return_to_supplier` 별도 호출 (상태는 REJECTED 유지) | `judgment.py` |
| 판정 변경 | 같은 판정 재전송은 무시. 바꾸려면 사유 필수. PASS → FAIL 은 RECEIPT 외 이동이 없을 때만, FAIL → PASS 는 반품·폐기 전만 | `judgment.apply_incoming_judgment` |
| 변경 감지 조건 | 승인 시각 이후(같은 초 포함) 등록, 발생 일시가 기간 종료일 이전. 수불대장 시스템 결재가 없어져(10/14) 지금은 쓰는 곳 없음 — 제거 후보 | `ledger.stock_ledger_changes_since` |
| 정정 대상 | 입고(RECEIPT)는 일부만 정정 (0 이 되면 입고 취소). 취소된 입고와 정정 기록 자체는 정정 불가 | `movements.correct_movement` |
| 정정 일시 | 원 기록과 같은 일시 (수불대장에서 그 시점부터 바로잡힘) | `movements.correct_movement` |
| 소급 출고 | 그 시점 이후 잔량이 한 번이라도 음수가 되면 거부 | `movements._check_outflow` |
| 기초재고 | 반제품·완제품은 기존 LOT 번호 필수. 원료·포장재는 비우면 입고 규칙으로 채번 | `movements.record_opening_balance` |
| LOT 약어 없는 품목 | 원료·포장재는 `short_code` 가 없으면 입고·채번 거부. 반제품 규칙에는 약어 토큰이 없어 검사하지 않음 | `lot_numbers.render` |
| 수불대장 조회 기간 | 최대 1년 | `api.ledger_params` |
| 사용 가능 재고 | 상태 AVAILABLE 이고 미해제 HOLD 없음 (I5) | `stock.py` |

## 대기

| 항목 | 기다리는 것 | 현재 상태 |
|---|---|---|
| 입고 취소 때 문서 처리 | 문서 쪽 결정 | 결재중·승인·정정 중 문서가 있으면 취소 거부(연결 완료). 그 밖의 문서 처리는 미정 — `incoming_receipt_cancelled` 빈 함수 |
| 통합 입고 화면의 검사 항목 | 문서 쪽 `get_incoming_inspection_form()` | 입고 + 육안검사 값(`inspection`) 저장·판정 반영은 연결 완료(`require_for_lot`). 화면 항목 조회 함수는 문서 쪽 대기 |
| 운영 DB 문서 양식 | 문서 쪽 결정 | 입고·생산 시작이 D01~D03·CCP 양식을 요구. 운영에 넣는 방법 미정 |
| CCP 이탈 보류 연결 | 문서 쪽이 이탈 기록 때 `hold_batch` 를 부를지, 해제 조건(개선조치 완료·근거 문서 승인) | 수불 함수·API 준비됨 (`holds.py`, `/holds/`) |
| BOM·제조배치·투입 서비스, CCP | 생산 서비스 개발 | 생산 서비스·API 구현 완료. CCP 문서 연동은 문서 브랜치 병합 후 협의 |
| 화면 | 기존 시제품 활용 여부 | API 까지 완료 |
| 품목코드 재정리 | 7자리, 맨 앞 1 원료·2 포장재·3 반제품·4 완제품. 기존 4코드 중 반제품은 3코드로, 완제품 4코드 새로 받음 | 코드는 TEXT 로 저장만 함. 유형은 `item_type` 열이 결정(코드 앞자리와 무관) |
| 포장 처리 (C2) | MVP 범위 밖 (10/15). 다음 단계에서 다룰 때 데이터팀 반제품·완제품 코드 구조에 맞춤 | 포장배치 신규 생성 막음, 예전 행만 유지 |
| 원료성 완제품 (A4) | 데이터팀: 주문량대로 나가는 분말류(예: 224g)의 품목코드·단위 | 판매 단위별 4코드(v6.1)와 안 맞음 |
| CCP 기준 (C3) | 식품유형별 CCP 기준·일지 — 수정 가능하게 개발 후 추후 설정 | 문서 쪽 |
| 운영 시작일 (E1) | 운영 시작일·기초재고 실사 일정 | 미정 |
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
| `movements/<id>/correct/` | POST | 정정 (`quantity` 생략 시 남은 전량. 입고는 일부만) |
| `batches/` | GET, POST | 배치 목록(`status`, `process_type`, `item_id`, `from`, `to`=제조일·계획일, `limit`, `offset`) / 등록(`item_id`(반제품), `staff_id`, 선택 `process_type`(MANUFACTURE 만, 생략 시 MANUFACTURE)·`planned_date`·`planned_quantity`·`manufactured_date`(=생산 시작일, 사후 입력이면 필수)·`bom_id`·`notes`) |
| `batches/<id>/` | GET | 배치 상세: 투입·산출(정정 반영 순수량), 산출 LOT 요약 `output_lot`(번호·순수량·재고), BOM 표준 대비 실제(`bom_check`) |
| `batches/<id>/start/`, `complete/`, `cancel/` | POST | 시작(`manufactured_date` 지정 가능, 기본 시작일) / 완료 / 취소(`reason` 필수) |
| `batches/<id>/usages/`, `outputs/` | POST | 투입(`lot_id`, `quantity`, `bom_line_id` 선택) / 산출(`quantity`, 첫 산출만 `lot_number`·`expiration_date` 선택 — 이후 산출은 같은 LOT 에 더함). `idempotency_key` 필수 |
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

- 반제품 신규 LOT는 제조일 + 품목별 생산 순번. 기존 LOT 번호는 유지하며 0004 규칙은 2026-10-13부터 적용한다. 문서 조회 뷰는 유지한다. (근무조는 10/14 폐지)
- `bom_line_alternatives`는 BOM 줄별 허용 대체 품목을 관리한다. 사용한 BOM의 대체 관계는 변경할 수 없으며 새 버전을 만든다.
- 대체 투입은 `bom_line_id`를 지정해야 표준 대비 실적에 포함된다. kg/g는 환산하고 그 밖의 단위는 동일해야 한다. BOM 밖 투입은 대체 실적으로 자동 합산하지 않는다.

## 10/14 PM 미팅 반영 (0005)

- 근무조 폐지: 완제품 LOT 도 제조일 + 품목별 생산 순번. 0005 가 `{shift}` 규칙을 끄고 같은 품목유형·적용일로 새 규칙을 넣는다. `production_batches.shift` 열과 `v_doc_batch.shift` 는 계약 때문에 남김(항상 NULL).
- 제조일 = 생산 시작일. 시작하면 시작일, 사후 입력은 등록 때 넣은 제조일. 산출 시각으로 대신 채우지 않는다. 시작 시각·산출일이 제조일보다 빠르면 거부.
- 소비기한 하루 전 (`END_DAY_OFFSET = -1일`).
- 반제품 입고 허용, 구매 반제품 LOT 는 입고일 + 순번 (가정).
- `items.is_stock_managed`: 정제수 등 재고 비관리 품목. 기준정보 CSV 열 `is_stock_managed` (비우면 1).
- 입고 수량 일부 정정 허용. `v_doc_incoming_lot` 끝에 `net_quantity_e6` (정정·취소 반영 수량) 추가.

## 10/15 MVP 범위 정리 (0006)

- 범위: 입고 ~ 제조 완료된 벌크 산출. 물류 소분·포장·출고, 포장배치, 판매 단위 완제품 전환은 제외.
- 1 제조배치 = 1 산출 LOT (제조 시작일 채번). `add_output` 은 첫 산출 때만 LOT 을 만들고 이후는 같은 LOT 에 더함. 0006 트리거 `trg_outputs_one_lot_per_batch`·`trg_outputs_one_batch_per_lot`.
- 포장배치: `create_batch` 와 0006 트리거 `trg_batches_no_packaging(_update)` 가 막음. 예전 행은 그대로(조회·취소·완료), 시작·투입·산출 불가.
- 제조배치 산출 품목은 지금 반제품만 (`PRODUCIBLE_ITEM_TYPES = {"SEMI"}`). 현재 기준정보 분류에 따른 구현 제한이며 확정 업무 규칙 아님.
- 기존 데이터 영향: 로컬 개발 DB(`data/db/app.sqlite3`, 0004 까지 적용)에는 배치·산출·LOT 이 없어(기준정보 5건만) 정리할 기록 없음. 다른 DB 에 예전 포장배치나 LOT 이 여러 개인 배치가 있으면 행은 남고 새 작업만 막힘.
- 문서 뷰 `v_doc_batch`: `output_lot_count` 를 서로 다른 LOT 수로(산출 행 수 아님), 끝에 `output_lot_number` 추가. `process_type` 은 그대로(새 행은 항상 MANUFACTURE).
- 그대로 둔 것: `ProcessType.PACKAGING`·DB CHECK 값, 완제품(4코드) 품목·완제품 채번 규칙, `test_production_schema.py`(0002 스키마만 따로 검증하는 테스트라 포장 시나리오 유지), 기초재고의 완제품 LOT 등록.

## 10/15 A1 정정 · LOT 번호 정정 검토

**A1 정정**: 10/14 미팅 답은 "LOT 번호가 중복되지 않으면 된다, 품목 약어 사용에 동의"였다. "LOT 은 원래 비밀스럽게 관리한다"는 관행 설명이지 약어 사용 금지가 아니다. 이전 문서의 "LOT 에 품목명 넣지 않음", "날짜 + 그날 전체 순번", "A1 데이터팀 확인 대기" 는 잘못 정리한 것이라 고쳤다.
- A1 은 **완제품 LOT** 에 관한 질문이었다. 반제품 채번(제조 시작일 + 품목별 순번)은 바꾸지 않는다. 완제품은 MVP 범위 밖이라 필수 후속 과제가 아니며, 완제품 채번을 다룰 때 품목 약어로 중복을 막는다(전체 공통 순번 아님, 약어 값·표기는 기준정보). (10/15 재정정: 이전에 "생산 LOT 품목 약어 반영 = 후속 채번 수정"으로 적은 것을 고침)
- 분할 포장은 기존 LOT 유지. 입고 LOT(원료·포장재·구매 반제품)은 입고일 기준 유지.

**LOT 번호 정정 검토 (산출 LOT 오입력)** — 지금은 배치를 취소하고 새 배치를 만들어야 한다. 후속 참조가 없는 LOT 에 한해 이력을 남기고 번호만 고치는 방안:
- 대상: 생산 LOT 의 `lot_number` (수동 입력 오타 등). LOT·배치·수불 행은 그대로이고 모든 참조는 `lot_id` 라 연결은 끊기지 않음.
- 허용 조건 (모두 만족): ① 그 LOT 의 수불이 산출(`PRODUCTION_OUTPUT`)과 그 정정뿐 — 다음 배치 투입·조정·반품·폐기 없음 ② 보류(`holds`) 기록 없음 ③ 문서 쪽 참조 없음 — `document_ref.lot_id` 또는 `label` 에 번호가 들어간 문서가 없음 (문서 앱 확인 함수 필요) ④ 새 번호가 같은 품목에서 중복 아님 ⑤ 사유 필수.
- 처리: `lots.lot_number` 갱신 + `audit_logs`(table `lots`, before/after 번호, 사유, 담당자). 자동 채번 순번(`lot_number_sequences`)은 되돌리지 않음(지운 번호를 다시 쓰지 않음).
- DB 보호: 조건 ①·② 를 트리거로 막아(이후 참조가 생긴 LOT 은 번호 변경 거부) 서비스 밖 수정도 차단. 조건 ③ 은 문서 앱 함수로만 확인 가능.
- 남는 위험: 이미 출력한 라벨·종이 일지의 옛 번호 — 운영에서 재부착. 결재 스냅샷의 옛 번호는 문서 쪽 보존 원칙대로 남고 감사 로그로 연결됨.
- 확인 필요: 문서 앱이 LOT 참조 여부를 알려 줄 함수(`has_lot_reference(lot_id)` 등)를 줄 수 있는지, 정정 권한자(품질 담당만?)를 둘지.

## ERD 점검 반영 (0007, 10/15) — `docs/inventory-erd-review-20261014.md`

확정 범위만 구현했다.
- 스키마: `lots.expiration_status` (KNOWN / NONE / UNKNOWN, 기본 UNKNOWN) + 트리거 3개 — KNOWN ⇔ 날짜(INSERT·UPDATE), 원료 입고 LOT 은 UNKNOWN 불가. 기존 행 이관: 날짜 있으면 KNOWN. `v_doc_incoming_lot` 끝에 `expiration_status`.
- 채번: 원료는 KNOWN → 약어 + 소비기한, NONE → 약어 + 입고일 (`expiration.incoming_number_date`). 채번 규칙의 적용일 판단은 입고일(`next_lot_number(rule_date=)`), 같은 기준일이 또 나오면 `-2` (기존 구조). 기초재고도 같은 기준(번호를 직접 넣으면 UNKNOWN 허용).
- 모델 `Lot.expiration_status`: 비워 두면 날짜로 KNOWN / UNKNOWN 을 정함. NONE 은 명시할 때만.
- API: 입고·기초재고 `expiration_status`, 응답(입고·LOT·재고·수불·FEFO)에 `expiration_status`. `stock/lots/` 에 `lot_number`(일부), `manufactured_from`·`manufactured_to`(제조일), `expiration_status` 필터, `item_type` 여러 개(`SEMI,FINISHED`). `ledger/`·`ledger/export.csv` 에 `lot_number`. CSV 소비기한 칸은 날짜가 없으면 "없음"·"미확인".
- 화면: `prototype/js/modules/inventory-api.js` (재고장 = LOT별 현재고, 수불일지 = 기간 수불·누적 잔량·CSV). 원료·부자재·완제품 메뉴를 이 화면으로 연결(`app.js` 3줄, `index.html` 스크립트 1줄). 기존 `inventory.js` 는 보존.
- 검증: 테스트 189개(인벤토리 170) 통과, 사용자 DB 사본에 0005~0007 정·역·재적용, 브라우저로 재고장·수불일지·필터·CSV 확인.
- 범위 정리(10/15): 반제품은 배치별 LOT 유지(분할 포장 답변을 배치 간 통합으로 해석하지 않음), 원료는 입고 건별 LOT·`-2` 접미사 유지, 소비기한 상태 필드만 구현하고 품목별 정책 컬럼·새 사용 차단은 제외. 확정 표에 기록.
## 10/16 재고 사용 가능 표시·추천 순서 보완

- 원료 채번은 확정한 **소비기한 있음 → 약어+소비기한 / 없음 → 약어+입고일**을 유지한다.
- `is_usable`은 기존 문서·품질/HOLD 판정 의미를 유지한다. 재고 API의 `can_use`는 여기에 양수 재고와 소비기한 미경과를 포함한다. 소비기한 당일까지 허용, 전날까지의 날짜면 경과로 표시한다.
- `stock/lots/?usable_only=1`은 `can_use`인 LOT만 반환한다. 생산 LOT 선택도 이 조회를 사용한다. 경과 LOT의 수불 이력·재고 기록을 삭제하지 않는다.
- `use_priority`는 같은 품목의 사용 가능한 전체 LOT에 대해 계산한다. 품목·LOT·상태 검색으로 일부만 보여도 순위를 다시 부여하지 않는다. 사용 불가·0 재고는 순위가 없다.
- **현재 시스템 정책(멘토링 확정 사항 아님):** 소비기한 있는 LOT부터 소비기한 오름차순. 같은 소비기한이면 입고일(없으면 제조일), 마지막으로 내부 LOT ID순. 날짜 없는 NONE·UNKNOWN은 그 뒤에서 입고일(없으면 제조일)순, 기준 날짜도 없으면 마지막이다. NONE·UNKNOWN에 새 사용 차단 정책을 추가하지 않는다.
- 재고 조회의 우선순위와 생산 FEFO 추천은 공통 정렬식을 사용한다. 품목별 가용 재고 합계도 경과 재고를 제외한다. DB 스키마·LOT 품질 상태는 변경하지 않는다.

