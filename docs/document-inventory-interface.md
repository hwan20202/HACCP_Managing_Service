# 문서 ↔ 생산·수불 연동 인터페이스 (문서 쪽)

생산·수불(inventory) 앱이 부르는 문서 쪽 함수의 계약입니다. 수불 쪽 테이블·뷰·함수는 [inventory-document-interface.md](inventory-document-interface.md), 문서 쪽 결정 근거는 [document-decisions.md](document-decisions.md).

## 1. 공통 규칙

| 항목 | 규칙 |
|---|---|
| 위치 | 모두 `apps.doc_requirements.services`. 인자는 키워드, 사람은 `staff_id` |
| 트랜잭션 | 쓰는 함수(2.1·2.3)는 호출자 트랜잭션 안에서만 동작(밖이면 `TRANSACTION_REQUIRED`). 호출자는 자기 쓰기(입고·배치)를 먼저 한 뒤 부름 |
| 재호출 | 같은 LOT·배치로 다시 불러도 문서가 늘지 않음(기존 문서 반환) |
| 반환 필드 | 여기 적힌 필드는 보장하고 바꾸지 않음. 그 밖의 필드가 더 있을 수 있음(무시해도 됨) |
| 오류 | `apps.core.http.ApiError` 하위 예외(`code`, `message` — 사용자에게 보여줄 한국어, `details`). 잡지 않으면 호출자 전체 롤백 |
| 공통 오류 코드 | `VALIDATION_ERROR` 400(입력), `INVALID_STAFF` 403(없는 담당자) |
| 문서 상태 | `draft` 작성중 / `completed` 작성완료 / `submitted` 결재중 / `approved` 승인 / `rejected` 반려 / `correcting` 정정 중 |
| 문서 내용 | 문서 테이블을 직접 읽지 말고 2.4~2.6 조회 함수를 씀(직접 읽으면 미승인·정정 중 내용이 나올 수 있음) |

## 2. 문서가 제공하는 함수

### 2.1 `create_incoming_inspection(*, lot_id, staff_id, answers=None)` — 입고 등록 직후

LOT마다 시험성적서(D01)·원산지 증빙(D02)·육안검사(D03) 문서를 1건씩 만듭니다(작성중). 육안검사의 결재 단위는 LOT이고, "그날 육안검사일지"는 입고일로 묶어 보여 주는 화면·출력입니다.

`answers`(선택) — 입고 화면에서 육안검사까지 입력한 경우. 형식은 2.2의 `fields`이며 현재는:

| 키 | 값 | 필수 |
|---|---|---|
| `appearance` (성상 및 이물혼입) | `양호` / `불량` | O |
| `packaging` (외/내포장) | `양호` / `불량` | O |
| `labeling` (표시사항) | `양호` / `불량` | O |
| `verdict` (최종판정) | `PASS` / `FAIL` | O |
| `has_coa` (시험성적서) | `유` / `무` | 아님 — 보내지 않음. 육안검사 문서 화면에서 D01 성적서 파일 연결 여부로 자동 제안됨 |

- D03 문서를 **새로 만들 때만** 채웁니다. 이미 있는 문서는 덮어쓰지 않습니다(`inspection_applied: False`).
- `answers.verdict`는 입고 판정(`ReceiptInput.judgment`)과 같은 값으로 보내 주세요. LOT 판정 반영은 수불이 `apply_incoming_judgment`로 직접 합니다.

```python
create_incoming_inspection(lot_id=..., staff_id=..., answers=None)
# -> {"lot_id": ..., "documents": [
#      {"type_code": "D01", "document_id": ..., "result": "created" | "existing"},
#      {"type_code": "D02", "document_id": ..., "result": "created" | "existing"},
#      {"type_code": "D03", "document_id": ..., "result": "created" | "existing",
#       "inspection_applied": bool}]}
```

| 상황 | 결과 |
|---|---|
| 없는 LOT / 입고 LOT 아님 / 입고 건 없는 LOT | `LOT_NOT_FOUND` 404 / `LOT_NOT_INCOMING` 409 / 거부 |
| `answers` 키·값 오류 | `VALIDATION_ERROR` 400 |

### 2.2 `get_incoming_inspection_form()` — 입고 화면 그리기

입고 화면의 육안검사 칸과 검증 기준. 쓰기 없음. 양식이 바뀌면 반환도 바뀌므로 화면에 하드코딩하지 마세요.

```python
get_incoming_inspection_form()
# -> {"fields": [
#       {"key": "appearance", "label": "성상 및 이물혼입", "type": "select",
#        "options": ["양호", "불량"], "required": True},
#       ...
#       {"key": "verdict", "label": "최종판정", "type": "select", "options": ["PASS", "FAIL"],
#        "option_labels": {"PASS": "적합", "FAIL": "부적합"}, "required": True},
#       {"key": "has_coa", "label": "시험성적서", "type": "select", "options": ["유", "무"],
#        "required": False}],
#     "guide": [{"title": "검사 기준", "rows": [["성상 및 이물혼입", "원료 고유의 색택, ..."], ...]}]}
```

