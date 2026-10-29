# API 안내

화면(프런트엔드)이 서버에 보내는 HTTP API의 목록과 규칙입니다. 기능을 고치거나, 다른 프로그램에서 서버를 부르거나, 오류 문구의 원인을 찾을 때 봅니다. 읽는 분은 [기술 인수인계](../developer-guide.md)를 받는 개발자입니다.

> 현재 기준 2026-10-29 · 코드 기준 `feature/p16-admin-settings` `61d4b9f` · 목록은 `urls.py`·`api.py`에서 뽑아 코드와 1:1로 맞췄습니다.

## 파일 구성

| 파일 | 범위 | 경로 수 | 앱 | 상태 |
|---|---|---|---|---|
| [document.md](document.md) | 문서·결재·작성 요구·출력·생산일지·관리 설정 | 64경로 · 76개(메서드 기준) | documents · approvals · document_workflow · doc_requirements · production_log · admin_settings | 목록 + 76개 모두 상세 |
| [inventory.md](inventory.md) | 입고·재고·수불·생산·BOM·보류 | 42경로 · 53개(메서드 기준) | inventory | 목록 + 상세 — **수불 담당 확인 전 초안** |
| (없음) | 개발 콘솔 `/api/dev/` | 15경로 | devtools | 다루지 않음. `DEBUG`와 `HACCP_DEV_CONSOLE`을 켠 개발 설정에서만 경로가 생깁니다(`backend/config/urls.py`). |

DB를 직접 읽는 연동 계약(뷰·훅)은 API가 아니라 [문서 → 수불 인터페이스](../../reference/document-inventory-interface.md)·[수불 → 문서 인터페이스](../../reference/inventory-document-interface.md)에 있습니다.

## 공통 규칙 — 문서 쪽 (`document.md`)

| 항목 | 규칙 | 코드 |
|---|---|---|
| 기본 경로 | `/api/v1/` · 끝 슬래시 없음 | `backend/config/urls.py` |
| 요청 본문 | `Content-Type: application/json`, JSON 객체만. 정해지지 않은 키가 있으면 거부(400 `INVALID_REQUEST`, `details[].code = unknown_key`). 파일 올리기만 multipart | `apps/core/http.py` |
| 현재 사용자 | 헤더 `X-Staff-Id: <staff_id>`. 쓰기는 필수, 읽기는 API마다 다름(선택·불필요). 없으면 400 `STAFF_HEADER_MISSING`, 숫자가 아니거나 비활성 직원이면 403 `INVALID_STAFF` | `apps/staff/services.py::actor_from_header` |
| 인증 | **[테스트 버전]** 로그인·세션 없음. CSRF 대신 "사용자 지정 헤더 + JSON 본문"을 요구해 다른 출처의 단순 요청을 막음. **예외: 관리 설정(`/admin/…`) 쓰기는 CSRF 검사를 함** — `csrftoken` 쿠키(첫 화면이 발급) 값을 `X-CSRFToken` 헤더로 | `apps/documents/api.py` 머리말 · `apps/admin_settings/api.py` 머리말 |
| 오류 형식 | `{"code": "...", "message": "...", "details": [{"path", "code", "message", ...}]}` · `message`는 화면에 그대로 보이는 한국어 문장 | `apps/core/http.py::error_response` |
| 버전 확인 | 쓰기는 본문에 `expected_version`(화면이 본 문서 버전). 다르면 409 `VERSION_CONFLICT`, `details`에 `expected`·`current`·`updated_at` | `apps/documents/errors.py` |
| 실패 판정 순서 | 없음 404 → 상태가 안 맞음 409(`INVALID_TRANSITION` 등) → 버전이 안 맞음 409 | `apps/documents/services.py::_lock_failure` |
| 여러 건 처리 | `items` 또는 `*_ids` 배열, 한 번에 50건까지. 결과는 건별 성공·실패 요약 | `apps/core/batch.py` (`MAX_ITEMS = 50`) |

## 수불 쪽은 다릅니다 (`inventory.md`)

