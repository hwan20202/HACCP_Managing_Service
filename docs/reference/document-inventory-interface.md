# 문서 ↔ 생산·수불 연동 인터페이스 — 문서 제공 함수

2026-10-27 코드 대조 기준. 구현 위치는 `backend/apps/doc_requirements/services.py`, 수불 진입점은 `backend/apps/inventory/document_bridge.py`입니다. 수불 제공 계약은 [수불 인터페이스](inventory-document-interface.md), 문서 규칙은 [문서 결정사항](document-decisions.md)을 참고합니다.

## 1. 공통 규칙

- 실제 쓰기 함수는 `require_for_lot(actor_id, lot_id, inspection=None)`, `require_for_batch(actor_id, batch_id)`, `delete_lot_documents(actor_id, lot_id)`입니다. `actor_id`는 수불의 직원 ID입니다. 예전 설계의 키워드 전용 `staff_id`와 혼동하지 않습니다.
- 호출자 트랜잭션 안에서 실행하며 수불이 자기 기록을 먼저 저장합니다. 호출자 밖에서는 `TRANSACTION_REQUIRED`입니다.
- 같은 LOT·배치를 재호출하면 기존 문서를 반환합니다. 입고 검사값은 새 D03에만 채웁니다.
- 잘못된 직원·대상·양식 등 `ApiError`가 전파되면 호출자도 롤백합니다. 단, 적합 D03의 자동 작성완료 도메인 오류는 내부 세이브포인트만 되돌리고 작성중으로 남깁니다.
- 작성 요구 진입점에는 양식 역할 검사를 하지 않습니다. 실제 직원 유효성은 확인합니다. 이후 문서 작성·결재에는 역할 검사를 적용합니다.

## 2. 입고 등록

```python
from apps.doc_requirements import services

result = services.require_for_lot(staff_id, lot_id, inspection=inspection)
```

LOT마다 D01 시험성적서·D02 원산지 증빙·D03 육안검사 문서를 만듭니다. D03은 입고일 묶음 화면으로 표시하더라도 LOT별 문서입니다. 새 D03의 점검자는 호출 직원으로 설정합니다.

| inspection 키 | 값 | 필수 |
|---|---|---|
| appearance | 양호 / 불량 | 예 |
| packaging | 양호 / 불량 | 예 |
| labeling | 양호 / 불량 | 예 |
| verdict | PASS / FAIL | 예 |
| has_coa | 이전 호환 입력은 허용하나 저장 입력에서 제거. D01 첨부로 계산 | 아니요 |

`inspection=None`도 허용합니다. 수불은 검사 상세가 없고 입고 판정이 PASS이면 기본 적합 검사값을 전달합니다. 명시 입력은 유지합니다. 최종판정 PASS로 새 D03을 채웠을 때 자동 작성완료를 시도합니다. 완료 오류 시 작성중 유지·오류 코드 반환이며, 입고 자체는 계속됩니다. 검사 형식·문서 생성 자체의 오류까지 모두 무시하는 동작은 아닙니다.

반환은 `lot_id`, `documents` 목록입니다. 각 항목은 `type_code`, `document_id`, `record_key`, `result`(created/existing)을 포함합니다. D03에는 `inspection_applied`, 자동 완료 시도 시 `auto_completed`, 실패 시 `completion_error`가 추가됩니다.

## 3. 생산 시작

```python
result = services.require_for_batch(staff_id, batch_id)
```

현재 제조 공정 기본값은 CCP-1P·2B·3P이고, 제조 배치에는 생산일지(`PROD-LOG`) 1건을 함께 만듭니다(공정 없이, 결재 없음 — 양식을 `install_document_templates --production-log`로 설치했을 때만). P16부터 공정 목록은 관리 설정 DB입니다: 기본은 `ccp_default`, 품목별 예외는 생산 기준정보 › 품목별 CCP(`item_ccp`), 배치마다 처음 생산 시작 때 정한 공정을 `batch_ccp_applied`에 남기고 [다시 호출]은 그 기록대로 만듭니다. 품목을 지우면(`item_removal.py`) 그 품목의 CCP 설정도 DB가 함께 지웁니다. 취소 배치는 거부합니다. 포장배치에는 작성 요구가 없고, 신규 포장배치 생성 자체도 MVP 범위에서 금지합니다.

