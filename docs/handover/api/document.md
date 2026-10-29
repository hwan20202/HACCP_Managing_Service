# API 명세 — 문서 쪽

문서·결재·작성 요구·출력·생산일지·관리 설정 화면이 서버에 보내는 API입니다. 공통 규칙(사용자 헤더·오류 형식·버전 확인)과 오류 코드 전체는 [API 안내](README.md)를 먼저 봅니다. 화면에서 어떻게 쓰는지는 [문서·결재 기능 안내](../guide/document-guide.md)에 있습니다.

> 현재 기준 2026-10-29 · 코드 기준 `feature/p16-admin-settings` `61d4b9f` · 경로는 모두 `/api/v1` 아래(표에는 뒷부분만) · 목록 64경로 · 76개(메서드 기준 — P16 관리 설정 9경로 · 11개 추가)는 `urls.py`와 1:1로 맞춤

## 읽는 법

- **사용자** 칸: `X-Staff-Id` 헤더가 필수 / 선택 / 필요 없음. 쓰기 요청은 모두 필수입니다.
- **본문**은 JSON 객체입니다. 적힌 키 말고 다른 키를 보내면 400 `INVALID_REQUEST`입니다.
- **오류** 칸에는 그 API에서 나는 주요 오류만 적습니다. 모든 쓰기 요청에서 날 수 있는 400 `INVALID_REQUEST` · 400 `STAFF_HEADER_MISSING` · 403 `INVALID_STAFF`는 반복하지 않습니다. (P16부터 역할은 DB 문서 권한이라 역할 설정 오류 409 `ROLE_CONFIG_INVALID`는 없어졌습니다.)
- **관리 설정(ADM)** API는 규칙이 조금 다릅니다: 쓰기에 CSRF 헤더 `X-CSRFToken`이 필요하고, 입력 오류는 400 `VALIDATION_ERROR` + `details[].code`로 옵니다([9. 관리 설정](#9-관리-설정adm)).
- **일괄 결과**는 `{action, total, succeeded, failed, results: [{ok, ...}]}` 모양이고, 일부가 실패해도 200입니다.
- API ID가 `—`인 것은 설계 때 번호가 없던 것입니다.

## 목록

**1. 직원·역할·양식**

| API ID | 메서드 | 경로 | 하는 일 | 기능 ID | 구현 | 상세 |
|---|---|---|---|---|---|---|
| `DOC-A01` | GET | `/staff` | 직원 목록(현재 사용자 고르기) | — | `documents/api.py::staff_list` | [보기](#doc-a01) |
| `ROLE-A01` | GET | `/roles` | 문서 권한 읽기(읽기 전용, 헤더가 있으면 내 역할 포함) | `F-ROLE-01` | `documents/api.py::roles_view` | [보기](#role-a01) |
| `DOC-A02` | GET | `/templates` | 양식 목록 | — | `documents/api.py::template_list` | [보기](#doc-a02) |
| `DOC-A03` | GET | `/templates/{template_id}` | 양식 한 개(칸 정의) | — | `documents/api.py::template_detail` | [보기](#doc-a03) |

**2. 문서**

| API ID | 메서드 | 경로 | 하는 일 | 기능 ID | 구현 | 상세 |
|---|---|---|---|---|---|---|
| `DOC-A04` | GET | `/documents` | 문서 목록(기간·양식·상태 거르기, 쪽 나눔) | — | `documents/api.py::document_collection` | [보기](#doc-a04) |
| `DOC-A06` | POST | `/documents` | 새 문서 | — | `documents/api.py::document_collection` | [보기](#doc-a06) |
| `DOC-A05` | GET | `/documents/{document_id}` | 문서 상세(권한·결재선 미리 보기 포함) | — | `documents/api.py::document_item` | [보기](#doc-a05) |
| `DOC-A07` | PATCH | `/documents/{document_id}` | 문서 수정 | — | `documents/api.py::document_item` | [보기](#doc-a07) |
| `DOC-A08` | DELETE | `/documents/{document_id}` | 문서 삭제 | — | `documents/api.py::document_item` | [보기](#doc-a08) |
| `DOC-A09` | POST | `/documents/{document_id}/complete` | 작성완료 | — | `documents/api.py::document_complete` | [보기](#doc-a09) |
| `DOC-A10` | POST | `/documents/{document_id}/reopen` | 작성 재개 | — | `documents/api.py::document_reopen` | [보기](#doc-a10) |
| `DOC-A24` | POST | `/documents/batch-skip` | 작성 안 함(여러 건) | — | `documents/api.py::batch_skip` | [보기](#doc-a24) |
| `DOC-A25` | POST | `/documents/{document_id}/unskip` | 작성 안 함 되돌리기 | — | `documents/api.py::document_unskip` | [보기](#doc-a25) |
| `DOC-A18` | POST | `/documents/{document_id}/correction` | 정정 시작 | `F-WF-05` | `documents/api.py::document_correction` | [보기](#doc-a18) |
| `DOC-A19` | POST | `/documents/{document_id}/correction/cancel` | 정정 취소 | `F-WF-05` | `documents/api.py::document_correction_cancel` | [보기](#doc-a19) |
| `DOC-A20` | POST | `/documents/batch-inspector` | 점검자 일괄 지정 | — | `documents/api.py::batch_inspector` | [보기](#doc-a20) |
| `DOC-A21` | GET | `/documents/brief` | 문서 요약 여러 건(?ids=, 1~50개) | — | `documents/api.py::document_brief` | [보기](#doc-a21) |
| `DOC-A26` | GET | `/documents/recent-values` | 최근 입력 값(?type_code=&field=) | — | `documents/api.py::recent_values` | [보기](#doc-a26) |

**3. 이탈·개선조치**

| API ID | 메서드 | 경로 | 하는 일 | 기능 ID | 구현 | 상세 |
|---|---|---|---|---|---|---|
| `DOC-A15` | POST | `/documents/{document_id}/deviations` | 개선조치 쓰기 | `F-CCP-02` | `documents/api.py::deviation_collection` | [보기](#doc-a15) |
| `DOC-A16` | PATCH | `/deviations/{deviation_id}` | 개선조치 수정 | `F-CCP-02` | `documents/api.py::deviation_item` | [보기](#doc-a16) |
| `DOC-A17` | DELETE | `/deviations/{deviation_id}` | 개선조치 삭제 | `F-CCP-02` | `documents/api.py::deviation_item` | [보기](#doc-a17) |
| `DOC-A22` | GET | `/deviations/pending` | 확인 대기 목록(?date=&mine=&summary=) | `F-CCP-03` | `documents/api.py::deviations_pending` | [보기](#doc-a22) |
| `DOC-A23` | POST | `/deviations/{deviation_id}/check` | 개선조치 확인 | `F-CCP-03` | `documents/api.py::deviation_check` | [보기](#doc-a23) |

**4. 증빙 파일**

| API ID | 메서드 | 경로 | 하는 일 | 기능 ID | 구현 | 상세 |
|---|---|---|---|---|---|---|
| `DOC-A11` | POST | `/documents/{document_id}/files` | 파일 올리기(multipart) 또는 기존 파일 연결 | — | `documents/api.py::document_files` | [보기](#doc-a11) |
| `DOC-A12` | DELETE | `/documents/{document_id}/files/{file_id}` | 파일 연결 끊기(?expected_version=) | — | `documents/api.py::document_file_item` | [보기](#doc-a12) |
| `DOC-A14` | GET | `/files` | 이전 파일 검색 | — | `documents/api.py::file_collection` | [보기](#doc-a14) |
| `DOC-A13` | GET | `/files/{file_id}` | 파일 보기(inline) | — | `documents/api.py::file_item` | [보기](#doc-a13) |

**5. 결재**

| API ID | 메서드 | 경로 | 하는 일 | 기능 ID | 구현 | 상세 |
|---|---|---|---|---|---|---|
| `WF-A01` | POST | `/documents/{document_id}/submit` | 상신·재상신 | `F-WF-01` | `document_workflow/api.py::submit` | [보기](#wf-a01) |
| `WF-A02` | POST | `/approvals/{approval_id}/decision` | 승인·반려 | `F-WF-02` | `document_workflow/api.py::decision` | [보기](#wf-a02) |
| `WF-A03` | POST | `/approvals/batch-decision` | 일괄 승인(반려 없음) | `F-WF-06` | `document_workflow/api.py::batch_decision` | [보기](#wf-a03) |
| `WF-A04` | POST | `/documents/batch-submit` | 일괄 상신 | `F-WF-06` | `document_workflow/api.py::batch_submit` | [보기](#wf-a04) |
| `WF-A05` | GET | `/workflow/batch-config` | 일괄 처리 설정 | `F-WF-06` | `document_workflow/api.py::batch_config` | [보기](#wf-a05) |
| `WF-F05` | POST | `/approval-requests/{request_id}/cancel` | 상신 취소(본문 없음) | `F-WF-04` | `document_workflow/api.py::cancel_submission` | [보기](#wf-f05) |
| `APR-A01` | GET | `/approval-inbox` | 결재함(?box=pending\|done) | `F-WF-02` | `approvals/api.py::approval_inbox` | [보기](#apr-a01) |
| `APR-A02` | GET | `/approval-requests/{request_id}` | 결재 요청 상세(상신 당시 내용) | — | `approvals/api.py::request_detail` | [보기](#apr-a02) |
| `APR-A03` | GET | `/documents/{document_id}/approval-requests` | 문서의 결재 회차 목록 | — | `approvals/api.py::document_requests` | [보기](#apr-a03) |

**6. 작성 요구·묶음·대시보드**

| API ID | 메서드 | 경로 | 하는 일 | 기능 ID | 구현 | 상세 |
|---|---|---|---|---|---|---|
| `REQ-A01` | GET | `/lots/{lot_id}/documents` | LOT별 연결 문서 | — | `doc_requirements/api.py::lot_documents` | [보기](#req-a01) |
| `REQ-A02` | GET | `/batches/{batch_id}/documents` | 배치별 연결 문서 | — | `doc_requirements/api.py::batch_documents` | [보기](#req-a02) |
| `REQ-A03` | GET | `/incoming-inspections` | 입고일 묶음(?received_date=) | — | `doc_requirements/api.py::incoming_inspections` | [보기](#req-a03) |
| `REQ-A04` | GET | `/periodic-bundles` | 주 묶음(?type_code=&week_start=) | — | `doc_requirements/api.py::periodic_bundles` | [보기](#req-a04) |
| `REQ-A05` | POST | `/periodic-runs` | 기간의 주기 문서 만들기 | — | `doc_requirements/api.py::periodic_runs` | [보기](#req-a05) |
| `REQ-A06` | POST | `/periodic-documents` | 그날 주기 문서 찾거나 만들기 | — | `doc_requirements/api.py::periodic_documents` | [보기](#req-a06) |
| `REQ-A07` | GET | `/periodic-rules` | 주기 규칙 목록 | — | `doc_requirements/api.py::periodic_rules` | [보기](#req-a07) |
| `REQ-A08` | GET | `/todo` | 작성 필요 목록(?date=&mine=) | — | `doc_requirements/api.py::todo_list` | [보기](#req-a08) |
| `REQ-A09` | GET | `/ccp-dashboard` | CCP 현황(?date=) | `F-CCP-01` | `doc_requirements/api.py::ccp_dashboard` | [보기](#req-a09) |

**7. 출력**

| API ID | 메서드 | 경로 | 하는 일 | 기능 ID | 구현 | 상세 |
|---|---|---|---|---|---|---|
| `WF-A06` | GET | `/print/sheet` | 종이 한 장 데이터(읽기 전용) | — | `document_workflow/api.py::print_sheet` | [보기](#wf-a06) |

**8. 생산일지·생산 기준정보**

| API ID | 메서드 | 경로 | 하는 일 | 기능 ID | 구현 | 상세 |
|---|---|---|---|---|---|---|
| `PLG-A01` | GET | `/production-logs/{document_id}/linked` | 연동 값 조회(수불·CCP 일지) | — | `production_log/api.py::production_log_linked` | [보기](#plg-a01) |
| `PLG-A02` | POST | `/production-logs/{document_id}/template-rows` | 템플릿 줄 가져오기(일지에는 쓰지 않음) | — | `production_log/api.py::production_log_template_rows` | [보기](#plg-a02) |
| `PLG-A03` | POST | `/production-logs/{document_id}/save-template` | 일지 공정을 템플릿으로 저장 | — | `production_log/api.py::production_log_save_template` | [보기](#plg-a03) |
| `PLG-A04` | GET | `/production-logs/{document_id}/ccp-values` | CCP 값(?kind=) | — | `production_log/api.py::production_log_ccp_values` | [보기](#plg-a04) |
| `PLG-A05` | POST | `/production-logs/{document_id}/register-process` | 일지에서 공정 등록 | — | `production_log/api.py::production_log_register_process` | [보기](#plg-a05) |
| `PLG-A06` | GET | `/processes` | 공정 목록(?q=&kind=&status=) | — | `production_log/api.py::processes` | [보기](#plg-a06) |
| `PLG-A06` | POST | `/processes` | 일반 공정 추가 | — | `production_log/api.py::processes` | [보기](#plg-a06) |
| `—` | GET | `/processes/{process_id}` | 공정 한 개 | — | `production_log/api.py::process_item` | [보기](#plg-a06-item) |
| `—` | PATCH | `/processes/{process_id}` | 공정 수정 | — | `production_log/api.py::process_item` | [보기](#plg-a06-item) |
| `—` | DELETE | `/processes/{process_id}` | 공정 삭제 | — | `production_log/api.py::process_item` | [보기](#plg-a06-item) |
| `—` | POST | `/processes/{process_id}/active` | 사용 중지·다시 사용 | — | `production_log/api.py::process_active` | [보기](#plg-a06-active) |
| `PLG-A07` | GET | `/process-templates` | 공정 템플릿 목록 | — | `production_log/api.py::templates` | [보기](#plg-a07) |
| `PLG-A07` | POST | `/process-templates` | 공정 템플릿 추가 | — | `production_log/api.py::templates` | [보기](#plg-a07) |
| `—` | GET | `/process-templates/{template_id}` | 템플릿 한 개 | — | `production_log/api.py::template_item` | [보기](#plg-a07-item) |
| `—` | PATCH | `/process-templates/{template_id}` | 템플릿 수정 | — | `production_log/api.py::template_item` | [보기](#plg-a07-item) |
| `—` | DELETE | `/process-templates/{template_id}` | 템플릿 삭제 | — | `production_log/api.py::template_item` | [보기](#plg-a07-item) |
| `—` | POST | `/process-templates/{template_id}/copy` | 템플릿 복사 | — | `production_log/api.py::template_copy` | [보기](#plg-a07-copy) |
| `—` | POST | `/process-templates/{template_id}/active` | 사용 중지·다시 사용 | — | `production_log/api.py::template_active` | [보기](#plg-a07-active) |
| `PLG-A08` | GET | `/master-history` | 변경 이력(?target=process\|template&id=) | — | `production_log/api.py::master_history` | [보기](#plg-a08) |

**9. 관리 설정(ADM)**

| API ID | 메서드 | 경로 | 하는 일 | 기능 ID | 구현 | 상세 |
|---|---|---|---|---|---|---|
| `ADM-A01` | GET | `/admin/item-ccp` | 반제품 품목별 CCP 목록(?q=&include_inactive=&only_own=) | `F-ADM-04` | `admin_settings/api.py::item_ccp_list` | [보기](#adm-a01) |
| `ADM-A02` | PUT | `/admin/item-ccp/{item_id}` | 품목 CCP 저장 | `F-ADM-04` | `admin_settings/api.py::item_ccp_item` | [보기](#adm-a02) |
| `ADM-A03` | GET | `/admin/staff` | 직원 목록 + 역할 요약(?q=&state=) | `F-ADM-01` `F-ADM-02` | `admin_settings/api.py::staff_collection` | [보기](#adm-a03) |
| `ADM-A05` | POST | `/admin/staff` | 직원 등록(처음 설정 포함) | `F-ADM-01` `F-ADM-02` | `admin_settings/api.py::staff_collection` | [보기](#adm-a05) |
| `ADM-A04` | GET | `/admin/staff/next-code` | 직원 코드 제안 | `F-ADM-01` `F-ADM-02` | `admin_settings/api.py::staff_next_code` | [보기](#adm-a04) |
| `ADM-A06` | PATCH | `/admin/staff/{staff_id}` | 직원 이름 수정 | `F-ADM-02` | `admin_settings/api.py::staff_item` | [보기](#adm-a06) |
| `ADM-A08` | POST | `/admin/staff/{staff_id}/active` | 비활성·다시 활성(처음 설정은 다시 활성만) | `F-ADM-01` `F-ADM-02` | `admin_settings/api.py::staff_active` | [보기](#adm-a08) |
| `ADM-A07` | GET | `/admin/staff/{staff_id}/impact` | 비활성 영향(읽기) | `F-ADM-01` `F-ADM-02` | `admin_settings/api.py::staff_impact` | [보기](#adm-a07) |
| `ADM-A09` | GET | `/admin/roles` | 문서 권한 편집용 읽기(비활성 사람 포함) | `F-ADM-03` | `admin_settings/api.py::roles_view` | [보기](#adm-a09) |
| `ADM-A10` | PUT | `/admin/roles` | 문서 권한 저장(팀장·담당자·작성 권한자) | `F-ADM-03` | `admin_settings/api.py::roles_view` | [보기](#adm-a10) |
| `ADM-A11` | GET | `/admin/history` | 관리 설정 변경 이력(?target=item_ccp\|staff\|roles&target_id=&limit=) | `F-ADM-02` `F-ADM-03` `F-ADM-04` | `admin_settings/api.py::history` | [보기](#adm-a11) |


## 상세

### 1. 직원·역할·양식

<a id="doc-a01"></a>
#### DOC-A01 · GET `/staff` — 직원 목록

| | |
|---|---|
| 사용자 | 필요 없음 |
| 쿼리 | `include_inactive` = `0`(기본) / `1` — 1이면 비활성 직원도 포함하고 `is_active`를 붙임 |
| 응답 | 200 `{items: [...]}` |
| 오류 | 400 `INVALID_REQUEST`(include_inactive가 0·1이 아님) |
| 화면 | 화면 오른쪽 위 **현재 사용자** 고르기 · 점검자 고르기 |

<a id="role-a01"></a>
#### ROLE-A01 · GET `/roles` — 문서 권한 읽기

| | |
|---|---|
| 사용자 | 선택 — 보내면 응답에 내 역할(`me`: `is_leader`·`owner_of`·`writer_of`)이 붙음 |
| 응답 | 200 `{leaders, forms, warnings, version, setup, reload}` · `forms[]` = 활성 양식마다 `{type_code, name, slots[{slot_no, role, label}], owners, writers, submittable, block_reason}` · `version` = 문서 권한 전체 버전 · `setup` = `{empty: 사람 0명, leaders: 활성 팀장 수, blocked_forms: [상신 불가 양식]}` · `reload` = `"immediate"`(저장 즉시 다음 요청부터). P16에서 `config_error`는 없어짐 |
| 화면·기능 | **[문서 권한]** 화면 머리·결재 영역 미리 보기·현재 사용자 역할 요약 · `F-ROLE-01` · 읽기 전용. 고치기는 [`ADM-A09`](#adm-a09)·[`ADM-A10`](#adm-a10)(원본은 DB 표 `role_*` — [ERD](../erd/document.md#관리-설정)) |

<a id="doc-a02"></a>
#### DOC-A02 · GET `/templates` — 양식 목록

| | |
|---|---|
| 사용자 | 필요 없음 |
| 응답 | 200 `{items: [...]}` |

<a id="doc-a03"></a>
#### DOC-A03 · GET `/templates/{template_id}` — 양식 한 개

| | |
|---|---|
| 사용자 | 필요 없음 |
| 응답 | 200 양식 정의(영역·칸·관리기준 안내). 화면은 이것으로 작성 폼을 그림 |
| 오류 | 404 `TEMPLATE_NOT_FOUND` |

### 2. 문서

문서 상태는 `draft`(작성중) · `completed`(작성완료) · `submitted`(결재중) · `approved`(승인) · `rejected`(반려) · `correcting`(정정 중) · `skipped`(작성 안 함)입니다. 수정할 수 있는 상태는 작성중·반려·정정 중입니다.

<a id="doc-a04"></a>
#### DOC-A04 · GET `/documents` — 문서 목록

| | |
|---|---|
| 사용자 | 필요 없음 |
| 쿼리 | `from`·`to`(작업일) · `template_id` · `status`(위 상태 코드) · `author_id` · `owner_id`(그 사람이 담당인 양식 — [내 담당 양식]) · `target`(대상 글자, 1~50자) · `correcting`(`true`/`false`) · `page`(1부터) |
| 응답 | 200 `{items, total, page, page_size: 20}`. 입고일·주 단위로 묶인 줄이 함께 옴 |
| 오류 | 400 `VALIDATION_ERROR`(조건 형식) |
| 화면 | **문서함** 전체 문서 탭 |

<a id="doc-a06"></a>
#### DOC-A06 · POST `/documents` — 새 문서

| | |
|---|---|
| 사용자 | 필수 |
| 본문 | `template_id`(필수) · `subject` · `work_date` · `due_at` · `sections`(영역별 처음 값) |
| 응답 | 201 문서 |
| 오류 | 404 `TEMPLATE_NOT_FOUND` · 409 `TEMPLATE_INACTIVE` · 409 `TEMPLATE_REQUIREMENT_ONLY`(입고·생산·주기로만 만드는 양식 — 업무 양식은 전부 해당) · 400 `VALIDATION_ERROR` · 403 `ROLE_REQUIRED` |
| 알아둘 점 | 지금 업무 양식은 모두 자동 생성이라, 이 API로 만들 수 있는 것은 초기 예시 양식뿐입니다. 주기 점검표는 `REQ-A06`을 씁니다. |

<a id="doc-a05"></a>
#### DOC-A05 · GET `/documents/{document_id}` — 문서 상세

| | |
|---|---|
| 사용자 | 선택 — 보내면 그 사람 기준 권한(`permissions`: 수정·작성완료·상신 등 가능 여부)과 결재선 미리 보기가 붙음 |
| 응답 | 200 문서(기본정보·영역 값·상태·`version`) + 역할 정보 |
| 오류 | 404 `DOCUMENT_NOT_FOUND` |
| 알아둘 점 | 화면은 버튼 활성 여부를 이 응답의 `permissions`로 정합니다. 화면에서 권한을 다시 계산하지 않습니다. |

<a id="doc-a07"></a>
#### DOC-A07 · PATCH `/documents/{document_id}` — 문서 수정

| | |
|---|---|
| 사용자 | 필수 · 작성 권한(담당자·작성 권한자·HACCP팀장·그 문서의 점검자) |
| 본문 | `expected_version`(필수) · `document`: `{subject, work_date, due_at}` 중 바꿀 것 · `sections`: `{add: [{section_def, values}], update: [{section_id, values}], delete: [section_id]}` |
| 응답 | 200 문서(버전 +1) |
| 오류 | 400 `NO_CHANGES`(바꿀 것 없음) · 400 `VALIDATION_ERROR`(칸 값) · 400 `SYSTEM_SECTION`(시스템이 채우는 영역) · 404 `DOCUMENT_NOT_FOUND` · 409 `DOCUMENT_LOCKED`(수정할 수 없는 상태) · 409 `VERSION_CONFLICT` · 409 `SECTION_ROW_NOT_FOUND` · 409 `DUPLICATE_ROUND`(같은 측정시점) · 403 `ROLE_REQUIRED` |
| 알아둘 점 | CCP 판정·총 건조시간·D03 시험성적서 유무 같은 계산 칸은 서버가 다시 계산해 덮어씁니다. |

<a id="doc-a08"></a>
#### DOC-A08 · DELETE `/documents/{document_id}` — 문서 삭제

| | |
|---|---|
| 사용자 | 필수 |
| 응답 | 204 (논리 삭제) |
| 오류 | 404 `DOCUMENT_NOT_FOUND` · 409 `DOCUMENT_NOT_DELETABLE` — `details[].reason`: `requirement`(입고·생산이 만든 문서) / `status`(작성중이 아님) / `submitted`(상신 이력 있음) |
| 알아둘 점 | 지울 수 있는 것은 상신한 적 없는 작성중 문서뿐입니다. 주기 점검표는 지워도 규칙상 만드는 날이면 다시 만들어지므로, 쓸 일 없는 날은 `DOC-A24`(작성 안 함)를 씁니다. |

<a id="doc-a09"></a>
#### DOC-A09 · POST `/documents/{document_id}/complete` — 작성완료

| | |
|---|---|
| 사용자 | 필수 · 작성 권한 |
| 본문 | `expected_version`(필수) · `note`(선택 — D03 판정을 바꿔 다시 작성완료할 때 판정 변경 사유, 200자) |
| 응답 | 200 문서(`completed`) |
| 오류 | 400 `COMPLETION_INCOMPLETE`(빠진 필수 칸, 부적합인데 개선조치 없음 — `details`에 항목) · 404 · 409 `INVALID_TRANSITION`(작성중·반려·정정 중이 아님, 작성 안 함 문서) · 409 `VERSION_CONFLICT` · 409 `INVENTORY_REJECTED`(D03 판정을 수불이 받지 않음 — 작성완료 전체 취소) · 409 `PLG_LINKED_UNAVAILABLE`(생산일지 연동 실패) |
| 부수 효과 | D03은 판정을 수불에 전달 · 생산일지는 기본정보·원료칭량을 고정 · CCP 외 양식의 개선조치가 확인 대기에 나타나기 시작 |

<a id="doc-a10"></a>
#### DOC-A10 · POST `/documents/{document_id}/reopen` — 작성 재개

| | |
|---|---|
| 사용자 | 필수 · 작성 권한 |
| 본문 | `expected_version`(필수)만 |
| 응답 | 200 문서(`draft`) |
| 오류 | 404 · 409 `INVALID_TRANSITION`(작성완료가 아님 — 결재중이면 먼저 상신 취소) · 409 `VERSION_CONFLICT` |

<a id="doc-a24"></a>
#### DOC-A24 · POST `/documents/batch-skip` — 작성 안 함(여러 건)

| | |
|---|---|
| 사용자 | 필수 |
| 본문 | `items: [{document_id, expected_version}]`(1~50건) · `reason`(필수, 1~200자, 공백만 불가) |
| 응답 | 200 일괄 결과 `{action, total, succeeded, failed, results: [{ok, ...}]}` — 일부 실패해도 200 |
| 건별 실패 | `DOCUMENT_NOT_SKIPPABLE`(주기 작성 요구 문서의 작성중만 가능) · `VERSION_CONFLICT` 등 |

<a id="doc-a25"></a>
#### DOC-A25 · POST `/documents/{document_id}/unskip` — 작성 안 함 되돌리기

| | |
|---|---|
| 사용자 | 필수 |
| 본문 | `expected_version`(필수)만 |
| 응답 | 200 문서(`draft`, 써 둔 값 그대로) |
| 오류 | 404 · 409 `INVALID_TRANSITION` · 409 `VERSION_CONFLICT` |

<a id="doc-a18"></a>
#### DOC-A18 · POST `/documents/{document_id}/correction` — 정정 시작

| | |
|---|---|
| 사용자 | 필수 · 그 양식 담당자 또는 HACCP팀장(작성 권한자는 안 됨) |
| 본문 | `expected_version`(필수) · `reason`(필수, 200자 이하) |
| 판정 순서 | 형식 → 사용자 → 사유 → 404 → 409 |
| 응답 | 200 문서(`correcting`) |
| 오류 | 400 `VALIDATION_ERROR`(사유) · 403 `ROLE_REQUIRED` · 404 · 409 `INVALID_TRANSITION`(승인이 아님) · 409 `VERSION_CONFLICT` |
| 알아둘 점 | 새 승인이 끝나기 전까지는 이전 승인본이 유효합니다. 출력도 이전 승인본 값으로 나옵니다. |

<a id="doc-a19"></a>
#### DOC-A19 · POST `/documents/{document_id}/correction/cancel` — 정정 취소

| | |
|---|---|
| 사용자 | 필수 |
| 본문 | `expected_version`(필수)만 |
| 응답 | 200 문서(`approved`로 돌아감) |
| 오류 | 409 `CORRECTION_HAS_CHANGES`(정정 시작 뒤 고친 내용이 있음 — 작성완료 후 재상신) · 409 `INVALID_TRANSITION` · 409 `VERSION_CONFLICT` |

<a id="doc-a20"></a>
#### DOC-A20 · POST `/documents/batch-inspector` — 점검자 일괄 지정

| | |
|---|---|
| 사용자 | 필수 · 그 양식 담당자 또는 HACCP팀장 |
| 본문 | `items: [{document_id, expected_version}]`(1~50건) · `inspector_id`(필수) |
| 응답 | 200 일괄 결과. 같은 값이면 그 건은 "변화 없음" |
| 화면 | 입고일 묶음·주 묶음 **[점검자 지정]** |

<a id="doc-a21"></a>
#### DOC-A21 · GET `/documents/brief` — 문서 요약 여러 건

| | |
|---|---|
| 사용자 | 필요 없음 |
| 쿼리 | `ids` — 쉼표로 구분한 문서 번호 1~50개 (`?ids=58,67,73`) |
| 응답 | 200 문서마다 상태·버전 등 짧은 요약 |
| 오류 | 400 `INVALID_FILTER`(없음·형식·50개 초과) |

<a id="doc-a26"></a>
#### DOC-A26 · GET `/documents/recent-values` — 최근 입력 값

| | |
|---|---|
| 사용자 | 필요 없음 |
| 쿼리 | `type_code`·`field`(필수) · `section`(선택). 다른 키는 거부 |
| 응답 | 200 최근 값 목록 |
| 화면 | D12 공정명의 "최근: …" 제안 |

### 3. 이탈·개선조치

개선조치는 문서 상태와 상관없이 언제든 쓰고 고칠 수 있으며, 문서 버전·결재 상태를 바꾸지 않습니다([기능 안내 4장](../guide/document-guide.md#4-ccp개선조치)).

<a id="doc-a15"></a>
#### DOC-A15 · POST `/documents/{document_id}/deviations` — 개선조치 쓰기

| | |
|---|---|
| 사용자 | 필수 · 그 문서의 작성 권한 |
| 본문 | `description`(이탈내용, 필수) · `action_result`(개선조치 및 결과) · `actor_id`(조치자) · `section_id`(관련 행) |
| 응답 | 201 개선조치 + 자동 지정된 확인자. 확인자를 못 정하면 `checker_warning` |
| 오류 | 400 `VALIDATION_ERROR` · 404 `DOCUMENT_NOT_FOUND` · 403 `ROLE_REQUIRED` |
| 기능 | `F-CCP-02` [이탈·개선조치 적기](../guide/document-guide.md#41-이탈개선조치-적기) |

<a id="doc-a16"></a>
#### DOC-A16 · PATCH `/deviations/{deviation_id}` — 개선조치 수정

| | |
|---|---|
| 사용자 | 필수 · 작성 권한 또는 그 줄의 확인자 |
| 본문 | `expected_version`(필수) + 바꿀 칸(`description`·`action_result`·`actor_id`·`section_id`) |
| 응답 | 200 개선조치 |
| 오류 | 404 `DEVIATION_NOT_FOUND` · 409 `VERSION_CONFLICT` · 403 |
| 알아둘 점 | 확인된 뒤 고쳐도 확인 기록은 남습니다. |

<a id="doc-a17"></a>
#### DOC-A17 · DELETE `/deviations/{deviation_id}` — 개선조치 삭제

| | |
|---|---|
| 사용자 | 필수 · 작성 권한 |
| 쿼리 | `expected_version`(필수) |
| 응답 | 204 |
| 오류 | 400(`expected_version` 없음) · 404 `DEVIATION_NOT_FOUND` · 409 `VERSION_CONFLICT` |

<a id="doc-a22"></a>
#### DOC-A22 · GET `/deviations/pending` — 확인 대기 목록

| | |
|---|---|
| 사용자 | 선택 — `mine=1`일 때는 그 사람 기준 |
| 쿼리 | `date`(YYYY-MM-DD) · `mine`(`0`/`1`, 내 확인 대기만) · `summary`(`0`/`1`, 숫자만 — 사이드바 배지) |
| 응답 | 200 확인 대기 개선조치 목록 또는 개수 |
| 화면 | CCP 대시보드 "② 개선조치 확인 대기" · 사이드바 숫자 |

<a id="doc-a23"></a>
#### DOC-A23 · POST `/deviations/{deviation_id}/check` — 개선조치 확인

| | |
|---|---|
| 사용자 | 필수 · 그 줄의 확인자 또는 HACCP팀장 |
| 본문 | `expected_version`(필수, 개선조치 버전) |
| 응답 | 200 개선조치(확인자·확인 시각) |
| 오류 | 403 `NOT_CHECKER` · 409 `ALREADY_CHECKED`(누가·언제 확인했는지 함께) · 409 `VERSION_CONFLICT`(그사이 내용이 바뀜) · 404 `DEVIATION_NOT_FOUND`(삭제됨) |
| 기능 | `F-CCP-03` [개선조치 확인하기](../guide/document-guide.md#42-개선조치-확인하기) · 되돌릴 수 없음 |

### 4. 증빙 파일

파일을 붙이는 양식은 D01·D02뿐입니다(다른 양식은 409 `FILES_NOT_ALLOWED`). 형식 PDF·JPG·PNG, 파일당 20MB 이하.

<a id="doc-a11"></a>
#### DOC-A11 · POST `/documents/{document_id}/files` — 파일 올리기 / 기존 파일 연결

| | |
|---|---|
| 사용자 | 필수 · 작성 권한 |
| 본문 — 올리기 | `multipart/form-data`: `file`(한 요청에 1개) · `expected_version` |
| 본문 — 연결 | JSON `{expected_version, link_file_id}` — `DOC-A14`로 찾은 같은 양식의 파일 |
| 응답 | 201 파일 정보 + 문서 버전 |
| 오류 | 400 `FILE_REJECTED`(형식·크기·내용이 확장자와 다름) · 409 `FILES_NOT_ALLOWED` · 409 `DOCUMENT_LOCKED` · 409 `FILE_ALREADY_LINKED` · 409 `FILE_TEMPLATE_MISMATCH` · 404 `FILE_NOT_FOUND` · 409 `VERSION_CONFLICT` |

<a id="doc-a12"></a>
#### DOC-A12 · DELETE `/documents/{document_id}/files/{file_id}` — 파일 연결 끊기

| | |
|---|---|
| 사용자 | 필수 · 작성 권한 |
| 쿼리 | `expected_version`(필수) |
| 응답 | 200. 다른 문서도 쓰는 파일이거나 상신된 적 있는 파일이면 파일은 남음 |
| 오류 | 409 `FILE_NOT_LINKED` · 409 `DOCUMENT_LOCKED` · 409 `VERSION_CONFLICT` |

<a id="doc-a14"></a>
#### DOC-A14 · GET `/files` — 이전 파일 검색

| | |
|---|---|
| 사용자 | 필요 없음 |
| 쿼리 | `type_code` · `item`(품명) · `supplier`(매입처) · `days`(1~365, 기본 90) · `page`. 다른 키는 거부 |
| 응답 | 200 파일 목록(쪽당 20) |
| 화면 | D01·D02 **[이전 파일 불러오기]** |

<a id="doc-a13"></a>
#### DOC-A13 · GET `/files/{file_id}` — 파일 보기

| | |
|---|---|
| 사용자 | 필요 없음 |
| 응답 | 200 파일 내용(inline, `Cache-Control: private, no-store`). 같은 출처의 iframe에서만 열림(PDF 미리 보기용) |
| 오류 | 404 `FILE_NOT_FOUND` |


### 5. 결재

결재선은 본문으로 받지 않고 문서 권한의 결재 칸 구성으로 서버가 만듭니다. 칸마다 후보 중 1명이 처리하면 되고 칸 사이 순서는 없습니다. 모든 칸이 승인하면 문서가 `approved`, 한 칸이라도 반려하면 `rejected`가 됩니다.

<a id="wf-a01"></a>
#### WF-A01 · POST `/documents/{document_id}/submit` — 상신·재상신

작성완료된 문서를 결재에 올립니다. 결재선은 받지 않고 문서 권한의 결재 칸 구성으로 서버가 만듭니다. 반려된 문서를 다시 올릴 때도 같은 API입니다.

| | |
|---|---|
| **기능** | `F-WF-01` [문서를 결재 올리기](../guide/document-guide.md#31-문서를-결재-올리기) |
| **화면** | 문서함 → 문서 상세 결재 영역 **[결재 상신]** → 확인 창 **[상신]** (`frontend/static/temp-entry/approval/approval.js`) |
| **구현** | `document_workflow/api.py::submit` → `document_workflow/services.py::submit` (권한·결재선 → 트랜잭션[문서 잠금 → 스냅샷 → 회차 생성]) |
| **테스트** | `document_workflow/tests/test_api.py::SubmitApiTests`(응답·요청·오류) · `test_p14_roles.py`(역할·결재선) |
| **결정** | D-055(작성완료에서만 상신) · D-058(상신된 문서의 파일 보존) · D-182, D-198(문서 권한 결재선) |

##### 요청

| 위치 | 이름 | 형 | 필수 | 설명 |
|---|---|---|---|---|
| 헤더 | `X-Staff-Id` | 정수 | ✓ | 올리는 사람 |
| 헤더 | `Content-Type` | — | ✓ | `application/json` |
| 경로 | `document_id` | 정수 | ✓ | 문서 번호 |
| 본문 | `expected_version` | 정수 ≥ 1 | ✓ | 화면이 본 문서 버전. 다른 키는 받지 않음 |

```json
{"expected_version": 4}
```

##### 응답

`201 Created`

```json
{
  "document": {
    "document_id": 7, "template_id": 3, "status": "submitted",
    "submitted_at": "2026-10-28T09:00:00+09:00", "version": 5
  },
  "request": {
    "request_id": 12, "document_id": 7, "attempt": 1,
    "status": "in_progress", "document_version": 5,
    "template_id": 3, "subject": "입고 검사", "work_date": "2026-10-28",
    "requested_by": 2, "requested_at": "2026-10-28T09:00:00+09:00",
    "closed_at": null,
    "slots": [{
      "approval_id": 21, "slot_no": 1, "label": "HACCP팀장",
      "role": "leader", "candidate_ids": [4], "approver_id": null,
      "state": "pending", "comment": null, "decided_at": null
    }],
    "can_cancel": false, "effective": false, "superseded_by": null,
    "superseded_at": null, "is_correction": false, "correction_reason": null
  }
}
```

`document`는 잠금 결과, `request`는 새 결재 회차입니다. `slots`는 설정된 결재 칸 수만큼 들어가며, 응답에는 문서 스냅샷이 포함되지 않습니다. 일괄 상신의 축약 응답(`_submit_result`)과 다릅니다.

##### 오류 (판정 순서)

| 상태 | `code` | 언제 | 화면 문구 |
|---|---|---|---|
| 400 | `INVALID_REQUEST` | 본문이 JSON 객체가 아님 · 모르는 키 · `expected_version` 없음/정수 아님/1 미만 | "expected_version은 1 이상의 정수여야 합니다." 등 |
| 400 | `STAFF_HEADER_MISSING` | `X-Staff-Id` 없음 | — |
| 403 | `INVALID_STAFF` | 숫자가 아니거나 비활성 직원 | — |
| 404 | `DOCUMENT_NOT_FOUND` | 문서가 없거나 삭제됨 | — |
| 409 | `NO_APPROVAL_FORM` | 결재 없는 양식(생산일지 등) | "결재 없는 양식은 상신할 수 없습니다." |
| 403 | `ROLE_REQUIRED` | 그 양식의 담당자·작성 권한자·HACCP팀장이 아님 | "이 양식의 담당자·작성 권한자나 HACCP팀장만 상신할 수 있습니다." |
| 409 | `NO_APPROVAL_LINE` | 처리할 사람이 0명인 결재 칸이 있음 | "결재 칸을 처리할 사람이 없습니다(역할 보유자 0명)." |
| 409 | `DOCUMENT_LOCKED` | 작성완료·재상신 가능 상태가 아님 | — |
| 409 | `VERSION_CONFLICT` | `expected_version`이 현재 버전과 다름 | "다른 사용자가 먼저 수정했습니다. 최신 내용을 다시 불러오세요." |

본문과 사용자 헤더를 확인한 뒤 `services.py::_line_for`에서 문서 존재·결재 양식·문서 권한·결재선을 순서대로 판정합니다. 마지막으로 `documents/services.py::_lock_failure`가 상태·버전을 판정합니다.

##### 부수 효과

- 문서 `completed → submitted`, 버전 +1. 이후 수정 불가.
- 올린 순간의 문서 내용과 개선조치를 결재 요청에 저장(스냅샷). 결재자는 이 내용을 봅니다.
- 결재 회차와 결재 칸 생성 — 칸마다 후보 = 그 순간 역할 보유자 전원. 결재자의 결재함(`APR-A01`)에 나타남.
- 연결된 증빙 파일에 보존 표시(이후 연결을 끊어도 파일은 지우지 않음).
- D03은 시험성적서 유무를 이때 다시 계산해 확정.

##### 알아둘 점

- 결재선을 본문으로 받지 않습니다(P14). 재상신도 그때의 문서 권한으로 새로 만듭니다.
- 여러 건은 `WF-A04`(일괄 상신)를 씁니다.
- **[테스트 버전]** `X-Staff-Id`는 화면의 "현재 사용자" 선택이며 인증이 아닙니다.

<a id="wf-a02"></a>
#### WF-A02 · POST `/approvals/{approval_id}/decision` — 승인·반려

| | |
|---|---|
| 사용자 | 필수 · 그 결재 칸의 후보 |
| 본문 | `result`(필수, `approved` / `rejected`) · `comment`(500자 이하, **반려면 필수**) |
| 응답 | 200 결재 칸·회차 결과. 회차가 끝나면 문서 상태도 바뀜 |
| 오류 | 400 `INVALID_DECISION` · 400 `COMMENT_REQUIRED` · 403 `NOT_YOUR_SLOT` · 404 `APPROVAL_NOT_FOUND` · 409 `ALREADY_DECIDED` · 409 `REQUEST_CLOSED` |
| 기능 | `F-WF-02` · 결재함 |

<a id="wf-a03"></a>
#### WF-A03 · POST `/approvals/batch-decision` — 일괄 승인

| | |
|---|---|
| 사용자 | 필수 |
| 본문 | `approval_ids`(필수, 1~50개) · `comment`(선택). **반려는 받지 않음**(한 건씩 `WF-A02`) |
| 응답 | 200 일괄 결과(건별 성공·실패) |
| 기능 | `F-WF-06` · 입고일 묶음·주 묶음·결재함 **[선택 승인]** |

<a id="wf-a04"></a>
#### WF-A04 · POST `/documents/batch-submit` — 일괄 상신

| | |
|---|---|
| 사용자 | 필수 |
| 본문 | `items: [{document_id, expected_version}]`(필수, 1~50건). 결재선은 문서마다 설정으로 |
| 응답 | 200 일괄 결과. 건별 실패 사유는 `WF-A01`의 오류와 같음 |
| 기능 | `F-WF-06` · **[선택 상신]** |

<a id="wf-a05"></a>
#### WF-A05 · GET `/workflow/batch-config` — 일괄 처리 설정

| | |
|---|---|
| 사용자 | 필요 없음 |
| 응답 | 200 `{batch_types, template_ids, max_items: 50, inspector_types}` — 일괄 처리 대상 양식(`HACCP_BATCH_TYPES`, 기본 `D03,D10,D11,D12`)과 점검자 지정 양식 |

<a id="wf-f05"></a>
#### WF-F05 · POST `/approval-requests/{request_id}/cancel` — 상신 취소

| | |
|---|---|
| 사용자 | 필수 · 상신한 사람 또는 HACCP팀장 |
| 본문 | 없음(보내면 빈 객체 `{}`만 허용, 사유 받지 않음) |
| 응답 | 200 회차(취소) · 문서는 `completed`로 돌아감 |
| 오류 | 403 `NOT_REQUESTER` · 404 `REQUEST_NOT_FOUND` · 409 `REQUEST_CLOSED`(이미 끝난 회차) |
| 기능 | `F-WF-04` |

<a id="apr-a01"></a>
#### APR-A01 · GET `/approval-inbox` — 결재함

| | |
|---|---|
| 사용자 | **필수** |
| 쿼리 | `box` = `pending`(기본, 내가 처리할 칸) / `done`(처리한 칸) · `from`·`to`(366일 이내) · `template_id` · `page`(쪽당 20) |
| 응답 | 200 목록 |
| 오류 | 400 `INVALID_FILTER` |

<a id="apr-a02"></a>
#### APR-A02 · GET `/approval-requests/{request_id}` — 결재 요청 상세

| | |
|---|---|
| 사용자 | 선택 — 보내면 `can_cancel`(내가 상신 취소할 수 있는지) |
| 응답 | 200 회차·결재 칸·**상신 당시 문서와 개선조치 스냅샷**·증빙 파일 |
| 오류 | 404 `REQUEST_NOT_FOUND` |

<a id="apr-a03"></a>
#### APR-A03 · GET `/documents/{document_id}/approval-requests` — 문서의 결재 회차

| | |
|---|---|
| 사용자 | 선택 — 보내면 `can_cancel` |
| 응답 | 200 그 문서의 회차 목록(1회차, 2회차 …) |

### 6. 작성 요구·묶음·대시보드

입고·생산이 문서를 만드는 일 자체는 API가 아니라 수불 쪽에서 함수로 부릅니다([문서 → 수불 인터페이스](../../reference/document-inventory-interface.md)). 여기 있는 것은 조회와 주기 문서 만들기입니다.

<a id="req-a01"></a>
#### REQ-A01 · GET `/lots/{lot_id}/documents` — LOT별 연결 문서

| | |
|---|---|
| 사용자 | 필요 없음 |
| 응답 | 200 그 LOT의 D01·D02·D03과 상태, **최신 승인본 기준 판정** |
| 오류 | 404 `LOT_NOT_FOUND` · 409 `LOT_NOT_INCOMING` · 503 `REQ_SOURCE_MISSING`(수불 뷰 없음) |

<a id="req-a02"></a>
#### REQ-A02 · GET `/batches/{batch_id}/documents` — 배치별 연결 문서

| | |
|---|---|
| 사용자 | 필요 없음 |
| 응답 | 200 그 배치의 CCP 일지(상태·최근 측정·이탈 수)와 생산일지 |
| 오류 | 404 `BATCH_NOT_FOUND` · 503 `REQ_SOURCE_MISSING` |
| 화면 | 생산 화면 배치 **[연결 문서]** 탭 |

<a id="req-a03"></a>
#### REQ-A03 · GET `/incoming-inspections` — 입고일 묶음

| | |
|---|---|
| 사용자 | 선택 — 보내면 그 사람 기준 가능 동작 |
| 쿼리 | `received_date`(필수, YYYY-MM-DD) |
| 응답 | 200 그날 들어온 LOT의 D03 한 표(판정·상태·결재·점검자) |
| 오류 | 400 `VALIDATION_ERROR`(날짜 형식) |

<a id="req-a04"></a>
#### REQ-A04 · GET `/periodic-bundles` — 주 묶음

| | |
|---|---|
| 사용자 | 선택 |
| 쿼리 | `type_code`(D10·D12) · `week_start`(필수, 그 주 월요일 YYYY-MM-DD) |
| 응답 | 200 월~금 줄(상태·점검자·점검 결과 수·판정·결재) + 주말 문서 링크 |
| 오류 | 400 `VALIDATION_ERROR` · 400 `NOT_PERIODIC` |

<a id="req-a05"></a>
#### REQ-A05 · POST `/periodic-runs` — 기간의 주기 문서 만들기

| | |
|---|---|
| 사용자 | 필수 |
| 본문 | `date_from`·`date_to`(필수, 양 끝 포함 31일까지, 오늘 이후 불가) · `type_codes`(선택, 없으면 전부) |
| 응답 | 200 날짜·양식마다 `created`(새로 만듦) / 이미 있음 / 대상 아님 / `failed`. 실패 줄이 있어도 200 |
| 오류 | 400 `VALIDATION_ERROR`(기간) · 500 `RULES_INVALID`(주기 규칙 파일) — 이때는 아무것도 만들지 않음 |
| 알아둘 점 | 날마다 예약 실행하는 관리 명령 `make_periodic_documents`와 같은 일을 합니다. |

<a id="req-a06"></a>
#### REQ-A06 · POST `/periodic-documents` — 그날 주기 문서 찾거나 만들기

| | |
|---|---|
| 사용자 | 필수 |
| 본문 | `type_code`(D10·D11·D12) · `date`(YYYY-MM-DD — 미래·주말도 됨) |
| 응답 | 200 문서(있으면 그것, 없으면 새로 만들어서) |
| 오류 | 400 `NOT_PERIODIC` · 400 `VALIDATION_ERROR` |
| 화면 | 문서함 **[+ 새 문서] › 주기 양식** |

<a id="req-a07"></a>
#### REQ-A07 · GET `/periodic-rules` — 주기 규칙

| | |
|---|---|
| 사용자 | 필요 없음 |
| 응답 | 200 양식별 주기(daily·weekly)·요일·시작일·켜짐 여부 (`periodic_rules.json` 또는 `HACCP_PERIODIC_RULES`) |

<a id="req-a08"></a>
#### REQ-A08 · GET `/todo` — 작성 필요 목록

| | |
|---|---|
| 사용자 | **필수** |
| 쿼리 | `date`(없으면 오늘) · `mine`(`1`이면 내가 쓸 것만) |
| 응답 | 200 그날 작성해야 할 문서 목록 |
| 화면 | 문서함 **작성 필요** 탭 |

<a id="req-a09"></a>
#### REQ-A09 · GET `/ccp-dashboard` — CCP 현황

| | |
|---|---|
| 사용자 | 선택 — 보내면 [확인]·[개선조치 쓰기] 가능 여부 |
| 쿼리 | `date`(기준일, 없으면 오늘) |
| 응답 | 200 그날 배치별 CCP 일지·이탈·개선조치 확인 대기·생산일지 진행 |
| 기능 | `F-CCP-01` · **CCP 대시보드** |

### 7. 출력

<a id="wf-a06"></a>
#### WF-A06 · GET `/print/sheet` — 종이 한 장 데이터

| | |
|---|---|
| 사용자 | 필요 없음(보내도 쓰지 않음) |
| 쿼리 — 문서로 | `document_id` (+ `kind=single` 선택). 묶음 종이 양식이면 그 문서가 속한 입고일·주·달 종이가 나옴 |
| 쿼리 — 묶음으로 | `type` + `kind` + 날짜. `kind`는 양식마다 정해져 있음: D03 `receiving`(`date` = 입고일) · D10·D12 `weekly`(`date`) · D11 `monthly`(`month` = YYYY-MM). 미래 날짜·달은 안 됨 |
| 응답 | 200 종이 한 장 그리기에 필요한 값(머리·결재 칸·줄). 화면이 인쇄 페이지로 그림 |
| 오류 | 400 `INVALID_FILTER`(키·조합·날짜) · 400 `NOT_PRINTABLE_TYPE`(D01·D02 등) · 409 `NOT_PRINTABLE_STATUS`(작성중·반려) · 404 `DOCUMENT_NOT_FOUND` |
| 알아둘 점 | 출력 양식: CCP-1P·2B·3P `single` · D03 `receiving` · D10·D12 `weekly` · D11 `monthly` · 생산일지 `prodlog`(문서로만). 출력 기록은 남지 않음 |

### 8. 생산일지·생산 기준정보

생산 기준정보(공정·템플릿)는 **누구나** 쓸 수 있고(사용자 헤더는 필수), 모든 변경이 이력으로 남습니다. 수정·삭제·사용 중지는 `expected_version`이 필요합니다(삭제는 쿼리로). 생산일지 쓰기는 `PROD-LOG` 담당자·HACCP팀장만 합니다.

<a id="plg-a01"></a>
#### PLG-A01 · GET `/production-logs/{document_id}/linked` — 연동 값 조회

| | |
|---|---|
| 사용자 | 필요 없음 |
| 응답 | 200 `{linked, frozen, changed, error, last_template, ccp_documents}` — 수불에서 읽은 기본정보·원료칭량, 작성완료 때 고정한 값, 바뀐 곳, 같은 품목 최근 템플릿, CCP 일지 번호 |
| 연동 실패 | 200 그대로 `linked: null, error: "SOURCE_UNAVAILABLE"` (화면이 안내를 띄움) |
| 오류 | 404 `PLG_NOT_PRODUCTION_LOG` |

<a id="plg-a02"></a>
#### PLG-A02 · POST `/production-logs/{document_id}/template-rows` — 템플릿 줄 가져오기

| | |
|---|---|
| 사용자 | 필수 · 생산일지 작성 권한 |
| 본문 | `template_id`(필수) · `mode`(`replace` 바꾸기 / `append` 덧붙이기) |
| 응답 | 200 넣을 공정 줄. **일지에는 쓰지 않음** — 화면이 넣고 **[저장]** 할 때 `DOC-A07`로 씀. 템플릿 사용 기록만 남김 |
| 오류 | 404 `PLG_TEMPLATE_NOT_FOUND` · 409 `PLG_BATCH_CANCELLED` · 400 `VALIDATION_ERROR` |

<a id="plg-a03"></a>
#### PLG-A03 · POST `/production-logs/{document_id}/save-template` — 일지 공정을 템플릿으로 저장

| | |
|---|---|
| 사용자 | 필수 · 생산일지 작성 권한 |
| 본문 | `name`·`steps`(필수) · `overwrite`(같은 이름 덮어쓰기) · `expected_version`(덮어쓸 때 — `PLG_NAME_TAKEN` 응답에서 받은 버전) · `confirm_similar` |
| 응답 | 201 템플릿. 일지 한정 공정(목록에 없는 직접 입력)은 빠짐 |
| 오류 | 409 `PLG_NAME_TAKEN` · 409 `PLG_SIMILAR_NAME`(→ `confirm_similar: true`로 다시) · 409 `VERSION_CONFLICT` · 400 `PLG_TEMPLATE_INVALID` |

<a id="plg-a04"></a>
#### PLG-A04 · GET `/production-logs/{document_id}/ccp-values` — CCP 값

| | |
|---|---|
| 사용자 | 필요 없음 |
| 쿼리 | `kind` = `CCP-1P` / `CCP-2B` / `CCP-3P` |
| 응답 | 200 그 배치 CCP 일지의 상태와 결과 값(1P·3P 판정, 2B 온도·시간) |
| 오류 | 400 `VALIDATION_ERROR`(kind) · 404 `PLG_CCP_DOC_MISSING` |
| 화면 | 공정 카드 **[CCP 일지 값 가져오기]** |

<a id="plg-a05"></a>
#### PLG-A05 · POST `/production-logs/{document_id}/register-process` — 일지에서 공정 등록

| | |
|---|---|
| 사용자 | 필수 · 생산일지 작성 권한 |
| 본문 | `name`(필수) · `mode`(입력 방식) · `confirm_similar` |
| 응답 | 같은 이름의 사용 중 공정이 있으면 **200** `{process, linked_existing: true}`(연결), 없으면 **201** 새 공정 |
| 오류 | 409 `PLG_SIMILAR_NAME` · 400 `VALIDATION_ERROR` |

<a id="plg-a06"></a>
#### PLG-A06 · GET·POST `/processes` — 공정 목록·추가

| | |
|---|---|
| 사용자 | GET 필요 없음 · POST 필수 |
| 쿼리(GET) | `q`(이름) · `kind`(기본 `all`) · `status`(기본 `active`) |
| 본문(POST) | `name`(필수) · `mode`(입력 방식: `JUDGE` 판정 / `TEMP_TIME` 온도·시간 / `QTY` 수량) · `description` · `std_duration` · `confirm_similar` |
| 응답 | GET 200 목록 · POST 201 공정(일반 공정만 추가 가능) |
| 오류 | 409 `PLG_NAME_TAKEN` · 409 `PLG_SIMILAR_NAME` · 400 `VALIDATION_ERROR` |

<a id="plg-a06-item"></a>
#### — · GET·PATCH·DELETE `/processes/{process_id}` — 공정 한 개

| | |
|---|---|
| 사용자 | GET 필요 없음 · PATCH·DELETE 필수 |
| PATCH 본문 | `expected_version`(필수) + 바꿀 값. 기본 제공 공정은 표시명·설명·소요기간만 |
| DELETE | 쿼리 `expected_version` · 응답 204 · 한 번도 안 쓴 일반 공정만 |
| 오류 | 404 `PLG_PROCESS_NOT_FOUND` · 409 `PLG_BUILTIN_LOCKED` · 409 `PLG_CONFIRM_REQUIRED`(입력 방식을 바꾸면 템플릿에도 반영 — 확인 후 다시) · 409 `PLG_IN_USE`(삭제 대신 사용 중지) · 409 `VERSION_CONFLICT` |
| 알아둘 점 | 템플릿에 쓰인 공정을 고치면 덮어쓰지 않은 템플릿에 반영됩니다(이미 만든 일지는 그대로). |

<a id="plg-a06-active"></a>
#### — · POST `/processes/{process_id}/active` — 공정 사용 중지·다시 사용

| | |
|---|---|
| 사용자 | 필수 |
| 본문 | `active`(true/false) · `expected_version`(필수) |
| 응답 | 200 공정 |

<a id="plg-a07"></a>
#### PLG-A07 · GET·POST `/process-templates` — 공정 템플릿 목록·추가

| | |
|---|---|
| 사용자 | GET 필요 없음 · POST 필수 |
| 쿼리(GET) | `q` · `status`(기본 `active`) |
| 본문(POST) | `name`·`steps`(필수, 같은 공정 두 번 불가, 최대 30단계) · `confirm_similar`. 단계마다 덮어쓸 값(표시명·설명·소요기간, 일반 공정 입력 방식, 내포장 규격·수량 단위, 외포장 포장재질) |
| 응답 | GET 200 목록 · POST 201 템플릿 |
| 오류 | 400 `PLG_TEMPLATE_INVALID` · 409 `PLG_NAME_TAKEN` · 409 `PLG_SIMILAR_NAME` |

<a id="plg-a07-item"></a>
#### — · GET·PATCH·DELETE `/process-templates/{template_id}` — 템플릿 한 개

| | |
|---|---|
| 사용자 | GET 필요 없음 · PATCH·DELETE 필수 |
| PATCH 본문 | `expected_version`(필수) + 바꿀 값(`name`·`steps`) |
| DELETE | 쿼리 `expected_version` · 응답 204 · 한 번도 안 불러온 템플릿만 |
| 오류 | 404 `PLG_TEMPLATE_NOT_FOUND` · 409 `PLG_IN_USE` · 409 `VERSION_CONFLICT` · 400 `PLG_TEMPLATE_INVALID` |

<a id="plg-a07-copy"></a>
#### — · POST `/process-templates/{template_id}/copy` — 템플릿 복제

| | |
|---|---|
| 사용자 | 필수 |
| 본문 | 없음 |
| 응답 | 201 새 템플릿 |

<a id="plg-a07-active"></a>
#### — · POST `/process-templates/{template_id}/active` — 템플릿 사용 중지·다시 사용

| | |
|---|---|
| 사용자 | 필수 |
| 본문 | `active` · `expected_version`(필수) |
| 응답 | 200 템플릿 |

<a id="plg-a08"></a>
#### PLG-A08 · GET `/master-history` — 변경 이력

| | |
|---|---|
| 사용자 | 필요 없음 |
| 쿼리 | `target` = `process` / `template` · `id` |
| 응답 | 200 누가·언제·전→후·관련 생산일지 문서 번호 |

### 9. 관리 설정(ADM)

P16에서 생긴 `backend/apps/admin_settings` 앱의 API입니다. 경로는 모두 `/api/v1/admin/…`이고, `doc_entry_enabled`와 관계없이 늘 등록됩니다. 화면은 [문서·결재 기능 안내 11장](../guide/document-guide.md#11-관리-설정직원문서-권한품목별-ccp)을 봅니다.

| 항목 | 규칙 |
|---|---|
| 현재 사용자 | 읽기(GET)는 헤더 없이 됨. 쓰기는 `X-Staff-Id` 필수 — **권한 검사는 없고**(누구나) 이력의 "누가"로만 씀. 예외: 활성 직원 0명일 때 `ADM-A05`(등록)·`ADM-A08`(다시 활성)은 헤더 없이 됨(처음 설정 — 아래) |
| CSRF | 문서 쪽 API와 달리 **Django CSRF 검사를 그대로 함**. 쓰기 요청은 `csrftoken` 쿠키(첫 화면 `home`이 발급) 값을 `X-CSRFToken` 헤더에 실어 보냄. 없거나 맞지 않으면 Django 403(JSON 아님) — 화면 문구 "보안 토큰이 만료됐습니다 — 새로고침 후 다시 시도하세요" |
| 입력 오류 | 400 `VALIDATION_ERROR` 하나로, 이유는 `details[].code`(`path`·`code`·`message`). 본문이 JSON 객체가 아니면 기존 400 `INVALID_REQUEST` |
| 버전 확인 | 품목 CCP는 품목 설정 행의 `version`(행 없음 = 0), 문서 권한은 전체 `version` 하나. 다르면 409 `VERSION_CONFLICT`("다른 사람이 먼저 저장했습니다. 새로고침한 뒤 다시 저장하세요.") |
| 같은 값 저장 | 저장·버전·이력 없이 200(`changed: false` 또는 `changes: []`) |
| 트랜잭션 | 쓰기 = 한 트랜잭션(본문 검사 → 대상 읽기 → 조건부 저장 → 이력 `admin_change_log`) |
| 처음 설정 | 헤더가 없거나 활성이 아닌 직원이면 서버가 **같은 트랜잭션에서 활성 직원 0명인지 다시 확인**. 0명이면 허용(이력 `bootstrap_create`·`bootstrap_activate`, 누가 = 그 직원), 아니면 400 `details[].code = setup_finished` |
| 직원 쓰기 | 수불 `staff` 표는 수불 쪽 `backend/apps/inventory/staff_admin.py`(스스로 커밋 안 함)를 거쳐서만 씀 |

`details[].code` 값: `invalid` · `required` · `unknown_key` · `too_long` · `invalid_process` · `not_producible` · `duplicate_code` · `confirm_required` · `last_active_staff` · `setup_finished` · `duplicate` · `unknown_staff` · `inactive_staff` · `unknown_form`. 없는 대상은 404 `ADM_ITEM_NOT_FOUND`(품목) · `ADM_STAFF_NOT_FOUND`(직원)입니다.

<a id="adm-a01"></a>
#### ADM-A01 · GET `/admin/item-ccp` — 품목별 CCP 목록

| | |
|---|---|
| 사용자 | 필요 없음 |
| 쿼리 | `q`(이름·품목코드 일부) · `include_inactive` = `0`(기본) / `1`(사용 중지 품목 포함) · `only_own` = `0` / `1`(품목 설정만) |
| 응답 | 200 `{default: {MANUFACTURE: ["1P","2B","3P"], PACKAGING: []}, items: [{item_id, item_code, name, is_active, mode, processes, version, effective, planned_batches, running_batches}]}` · 반제품(`item_type = SEMI`)만, 품목코드 순 · 설정 행 없음 = `mode: "default"`·`version: 0` · `effective` = 실제로 쓸 공정 · 배치 수는 생산 전·생산 중 제조 배치(`v_doc_batch`) |
| 오류 | 400 `VALIDATION_ERROR`(`include_inactive`·`only_own`이 0·1 아님 — `invalid`) |
| 화면·기능 | **[생산 기준정보] › [품목별 CCP]** 목록 · [`F-ADM-04`](../guide/document-guide.md#114-품목별-ccp-정하기) |

<a id="adm-a02"></a>
#### ADM-A02 · PUT `/admin/item-ccp/{item_id}` — 품목 CCP 저장

| | |
|---|---|
| 사용자 | 필수 · `X-CSRFToken` 필수 |
| 본문 | `mode`(필수, `default` 기본 따름 / `own` 품목 설정) · `processes`(`own`일 때 `1P`·`2B`·`3P` 중 0~3개, 0개 = CCP 없음. `default`면 비우거나 생략) · `reason`(선택, 앞뒤 공백 정리 뒤 100자 이하) · `expected_version`(필수, 설정 없음 = 0) |
| 응답 | 200 `{item, changed}` — `item`은 A01 한 줄 모양. 같은 값이면 `changed: false`(저장·이력 없음) |
| 오류 | 400 `VALIDATION_ERROR`(`unknown_key` · `invalid`(mode) · `invalid_process`(없는 공정·중복·default인데 공정 있음) · `too_long`(사유) · `required`(expected_version) · `not_producible`(반제품 아님)) · 404 `ADM_ITEM_NOT_FOUND` · 409 `VERSION_CONFLICT` |
| 부수 효과 | `item_ccp` 행 저장(기본 따름으로 되돌려도 행은 남기고 `mode = default`, 버전 +1) · 이력 1행(`set`·`default`, 사유 포함). **다음 생산 시작부터** 적용 — 이미 적용 기록(`batch_ccp_applied`)이 있는 배치는 그대로 |
| 화면·기능 | **[품목별 CCP]** [편집] → [저장] · [`F-ADM-04`](../guide/document-guide.md#114-품목별-ccp-정하기) |

<a id="adm-a03"></a>
#### ADM-A03 · GET `/admin/staff` — 직원 목록(관리용)

| | |
|---|---|
| 사용자 | 필요 없음(처음 설정 화면에서도 읽음) |
| 쿼리 | `q`(이름·코드 일부) · `state` = `all`(기본) / `active` / `inactive` |
| 응답 | 200 `{setup: {no_active_staff}, items: [{id, staff_code, name, is_active, created_at, roles: {is_leader, owner_of, writer_of}}]}` — 직원 번호 순, 비활성 포함 역할 요약 |
| 오류 | 400 `VALIDATION_ERROR`(`state` 값 — `invalid`) |
| 화면·기능 | **[시스템] › [설정]** 직원 카드 · 처음 설정의 비활성 직원 목록 · [`F-ADM-02`](../guide/document-guide.md#112-직원-관리) · [`F-ADM-01`](../guide/document-guide.md#111-처음-설정) |

활성 직원 0명 판정 자체는 문서 쪽 [`DOC-A01`](#doc-a01)(활성만, 빈 목록 = 0명)으로 합니다.

<a id="adm-a04"></a>
#### ADM-A04 · GET `/admin/staff/next-code` — 직원 코드 제안

| | |
|---|---|
| 사용자 | 필요 없음 |
| 응답 | 200 `{code}` — `영문-숫자` 형식이 가장 많은 접두어의 최대 번호 + 1(자릿수 유지, 예 `DEV-006`). 없으면 `S-001` |
| 화면·기능 | 직원 등록 창의 코드 기본값 · `F-ADM-01` `F-ADM-02` |

<a id="adm-a05"></a>
#### ADM-A05 · POST `/admin/staff` — 직원 등록

| | |
|---|---|
| 사용자 | 필수 · `X-CSRFToken` 필수. **활성 직원 0명이면 헤더 없이 됨**(처음 설정) |
| 본문 | `name`(필수, 앞뒤 공백 정리 뒤 1~40자) · `staff_code`(필수, 1~20자, 비활성 포함 유일 — 등록 뒤 바꿀 수 없음) |
| 응답 | 201 `{staff}`(A03 한 줄 모양, 역할 없음) |
| 오류 | 400 `VALIDATION_ERROR`(`unknown_key` · `invalid`(빈 값·길이) · `duplicate_code` · `setup_finished`(헤더 없이 보냈는데 활성 직원이 이미 있음)) |
| 부수 효과 | 수불 `staff` 표에 활성 직원 1행(`staff_admin.create`) · 이력 `create`(처음 설정이면 `bootstrap_create`, 누가 = 등록된 직원) |
| 화면·기능 | 직원 카드 [+ 직원] · 처음 설정 화면 [등록] · `F-ADM-01` `F-ADM-02` |

<a id="adm-a06"></a>
#### ADM-A06 · PATCH `/admin/staff/{staff_id}` — 직원 이름 수정

| | |
|---|---|
| 사용자 | 필수 · `X-CSRFToken` 필수 |
| 본문 | `name`만(필수, 1~40자). `staff_code` 등 다른 키는 `unknown_key` |
| 응답 | 200 `{staff, changed}` — 같은 이름이면 `changed: false`(이력 없음) |
| 오류 | 400 `VALIDATION_ERROR`(`required` · `invalid` · `unknown_key`) · 404 `ADM_STAFF_NOT_FOUND` |
| 부수 효과 | 수불 `staff.name` 변경(`staff_admin.rename`) · 이력 `rename` |
| 화면·기능 | 직원 줄 [이름 수정] · [`F-ADM-02`](../guide/document-guide.md#112-직원-관리) |

<a id="adm-a07"></a>
#### ADM-A07 · GET `/admin/staff/{staff_id}/impact` — 비활성 영향

| | |
|---|---|
| 사용자 | 필요 없음 — 보내면 `is_current_user`를 판정 |
| 응답 | 200 `{staff, roles, pending_approvals, sole_approvals: [{approval_id, request_id, document_id, type_code, subject, slot_label, role, requested_by, requester_active}], pending_checks, inspector_docs, orphaned: [{type_code, name, role, effect, forms?}](팀장 0명 줄은 type_code null + forms), active_leaders, last_active, is_current_user}` · `orphaned` = 이 사람을 빼면 활성 보유자가 0명이 되는 곳, `effect` = `submit_blocked` / `write_leader_only`(팀장 0명은 `type_code: null` 한 줄 + 영향 양식 `forms`) · `last_active` = 마지막 활성 직원 |
| 오류 | 404 `ADM_STAFF_NOT_FOUND` |
| 화면·기능 | [비활성…] 확인 창 · 처음 설정에서 다시 활성 행을 펼칠 때 · `F-ADM-01` `F-ADM-02` |

읽기만 합니다. 결재(APR)·개선조치·점검자(DOC) 읽기 함수를 함께 부릅니다.

<a id="adm-a08"></a>
#### ADM-A08 · POST `/admin/staff/{staff_id}/active` — 비활성·다시 활성

| | |
|---|---|
| 사용자 | 필수 · `X-CSRFToken` 필수. **활성 직원 0명이면 `active: true`만 헤더 없이 됨**(처음 설정) |
| 본문 | `active`(필수, true/false) · `confirm_impact`(비활성할 때 `true` 필수 — 화면이 A07 확인을 건너뛰지 않게) |
| 응답 | 200 `{staff, changed}` — 같은 값이면 `changed: false`(이력 없음) |
| 오류 | 400 `VALIDATION_ERROR`(`required` · `invalid` · `unknown_key` · `confirm_required` · `last_active_staff`(마지막 활성 직원) · `setup_finished`) · 400 `STAFF_HEADER_MISSING`(헤더 없이 비활성) · 404 `ADM_STAFF_NOT_FOUND` |
| 부수 효과 | 이력 `deactivate`·`activate`(처음 설정이면 `bootstrap_activate`). 비활성 직원의 문서 권한 행은 남고 효과만 빠짐. 영향이 있어도 막지 않음 |
| 화면·기능 | 직원 줄 [비활성…]·[다시 활성] · 처음 설정 · `F-ADM-01` `F-ADM-02` |

수불 CSV 가져오기·수불 `/staff/` API로 바꾼 것은 이력에 남지 않고, 마지막 직원 막기도 없습니다(0명이 되면 다음 접속 때 처음 설정).

<a id="adm-a09"></a>
#### ADM-A09 · GET `/admin/roles` — 문서 권한(편집용)

| | |
|---|---|
| 사용자 | 필요 없음 |
| 응답 | 200 `{version, setup, leaders: [{id, staff_code, name, is_active}], forms: [{type_code, name, slots, labels, owners, writers, warnings}], warnings}` · 활성 양식 순서(DOC 양식 목록) · **비활성 사람도 포함**(화면이 점선으로 표시) · `slots` = `owner` / `owner_leader` / `leader` / `none`, 양식 행이 없으면 `null` · `setup`은 `ROLE-A01`과 같음 |
| 화면·기능 | **[문서 권한]** 편집 화면 · [`F-ADM-03`](../guide/document-guide.md#113-문서-권한-정하기) |

<a id="adm-a10"></a>
#### ADM-A10 · PUT `/admin/roles` — 문서 권한 저장

| | |
|---|---|
| 사용자 | 필수 · `X-CSRFToken` 필수 |
| 본문 | `expected_version`(필수, 1 이상 — A09의 `version`) · `leaders`(선택, 직원 id 목록 — 보내면 팀장 전체를 이것으로) · `forms`(선택, `{type_code: {owners?, writers?}}` — 보낸 양식·역할만 이 목록으로, 안 보낸 것은 그대로). `slots`·`labels`는 바꾸지 않음(`unknown_key`) |
| 응답 | 200 `{version, changes: [{role, type_code, before, after}], warnings}` — 바뀐 곳이 없으면 `changes: []`, 버전 그대로 |
| 오류 | 400 `VALIDATION_ERROR`(`unknown_key` · `required` · `invalid` · `duplicate`(목록 안 같은 직원) · `unknown_form` · `unknown_staff` · `inactive_staff`(새로 넣는 비활성 직원)) · 409 `VERSION_CONFLICT` |
| 부수 효과 | 바뀐 팀장·양식×역할만 다시 씀(`role_leader`·`role_form_member`) · 전체 버전 +1(조건부) · 바뀐 곳마다 이력 `change` 1행. **재시작 없이 다음 작성·상신·결재부터 적용**, 이미 상신된 결재 후보는 그대로. 0명이 되는 역할도 저장되고 `warnings`로만 알림 |
| 화면·기능 | **[문서 권한]** [저장…] → [저장] · [`F-ADM-03`](../guide/document-guide.md#113-문서-권한-정하기) |

이미 들어 있던 비활성 직원은 목록에 그대로 둘 수 있습니다(`inactive_staff`는 저장 전 행에 없던 사람만). 담당자·작성 권한자·팀장 겹침은 허용합니다.

<a id="adm-a11"></a>
#### ADM-A11 · GET `/admin/history` — 관리 설정 변경 이력

| | |
|---|---|
| 사용자 | 필요 없음 |
| 쿼리 | `target`(필수) = `item_ccp` / `staff` / `roles`(팀장·양식·가져오기 묶음) · `target_id`(선택, 품목 id·직원 id·양식 행 id, 팀장 = 0) · `limit`(1~200, 기본 200) |
| 응답 | 200 `{items: [{log_id, label, at, actor: {id, name}, target, target_id, action, before, after, reason}]}` — 최신순, `at`은 한국 시각, `label` = 대상 이름(품목·직원 "이름(코드)", 양식 코드, "HACCP팀장", "문서 권한 가져오기") |
| 오류 | 400 `VALIDATION_ERROR`(`target`·`target_id`·`limit` — `invalid`) |
| 화면·기능 | 세 화면의 [이력] · `F-ADM-02` `F-ADM-03` `F-ADM-04` |

`action` 값은 [ERD — `admin_change_log`](../erd/document.md#admin_change_log)에 있습니다. 관리 명령 `import_roles`도 이 표에 `roles_import` 1행을 남깁니다.
