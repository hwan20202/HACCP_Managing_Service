# ERD — JSON 칸 구조

이 시스템은 양식마다 칸이 달라서, 칸 구성과 값을 표의 컬럼이 아니라 **JSON 칸**에 저장합니다. ERD 그림에는 `json` 한 칸으로만 보이므로 안의 모양을 여기에 적습니다.

> 현재 기준 2026-10-27 · 기준 코드 `2234f02`(main) · 근거 `backend/apps/documents/seed_forms.py`(양식 정의) · `documents/services.py`(값·스냅샷) · `production_log/services.py`(덮어쓸 값). 모든 JSON 칸에는 DB 검사 `JSON_VALID(...)`가 걸려 있습니다.

| 표.컬럼 | 무엇 | 바뀌나 |
|---|---|---|
| [`document_template.schema_json`](#양식-정의-document_templateschema_json) | 양식 정의 — 영역·칸·판정 규칙·관리기준 안내 | 바꾸지 않음(새 버전 행) |
| [`doc_section.values_json`](#칸-값-doc_sectionvalues_json) | 문서 한 줄의 칸 값 | 수정할 때마다 |
| [`approval_request.snapshot_json`](#결재-스냅샷-approval_requestsnapshot_json) | 상신 순간 문서 전체 | 바꾸지 않음 |
| [`process_template_step.overrides_json`](#템플릿-덮어쓸-값-process_template_stepoverrides_json) | 템플릿 단계에서 공정 값 덮어쓰기 | 템플릿 수정 때 |
| [`master_change_log.before_json`·`after_json`](#변경-이력-master_change_logbefore_jsonafter_json) | 공정·템플릿 변경 전후 값 | 바꾸지 않음 |

## 양식 정의 `document_template.schema_json`

```json
{
  "requirement_only": true,
  "skippable": true,
  "approval": false,
  "layout": "prodlog",
  "files": {"min": 1, "kinds": ["원산지 증명", "수입면장"]},
  "deviation": {"check_visibility": "immediate"},
  "guide": [{"title": "관리기준", "rows": [["한계기준", "자력 8,000 가우스 이상 …"]]}],
  "sections": [ { "key": "info", "label": "기본정보", "repeat": false, "fields": [ … ] } ]
}
```

**맨 위 키**

| 키 | 뜻 | 쓰는 양식 |
|---|---|---|
| `requirement_only` | true면 [새 문서]로 못 만들고 입고·생산·주기로만 생김 | 업무 양식 전부 |
| `skippable` | true면 작성 안 함 처리 가능 | D10·D11·D12 |
| `approval` | false면 결재 없음(작성중 ↔ 작성완료만) | PROD-LOG |
| `layout` | 화면·출력이 특별한 모양을 쓸 때 | PROD-LOG(`prodlog`) |
| `files` | 증빙 파일 — `min` 최소 개수, `kinds` 서류 종류 | D01·D02 |
| `deviation.check_visibility` | 개선조치가 확인 대기에 나타나는 때: `immediate`(적자마자) / 없으면 `after_complete`(작성완료 뒤) | CCP-1P·2B·3P가 `immediate` |
| `guide` | 화면 위 관리기준 안내 표(`title` + `[이름, 내용]` 줄) | 대부분 |
| `sections` | 영역 목록(아래) | 전부 |

**영역 `sections[]`**

| 키 | 뜻 |
|---|---|
| `key` · `label` | 영역 키(`doc_section.section_def`가 됨) · 화면 이름 |
| `repeat` | true면 반복 영역(줄 여러 개), false면 한 줄 |
| `min_rows` · `max_rows` | 반복 영역 줄 수 범위(CCP 측정 기록 2~48) |
| `phase_order` | 측정시점 순서 — `{field, time_field, first, last}`(첫 줄·마지막 줄 시점) |
| `fixed_phase_rows` | true면 첫 줄·마지막 줄 측정시점을 고정하고 그 사이에만 줄을 넣음 |
| `nonconforming` | 부적합 조건 — `{"any": [조건, …]}`. 하나라도 참이면 그 줄(문서)이 부적합 → 작성완료 전 개선조치 필요 |
| `elapsed` | 경과 시간 계산 — `{value_field, verdict_field, min, max}`(CCP-2B 총 건조시간 115~125분) |
| `fields` | 칸 목록(아래) |

**칸 `fields[]`**

| 키 | 뜻 |
|---|---|
| `key` · `label` | 칸 키(`values_json`의 키) · 화면 이름 |
| `type` | `text` · `number` · `date` · `datetime` · `select` · `staff`(직원 id) · `bool` |
| `required` | 작성완료에 필요한 칸 |
| `options` · `option_labels` | 고를 값과 화면 표시(예: `NA` → "해당 없음") |
| `readonly` | 사람이 쓰지 않는 칸(입고·배치에서 가져오거나 계산) |
| `limit` | 한계기준 표시용 `{min, max}` |
| `computed` | 자동 판정 — `{"all": [조건, …], "then": "적합", "else": "부적합"}` |
| `max_length` · `unit` · `display` | 글자 수 제한 · 단위 · 표시 방식(`hm` = 시간·분) |
| `cadence` · `group` | 점검표의 주기(매일 작업 전후·매주(금) …)와 묶음 이름 |
| `date_window` | 날짜 칸 허용 범위(D11 점검일 = 그 주 월~일) |

**조건** 한 개는 `{"field": "칸 키", "eq": 값}` · `{"field", "gt": 수}` · `{"field", "min": 수, "max": 수}` 모양입니다. 값이 비어 판정할 수 없는 조건은 빼고 계산합니다.

양식별 실제 칸과 기준은 [기능 안내 8장](../guide/document-guide.md#8-지원-문서양식별)에 사람 말로 정리돼 있습니다.

## 칸 값 `doc_section.values_json`

한 줄의 값을 `{칸 키: 값}`으로 저장합니다.

```json
{"phase": "작업시작 전", "measured_at": "2026-10-27T09:00", "gauss": 8200, "rod_cleaned": "O", "verdict": "적합"}
```

- `staff` 칸은 직원 id(정수), `select`는 고른 값 문자열, 날짜는 ISO 문자열입니다.
- `computed`·`elapsed`·시스템 칸(CCP 판정, 총 건조시간, D03 시험성적서 유무, 생산일지 `done`)은 **저장할 때 서버가 다시 계산해 덮어씁니다.** 화면이 보낸 값은 쓰지 않습니다.
- 점검자는 기본정보 영역(`info`) 줄의 `inspector` 값입니다.
- `round` 키가 있는 줄(측정 회차)은 한 문서·영역에서 같은 회차를 두 번 둘 수 없습니다(재측정 `retake`는 예외 — 인덱스 `ux_section_round`, 오류 `DUPLICATE_ROUND`).
- 생산일지의 `frozen_batch`·`frozen_materials` 영역은 **작성완료 순간 수불 값을 고정한 사본**입니다. 수량은 `*_e6`(백만 배 정수)로 저장합니다.

## 결재 스냅샷 `approval_request.snapshot_json`

상신하는 순간의 문서 상세(`DOC-A05` 응답과 같은 모양)를 통째로 저장합니다. 결재자가 보는 내용, 결재 요청 상세의 "상신 당시" 내용, 정정 중 출력의 이전 승인본이 모두 이 값입니다.

| 키 | 내용 |
|---|---|
| `document_id` · `template` · `subject` · `work_date` · `status` · `version` · `record_key` · `created_*` · `completed_*` · `submitted_at` | 문서 머리 |
| `refs` | 업무 대상 연결(`document_ref` 행들) |
| `sections` | 칸 값 줄 전부 — `{section_id, section_def, row_no, values, recorded_at, recorded_by}` |
| `files` | 연결된 증빙 파일 |
| `deviations` | 그 순간의 개선조치 |
| `correction` · `corrections` | 열린 정정과 정정 이력 |
| `requirement` · `skippable` · `skip` · `prefilled` · `target_summary` | 화면용 부가 정보 |

- 한 번 저장하면 바꾸지 않습니다. 예외로 CCP-3P 양식 v2 전환 마이그레이션(`documents` 0004)이 옛 스냅샷의 칸 이름을 옮긴 적이 있습니다.

## 템플릿 덮어쓸 값 `process_template_step.overrides_json`

템플릿 단계에서 공정 목록의 값을 이 템플릿에서만 바꿀 때 씁니다. 없으면 `{}`.

| 공정 기능 | 덮어쓸 수 있는 키 |
|---|---|
| 모든 공정 | `name`(표시명) · `desc`(설명, 300자) · `duration`(소요기간) |
| 일반 공정(`GEN`) | + `mode`(입력 방식) |
| 내포장(`INNER`) | + `spec`(규격, 40자) · `qty_unit`(수량 단위, 10자) |
| 외포장(`OUTER`) | + `material`(포장재질, 100자) |

## 변경 이력 `master_change_log.before_json`·`after_json`

공정·템플릿 한 건의 바뀌기 전·뒤 값(공정이면 `process` 행, 템플릿이면 단계 목록 포함)입니다. 만들기는 `before_json`이 NULL, 삭제는 `after_json`이 NULL이고, 복제는 `before_json`에 원본 번호(`{"from": 번호}`)가 들어갑니다. 화면 **[이력]** 이 이 두 값을 비교해 "전 → 후"로 보여 줍니다.
