# 문서·결재(documents) 결정 사항

`backend/apps/documents`·`approvals`·`document_workflow`·`doc_requirements`(문서 영역)의 동작 기준을 모았습니다. **확정**은 합의된 것, **가정**은 합의 전이지만 기본값으로 구현해 둔 것, **대기**는 결정이 나야 진행할 수 있는 것입니다. 가정이 바뀌면 "바꿀 곳"만 고치면 되도록 만들어 두었습니다. 생산·수불 앱 연동 명세는 [document-inventory-interface.md](document-inventory-interface.md).

## 확정

| 항목 | 내용 | 근거 |
|---|---|---|
| 도메인 구성 | 문서(`documents`)·결재(`approvals`)는 서로 import하지 않음. 둘을 묶는 처리(상신·승인·반려)는 워크플로우(`document_workflow`)가 각 도메인의 공개 서비스 함수만 불러 한 트랜잭션으로 수행. 외부(수불·생산)가 부르는 진입점은 작성 요구(`doc_requirements`). 경계는 각 앱의 import 검사 테스트로 확인 | 팀 결정 |
| 상태 변경 | 서비스 함수 안에서 조건부 UPDATE로 검사와 잠금을 함께 처리. 문서 단위 버전(`document.version`)으로 동시 수정 감지 — 수정 요청은 `expected_version` 필수, 다르면 409 `VERSION_CONFLICT` | 팀 결정 |
| 문서 상태 | `draft` 작성중 / `completed` 작성완료 / `submitted` 결재중 / `approved` 승인 / `rejected` 반려. 상신은 작성완료에서만. 작성완료는 잠김, [작성 재개]로 작성중 복귀 | 스프린트 2 계획 |
| 문서 삭제 | 논리 삭제만(`deleted_at`·`deleted_by`). 작성 요구로 생긴 문서는 삭제 불가 | 팀 결정 |
| 수정 방식 | 바뀐 부분만(PATCH, 섹션 행 단위 추가·변경·삭제) | 팀 결정 |
| 결재선 | 병렬·칸형. 칸 하나에 1명, 전원 승인이면 최종 승인, 작성자도 결재자 가능. 상신 때 사용자가 직접 지정(칸 최대 10, 같은 사람 중복 불가). 반려 시 남은 대기 칸은 미처리 종료 | 팀 결정 |
| 승인본 | 결재 회차마다 상신 시점 문서 스냅샷을 `approval_request.snapshot_json`에 보관. 회차는 만든 뒤 바꾸지 않음. 양식 정의는 스냅샷에 넣지 않고 `template_id`·버전으로 참조(양식 버전 내용은 불변) | 팀 결정 |
| 문서 ↔ 업무 대상 | `document_ref`가 `lot_id`·`production_batch_id`(+공정 코드)·`item_id`를 종류별 FK로 가짐. 문서 단위 참조와 행 단위(육안검사 LOT 행) 참조 | 10/11 ERD |
| 작성 요구 | 사건형 문서는 수불·생산이 부르는 함수로만 생성(양식 선택에서 숨김, 작업일 고정). 같은 대상 재호출은 기존 문서 반환(`record_key` 유니크) | 스프린트 2 계획 |
| 입고 LOT 문서 | 입고 LOT마다 D01(시험성적서)·D02(원산지 증빙) 1건, 그날 육안검사일지(D03)에 LOT 행 1개. 그날 일지가 작성완료·결재중·승인이면 다음 번호 일지(`#2` …, 하루 최대 9) | 스프린트 2 계획 |
| 생산 배치 문서 | 제조(MANUFACTURE) 배치는 CCP-1P·2B·3P 일지, 포장(PACKAGING) 배치는 없음. 취소 배치에는 만들지 않음 | 스프린트 2 계획 |
| 호출 규약 | 작성 요구 함수는 호출자(입고 등록·생산 시작) 트랜잭션 안에서만 동작. 호출자가 자기 쓰기를 먼저 한 뒤 부름(재호출 포함). 문서 쪽 오류면 호출자 전체 롤백 | 10/11 ERD |
| 수불 값 읽기 | 수불·생산 테이블을 직접 읽지 않고 뷰(`v_doc_incoming_lot`·`v_doc_batch`)로만. 값 사본을 따로 보관하지 않음 | 10/11 ERD |
| 문서는 기록 | 문서에는 문서가 판정한 내용만 남김. LOT 상태는 수불만 가지며 문서는 저장·표시·조회하지 않음 | 10/12 |
| 수불용 조회 | 수불은 문서 테이블을 직접 읽지 않고 `docs_for_lot(lot_id)`로 연결 문서·상태·최신 승인본 기준 판정을 받음 | 10/11 ERD |
| 개선조치 | 문서 영역 내부(`deviation_action`). 수불은 문서 참조(`source_document_id` = `document.document_id`)까지만 | 10/11 ERD |
| 육안검사 판정 | PASS / FAIL. 작성자가 고름(기본값 제안 없음) | 질의 3, 양식 협의 |
| 로그인 | MVP 범위 아님. 현재 사용자는 `X-Staff-Id` 헤더, staff에 없는 id는 거부 | 팀 결정 |
| 오류 응답 | `/api/v1/` 공통 `{code, message, details}` | 팀 결정 |