| 항목 | 문서 쪽 | 수불 쪽 |
|---|---|---|
| 기본 경로 | `/api/v1/` · 끝 슬래시 없음 | `/api/v1/inventory/` · **끝 슬래시 있음** |
| 현재 사용자 | 헤더 `X-Staff-Id` | **본문 `staff_id`** |
| CSRF | 검사 안 함(사용자 헤더 + JSON으로 대신) | 검사함 — GET이 준 `csrftoken` 쿠키를 `X-CSRFToken` 헤더로 |
| 모르는 키 | 400 `INVALID_REQUEST` | 받아들임(무시) |
| 같은 요청 두 번 | `expected_version`(낙관적 잠금) | `idempotency_key`(수불 기록을 만드는 요청) |
| 수량 | — | 기준단위 10진수(문자열 가능) |
| 목록 응답 | `{items, total, page, page_size}` | `{results}` + `count`(`limit`·`offset`) |
| 오류 형식 | `{code, message, details}` | `{"error": {"message", "fields"?, "code"?}}` — 수불 오류는 `code` 없음 |
| 업무 규칙 위반 | 대부분 409 | 대부분 **400** |
| 메서드 표시 | `@require_http_methods` | `@endpoint(...)` (`apps/inventory/api.py`) |

자세한 내용은 [inventory.md — 공통 규칙](inventory.md#공통-규칙--수불-쪽)에 있습니다.

## 엔드포인트 상세 틀

`document.md`는 엔드포인트마다 짧은 표(사용자·쿼리·본문·응답·오류·화면/기능)로 씁니다. 결재 올리기 [WF-A01](document.md#wf-a01)은 아래 틀을 모두 채운 긴 예시입니다. 새로 쓰거나 늘릴 때는 아래 순서를 따릅니다. 해당 없는 칸은 "없음".

| 칸 | 내용 |
|---|---|
| 제목 | `<a id="소문자 API ID"></a>` + `### API ID · 메서드 경로 — 하는 일` |
| 요약표 | 기능 ID(사용법 링크) · 화면 · 구현 함수 · 테스트 · 결정 |
| 요청 | 헤더 · 경로 값 · 쿼리 · 본문(이름·형·필수·설명) |
| 응답 | 상태 코드 · 형태 · 예시 JSON |
| 오류 | 상태 · `code` · 언제 · 화면 문구 (판정 순서대로) |
| 부수 효과 | 바뀌는 상태·다른 표·다른 기능 |
| 알아둘 점 | 제약, 테스트 버전 한정 사항 |

## ID와 연결

- **API ID**: 설계 때 붙인 번호를 그대로 씁니다(`DOC-A`·`APR-A`·`WF-A`·`REQ-A`·`PLG-A`·`ROLE-A`·`ADM-A`). 코드의 함수 설명 첫 줄에도 같은 ID가 있습니다. 번호가 없는 것은 `—`로 두고 새로 매기지 않습니다(필요하면 결정으로 정함).
- **기능 ID**: [문서·결재 기능 안내](../guide/document-guide.md)의 `F-…`와 같습니다. 한 기능이 API 여러 개를 쓰기도 합니다.
- **구현 지도**: `docs/reference/features/<영역>.yaml`의 `api:` 항목에 `spec:`(`docs/handover/api/document.md#<API ID 소문자>`)를 적어 기능 → API 상세로 바로 갑니다.

```text
사람용 기능 안내 (handover/document-guide.md, F-WF-01)
   ↕ 기능 ID
구현 지도 (reference/features/approval.yaml, api[].spec)
   ↕ API ID
API 명세 (handover/api/document.md#wf-a01)
```


## 오류 코드 모음

문서 쪽·관리 설정 API가 돌려주는 `code` 전체입니다(코드의 오류 클래스에서 뽑음). `message`가 화면에 그대로 보이며, 상황에 따라 더 자세한 문장으로 바뀌기도 합니다. 같은 이름(`VALIDATION_ERROR`·`INVALID_FILTER`·`TRANSACTION_REQUIRED`)은 여러 영역에 있고 뜻이 같습니다.

| 상태 | code | 기본 문구 | 영역 · 정의 위치 |
|---|---|---|---|
| 400 | `COMMENT_REQUIRED` | 반려 사유를 입력하세요. | 결재 · `approvals/errors.py` |
| 400 | `COMPLETION_INCOMPLETE` | 작성완료할 수 없습니다. 빠진 항목을 채우세요. | 문서 · `documents/errors.py` |
| 400 | `FILE_REJECTED` | 올릴 수 없는 파일입니다. | 문서 · `documents/errors.py` |
| 400 | `INVALID_DECISION` | 결재 처리 값을 확인하세요. | 결재 · `approvals/errors.py` |
| 400 | `INVALID_FILTER` | 조회 조건을 확인하세요. | 문서 · `documents/errors.py` |
| 400 | `INVALID_REQUEST` | 요청 형식이 올바르지 않습니다. | 공통 · `core/http.py` |
| 400 | `INVALID_SLOTS` | 결재선(슬롯)을 확인하세요. | 결재 · `approvals/errors.py` |
| 400 | `NOT_PERIODIC` | 주기 작성 요구 양식이 아닙니다. | 작성 요구 · `doc_requirements/errors.py` |
| 400 | `NOT_PRINTABLE_TYPE` | 이 양식은 출력하지 않습니다. | 결재·출력 · `document_workflow/printing.py` |
| 400 | `NO_CHANGES` | 바꿀 내용이 없습니다. | 문서 · `documents/errors.py` |
| 400 | `PLG_TEMPLATE_INVALID` | 템플릿 공정 구성을 확인하세요. | 생산일지 · `production_log/errors.py` |
| 400 | `STAFF_HEADER_MISSING` | 현재 사용자(X-Staff-Id)를 지정하세요. | 사용자·역할 · `staff/services.py` |
| 400 | `SYSTEM_SECTION` | 이 영역은 시스템이 채웁니다. 직접 쓸 수 없습니다. | 문서 · `documents/errors.py` |
| 400 | `VALIDATION_ERROR` | 입력값을 확인하세요. | 문서 · `documents/errors.py` · 관리 설정 · `admin_settings/errors.py` |
| 403 | `INVALID_STAFF` | 등록되지 않은 사용자입니다. | 사용자·역할 · `staff/services.py` |
| 403 | `NOT_CHECKER` | 확인자나 HACCP팀장만 확인할 수 있습니다. | 문서 · `documents/errors.py` |
| 403 | `NOT_REQUESTER` | 상신한 사람이나 HACCP팀장만 취소할 수 있습니다. | 결재 · `approvals/errors.py` |
| 403 | `NOT_YOUR_SLOT` | 이 결재 칸을 처리할 수 있는 사람(결재자·후보)이 아닙니다. | 결재 · `approvals/errors.py` |
| 403 | `ROLE_REQUIRED` | 이 양식의 담당자나 HACCP팀장만 할 수 있습니다. | 사용자·역할 · `staff/roles.py` |
| 404 | `ADM_ITEM_NOT_FOUND` | 품목을 찾을 수 없습니다. | 관리 설정 · `admin_settings/errors.py` |
| 404 | `ADM_STAFF_NOT_FOUND` | 직원을 찾을 수 없습니다. | 관리 설정 · `admin_settings/errors.py` |
| 404 | `APPROVAL_NOT_FOUND` | 결재 칸을 찾을 수 없습니다. | 결재 · `approvals/errors.py` |
| 404 | `BATCH_NOT_FOUND` | 생산 배치를 찾을 수 없습니다. | 작성 요구 · `doc_requirements/errors.py` |
| 404 | `DEVIATION_NOT_FOUND` | 개선조치를 찾을 수 없습니다. | 문서 · `documents/errors.py` |
| 404 | `DOCUMENT_NOT_FOUND` | 문서를 찾을 수 없습니다. | 문서 · `documents/errors.py` |
| 404 | `FILE_NOT_FOUND` | 파일을 찾을 수 없습니다. | 문서 · `documents/errors.py` |
| 404 | `LOT_NOT_FOUND` | 입고 LOT을 찾을 수 없습니다. | 작성 요구 · `doc_requirements/errors.py` |
| 404 | `PLG_CCP_DOC_MISSING` | 이 배치에 그 CCP 일지가 없습니다. | 생산일지 · `production_log/logbook.py` |
| 404 | `PLG_NOT_PRODUCTION_LOG` | 생산일지가 아닙니다. | 생산일지 · `production_log/logbook.py` |
| 404 | `PLG_PROCESS_NOT_FOUND` | 공정을 찾을 수 없습니다. | 생산일지 · `production_log/errors.py` |
| 404 | `PLG_TEMPLATE_NOT_FOUND` | 공정 템플릿을 찾을 수 없습니다. | 생산일지 · `production_log/errors.py` |
| 404 | `REQUEST_NOT_FOUND` | 결재 요청을 찾을 수 없습니다. | 결재 · `approvals/errors.py` |
| 404 | `TEMPLATE_NOT_FOUND` | 양식을 찾을 수 없습니다. | 문서 · `documents/errors.py` |
| 409 | `ALREADY_CHECKED` | 이미 확인된 개선조치입니다. | 문서 · `documents/errors.py` |
| 409 | `ALREADY_DECIDED` | 이미 처리한 결재 칸입니다. | 결재 · `approvals/errors.py` |
| 409 | `BATCH_CANCELLED` | 취소된 생산 배치입니다. | 작성 요구 · `doc_requirements/errors.py` |
| 409 | `CORRECTION_HAS_CHANGES` | 정정 시작 뒤 수정한 내용이 있어 취소할 수 없습니다. 작성완료 후 재상신하세요. | 문서 · `documents/errors.py` |
| 409 | `DOCUMENT_LOCKED` | 현재 상태에서는 문서를 수정할 수 없습니다. | 문서 · `documents/errors.py` |
| 409 | `DOCUMENT_NOT_DELETABLE` | 현재 상태이거나 상신 이력이 있어 삭제할 수 없습니다. | 문서 · `documents/errors.py` |
| 409 | `DOCUMENT_NOT_SKIPPABLE` | 작성 안 함으로 바꿀 수 없는 문서입니다(주기 작성 요구 문서만). | 문서 · `documents/errors.py` |
| 409 | `DUPLICATE_ROUND` | 같은 측정시점이 이미 있습니다. | 문서 · `documents/errors.py` |
| 409 | `FILES_NOT_ALLOWED` | 이 양식은 파일을 첨부하지 않습니다. | 문서 · `documents/errors.py` |
| 409 | `FILE_ALREADY_LINKED` | 이미 연결된 파일입니다. | 문서 · `documents/errors.py` |
| 409 | `FILE_NOT_LINKED` | 이 문서에 연결된 파일이 아닙니다. | 문서 · `documents/errors.py` |
| 409 | `FILE_TEMPLATE_MISMATCH` | 다른 종류 문서의 파일은 연결할 수 없습니다. | 문서 · `documents/errors.py` |
| 409 | `INVALID_TRANSITION` | 현재 상태에서 할 수 없는 상태 변경입니다. | 문서 · `documents/errors.py` |
| 409 | `INVENTORY_REJECTED` | 수불이 판정을 받지 않았습니다. | 수불 연동 · `doc_effects/errors.py` |
| 409 | `LOT_NOT_INCOMING` | 입고 LOT이 아닙니다. | 작성 요구 · `doc_requirements/errors.py` |
| 409 | `NOT_PRINTABLE_STATUS` | 작성완료 뒤 출력할 수 있습니다. | 결재·출력 · `document_workflow/printing.py` |
| 409 | `NO_APPROVAL_FORM` | 결재 없는 양식은 상신할 수 없습니다. | 결재·출력 · `document_workflow/services.py` |
| 409 | `NO_APPROVAL_LINE` | 결재선을 만들 수 없습니다. | 사용자·역할 · `staff/roles.py` |
| 409 | `OPEN_REQUEST_EXISTS` | 이 문서는 이미 결재 진행 중입니다. | 결재 · `approvals/errors.py` |
| 409 | `PLG_BATCH_CANCELLED` | 취소된 배치의 생산일지는 바꿀 수 없습니다. | 생산일지 · `production_log/logbook.py` |
| 409 | `PLG_BUILTIN_LOCKED` | 기본 제공 공정은 이 항목을 바꿀 수 없습니다. | 생산일지 · `production_log/errors.py` |
| 409 | `PLG_CONFIRM_REQUIRED` | 입력 방식을 바꾸면 이 공정을 쓰는 템플릿에도 반영됩니다. 확인하세요. | 생산일지 · `production_log/errors.py` |
| 409 | `PLG_IN_USE` | 이미 쓰인 적이 있어 삭제할 수 없습니다. 사용 중지하세요. | 생산일지 · `production_log/errors.py` |
| 409 | `PLG_LINKED_UNAVAILABLE` | 수불·생산 연동 데이터를 읽지 못해 처리할 수 없습니다. 잠시 뒤 다시 시도하세요. | 생산일지 · `production_log/logbook.py` |
| 409 | `PLG_NAME_TAKEN` | 같은 이름이 이미 있습니다. | 생산일지 · `production_log/errors.py` |
| 409 | `PLG_SIMILAR_NAME` | 비슷한 이름이 있습니다. 그래도 저장하려면 확인하세요. | 생산일지 · `production_log/errors.py` |
| 409 | `REQUEST_CLOSED` | 이미 끝난 결재 요청입니다. | 결재 · `approvals/errors.py` |
| 409 | `SECTION_ROW_NOT_FOUND` | 대상 행이 이 문서에 없습니다. | 문서 · `documents/errors.py` |
| 409 | `TEMPLATE_INACTIVE` | 사용할 수 없는 양식입니다. | 문서 · `documents/errors.py` |
| 409 | `TEMPLATE_REQUIREMENT_ONLY` | 이 양식은 입고·생산 시작 때 자동으로 만들어집니다. | 문서 · `documents/errors.py` |
| 409 | `VERSION_CONFLICT` | 다른 사용자가 먼저 수정했습니다. 최신 내용을 다시 불러오세요. | 문서 · `documents/errors.py` · 관리 설정 · `admin_settings/errors.py`("다른 사람이 먼저 저장했습니다. 새로고침한 뒤 다시 저장하세요.") |
| 500 | `RULES_INVALID` | 주기 규칙 파일이 올바르지 않습니다. | 작성 요구 · `doc_requirements/errors.py` |
| 500 | `SIMULATED_FAILURE` | 롤백 확인을 위한 의도된 실패입니다. | 작성 요구 · `doc_requirements/errors.py` |
| 500 | `TRANSACTION_REQUIRED` | 트랜잭션 안에서 호출해야 합니다. | 문서 · `documents/errors.py` |
| 503 | `INVENTORY_NOT_CONFIGURED` | 수불 판정 연동이 설정되지 않아 육안검사를 작성완료할 수 없습니다. | 수불 연동 · `doc_effects/errors.py` |
| 503 | `REQ_SOURCE_MISSING` | 수불·생산 뷰가 아직 준비되지 않았습니다. | 작성 요구 · `doc_requirements/errors.py` |

- **관리 설정**의 입력 오류는 새 `code`를 만들지 않고 400 `VALIDATION_ERROR`의 `details[].code`로 이유를 알립니다: `invalid` · `required` · `unknown_key` · `too_long` · `invalid_process` · `not_producible` · `duplicate_code` · `confirm_required` · `last_active_staff` · `setup_finished` · `duplicate` · `unknown_staff` · `inactive_staff` · `unknown_form`([document.md — 9. 관리 설정](document.md#9-관리-설정adm)).
- 관리 설정 쓰기에서 CSRF 쿠키·헤더가 없거나 맞지 않으면 Django가 403을 돌려줍니다(위 형식이 아닌 HTML). 화면은 "보안 토큰이 만료됐습니다 — 새로고침 후 다시 시도하세요"를 보입니다.
- P16부터 역할(문서 권한)이 DB에 있어 409 `ROLE_CONFIG_INVALID`(역할 설정 파일 오류)는 없어졌습니다.
- 500 `TRANSACTION_REQUIRED`는 코드 내부 사용 오류라 화면에서 보이면 개발자에게 알립니다.
- 503 `REQ_SOURCE_MISSING`은 수불 마이그레이션(뷰)이 적용되지 않았을 때 납니다([설치 안내](../installation.md)).
- 503 `INVENTORY_NOT_CONFIGURED`는 D03 작성완료에 필요한 수불 판정 함수 설정이 없을 때 납니다.

## 고칠 때

- `urls.py`에 경로를 더하거나 바꾸면 해당 파일의 목록 표를 같이 고칩니다.
- 본문 키·응답 형태·오류 코드를 바꾸면 상세와 구현 지도(`api:`·`errors:`)를 같이 고칩니다.
- 화면 문구(`message`)를 바꾸면 기능 안내의 "이럴 때 막혀요" 표와 위 오류 코드 모음도 고칩니다.