반환은 `production_batch_id`, `documents`이며 CCP 일지 항목에는 `process_code`가 있고, 생산일지 항목은 `type_code: "PROD-LOG"`·`process_code` null입니다. 연결 문서를 셀 때 CCP 일지는 `process_code`(또는 `CCP-` 유형)로 구분합니다. 생산 시작을 생략한 사후 입력은 수불의 완료 처리에서 이 함수를 호출합니다.

## 4. 연결 문서 조회

- `services.docs_for_lot(lot_id)`: `lot_id`, `lot` 요약, `documents` 반환. 문서 항목은 ID·유형·상태·버전·최신 승인 회차 요약·승인본 판정·열린 정정 여부/사유를 포함합니다. 현재 편집본의 검사값과 최신 승인본 판정은 구분합니다.
- `services.docs_for_batch(batch_id)`: `production_batch_id`, `batch` 요약, `documents` 반환. 문서마다 공정·상태·버전과 CCP 측정/개선조치 `summary`를 제공합니다. 생산일지는 맨 앞에 오고 `process_code`·`summary`가 null입니다.

반환 필드는 더 추가될 수 있으므로 사용하는 키만 읽습니다. 실제 반환 조립 코드를 기준으로 확인합니다.

## 5. 입고 취소

수불 `cancel_receipt`는 사용·조정 여부와 연결 문서 상태를 먼저 검사합니다. `submitted`·`approved`·`correcting` 또는 열린 정정이 있으면 취소를 차단합니다. 허용되는 취소는 수불 정정·취소 기록 후 다음 함수를 같은 트랜잭션에서 호출합니다.

```python
result = services.delete_lot_documents(staff_id, lot_id)
```

연결 문서를 논리 삭제하고 관련 진행 회차·정정을 닫으며 결재 이력·스냅샷은 보존합니다. 반환에는 `lot_id`, `lot`, `documents`, `closed_requests`, `closed_corrections`가 있습니다. 서비스 자체의 정리 범위가 넓더라도 수불 진입점의 취소 차단 정책을 우회해 호출하지 않습니다. 오류 시 입고 취소도 롤백됩니다.

## 6. 문서 → 수불 판정

D03 작성완료 때 `doc_effects`가 `apps.inventory.judgment.apply_incoming_judgment`를 호출합니다. 정정 후 재작성완료도 포함합니다. 승인·반려·작성 재개·정정 시작/취소만으로 LOT 판정을 변경하지 않습니다.

입고 시 수불도 판정을 같은 트랜잭션에서 반영합니다. 같은 판정 재호출은 상태를 다시 바꾸지 않습니다. 판정 변경 조건·사유와 사용 이력 제한은 수불 서비스가 검사합니다.

## 7. 이전 설계에서 사용하지 않는 항목

| 이전 이름·요구 | 현재 기준 |
|---|---|
| create_incoming_inspection | 미구현 이름. 실제 입고 연결은 require_for_lot |
| get_incoming_inspection_form | 미구현. 현재 입고는 기존 화면과 inspection 입력 사용 |
| get_source_document | 미구현 전용 조회. holds.source_document_id는 문서 ID이며 수불 보류는 문서 승인 상태를 조회하지 않음 |
| ledger_approved_until 및 수불 잠금 | 미구현이고 이번 범위에서 제외. 소급 정정 허용·시스템 결재 없음 |
| CCP 이탈 자동 HOLD·승인 후 자동 해제 | 이번 운영 기준에서 제외. 담당자 수동 보류·개선조치 확인 후 수동 해제 |

과거 설계·요청 내용은 Git 이력과 [개발 기록](../history/README.md)에서 추적합니다. 현재 호출 코드는 이 문서와 대조합니다.