### 2.3 `require_for_batch(*, batch_id, staff_id)` — 생산 시작 직후

제조(MANUFACTURE) 배치면 CCP-1P·2B·3P 일지를 만듭니다. 포장 배치는 없음.

```python
require_for_batch(batch_id=..., staff_id=...)
# -> {"production_batch_id": ..., "documents": [
#      {"type_code": "CCP-1P", "document_id": ..., "result": "created" | "existing",
#       "process_code": "1P"}, ...]}
```

없는 배치 `BATCH_NOT_FOUND` 404, 취소 배치 `BATCH_CANCELLED` 409.

### 2.4 `docs_for_lot(lot_id)` — LOT에 연결된 문서

```python
docs_for_lot(lot_id)
# -> {"lot_id": ..., "documents": [
#      {"document_id", "type_code", "status", "version",
#       "approved": {"request_id", "attempt", "closed_at"} | None,
#       "verdict": "PASS" | "FAIL" | None,    # 최신 승인본 기준(육안검사 문서)
#       "correcting": bool, "correction_reason": str | None}]}
```

### 2.5 `docs_for_batch(batch_id)` — 배치에 연결된 CCP 문서

```python
docs_for_batch(batch_id)
# -> {"production_batch_id": ..., "documents": [
#      {"document_id", "type_code", "process_code", "status", "version",
#       "summary": {"row_count", "latest": {"at", "phase", "verdict"} | None,
#                   "nonconforming_count", "deviation_count",
#                   "no_action", "pending", "no_checker", "checked"} | None}]}
```

`summary`(P11 — 생산 화면 [연결 문서]): CCP 일지마다 측정 행 수·최근 측정·이탈 행 수·개선조치 상태(이탈 행 중 개선조치 없음, 확인 대기, 확인자 없음, 확인됨). 기존 키는 그대로이고 키만 더함. 판정·상태 규칙은 CCP 대시보드와 같음.

### 2.6 `get_source_document(document_id)` — HOLD 근거 문서

`lot_holds.source_document_id`의 문서. 판단 근거로는 `approved`(최신 승인본)를 쓰세요. `current`는 결재 전·정정 중 내용일 수 있습니다.

```python
get_source_document(document_id)
# -> {"document_id", "type_code", "work_date", "status", "version",
#     "correcting": bool, "correction_reason": str | None,
#     "current": {"sections": [...], "deviations": [...]},
#     "approved": {"request_id", "attempt", "closed_at",
#                  "snapshot": {"sections": [...], "deviations": [...]}} | None}
```

없는 문서·삭제된 문서는 `DOCUMENT_NOT_FOUND` 404.

### 2.7 `ledger_approved_until()` — 수불대장 수정 잠금 기준

원료수불일지가 결재된 마지막 날짜(`datetime.date`, 월 단위라 그 달 말일). 수불은 이 날짜 이하의 수불 등록·정정을 막습니다. 원료수불일지(D04) 전에는 항상 `None`.

## 3. 문서가 수불 함수를 부르는 때

`apps.inventory.judgment.apply_incoming_judgment` — 육안검사(D03) 문서를 **작성완료**할 때 그 문서의 LOT에 한 번(정정 뒤 다시 작성완료 포함). 결재 승인·반려·작성 재개 때는 부르지 않습니다.

| 인자 | 문서 쪽이 넘기는 값 |
|---|---|
| `result` | 육안검사 문서의 최종판정 |
| `staff_id`, `judged_at` | 작성완료한 사람, 작성완료 시각 |
| `document_id` | 육안검사 문서 id |
| `reason` | 정정 중이면 정정 사유, 아니면 작성완료 때 입력한 판정 변경 사유(없으면 생략) |

`InventoryError`가 나면 작성완료를 취소하고 메시지를 화면에 그대로 보여 줍니다.

## 4. 수불에 요청

| 항목 | 요청 |
|---|---|
| 훅 `document_bridge.incoming_received` | `(*, lot_id)` → `(*, lot_id, staff_id, answers=None)`로 바꾸고 안에서 2.1 호출 |
| 입고 취소 | **결재중부터는 수불이 막음** — 취소 전 `docs_for_lot`에서 `status`가 `submitted`·`approved`·`correcting`인 문서가 있으면 거부. 그 밖의 경우 문서 쪽 처리는 미정, 훅 `incoming_receipt_cancelled`는 당분간 빈 함수 |
| 수불대장 | 2.7 `ledger_approved_until()` 이하 날짜의 수불 등록·정정을 막음 |