## 확정 — 구현 예정 (P6, 설계 완료)

| 항목 | 내용 | 근거 |
|---|---|---|
| 정정 | 승인 문서는 "승인 취소"가 아니라 정정. 상태 `correcting` 정정 중 추가, 정정 사유 필수(1~200자), 새 승인 전까지 이전 승인본 유효, 정정 회차가 승인되면 이전 승인 회차는 "대체됨"(계산, 저장 안 함). 정정 기록은 `document_correction` | 10/12, ERD v6 |
| 정정 취소 | 정정 시작 뒤 수정하지 않았을 때만. 수정 뒤 되돌리기는 추후 | 10/12 |
| 판정 → LOT 상태 | 육안검사일지 **작성완료** 때 문서 쪽이 LOT 행마다 `apps.inventory.judgment.apply_incoming_judgment()` 호출(정정 뒤 다시 작성완료 포함). 승인·반려·작성 재개는 부르지 않음. 거부되면 작성완료 전체 롤백, 화면에 LOT별 메시지 | 10/12, 수불 판정 함수 |
| 판정 변경 사유 | 정정 중이면 정정 사유, 아니면 작성완료 때 입력한 사유(선택, 200자, 문서에 저장하지 않고 수불에 전달만) | 10/12 |
| 후속 처리 계층 | 문서 → 외부 호출은 `doc_effects`(테이블 없음)가 문서 생명주기 신호를 받아 수행. 문서·결재·워크플로우·작성 요구는 이 앱을 import하지 않음. 수불 함수는 설정 `HACCP_INVENTORY_JUDGMENT`로 연결 | 10/12 |
| 수불용 공개 함수 | `create_incoming_inspection(lot_id, staff_id, answers)`(입고 화면 검사 값을 새 D03 행에 채움, 형식은 문서 쪽 D03 양식 항목), `get_incoming_inspection_form()`, `require_for_batch(batch_id, staff_id)`, `docs_for_lot`·`docs_for_batch`, HOLD 근거 문서 `get_source_document(document_id)`. 이름은 수불 요청에 맞춤(사람 = `staff_id`). 계약은 [document-inventory-interface.md](document-inventory-interface.md) 2장 | 10/12 |

## 가정 (기본값으로 구현, 확정 시 수정)

| 항목 | 현재 동작 | 바꿀 곳 |
|---|---|---|
| CCP 공정 목록 | 제조 = 1P·2B·3P, 포장 = 없음, 품목별 예외 없음 | `doc_requirements/rules.py` `CCP_PROCESSES`·`CCP_BY_ITEM` |
| 취소 배치 상태 이름 | `CANCELLED` | `doc_requirements/rules.py` `CANCELLED` |
| 같은 날 육안검사 일지 상한 | 9 | `doc_requirements/rules.py` `D03_LIMIT` |
| 수불 뷰 읽기 | 수불 뷰 `v_doc_incoming_lot`·`v_doc_batch`를 읽고 REQ 안의 키로 바꿈: 구분 RAW → 원료·PACKAGING → 부자재, 수량 `quantity_e6` ÷ 10⁶ + `base_unit`, 원산지 `origin_country`, CCP 수량 = 계획 수량 kg(단위 kg·g 또는 `unit_weight_mg`로 환산). 입고 기록 없는 LOT은 `LOT_NOT_FOUND` (C2) | `doc_requirements/sources.py`·`services.py` |
| 수불 테이블 | 수불 앱(`apps.inventory`) 테이블을 그대로 참조(`staff`·`items`·`lots`·`production_batches`). 문서 쪽 임시 테이블 없음(C2) | `document_ref` RunSQL FK, 사람 FK |
| staff | 수불 `staff`. 비활성 직원은 현재 사용자·결재자·담당자·확인자로 쓸 수 없음(C2) | `apps/staff/services.py` |
| 판정 함수 | 기본값 수불 `apps.inventory.judgment.apply_incoming_judgment`, 예외 `apps.inventory.errors.InventoryError`(설정으로 바꿀 수 있음, C2) | `config/settings/base.py` |
| 목록 기본 기간 | 최근 7일 | 문서 목록 API |
| 시각 | UTC 저장, 응답은 +09:00 | `apps/core` |

## 대기

| 항목 | 상태 |
|---|---|
| 수불 스키마 맞추기 | 스프린트 2 뒤 통합 때(수불이 `main`에 먼저 병합, 문서가 뒤따름. 운영 DB에 문서 데이터가 없어 문서 마이그레이션은 다시 생성). 수불 0001·0002 확정본(`feature/inventory`)에 맞춰 뷰 컬럼 이름(`quantity_e6`·`base_unit`·`item_type`·`origin_country`, 배치 `output_quantity_e6`), LOT 상태(CONSUMED·DISPOSED 없음), LOT 번호 유일성(품목 안에서만), `inventory.Staff` 사용, 마이그레이션 의존(`inventory 0002`)을 반영해야 함 |
| 입고 취소된 LOT의 문서 | 처리 방식 미정. 당분간 결재 이후(결재중·승인)에는 입고 취소가 없다고 가정 |
| 정정 권한·기한, 상신 취소, 파일 업로드, 작성 요구 현황 화면 | 스프린트 3 이후 |
