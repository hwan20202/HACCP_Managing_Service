# 생산·수불(inventory) 화면 개발 방향

기존 시제품(`frontend/static/prototype`)을 검토한 결과와 화면 개발 기준입니다. 개발 현황은 [inventory-roadmap.md](inventory-roadmap.md) 9번, API 는 [inventory-decisions.md](inventory-decisions.md) "API 요약".

## 결론

**화면 틀과 디자인은 시제품을 그대로 쓰고, 재고 메뉴의 데이터 처리(`inventory.js`)만 API 연결 버전으로 새로 작성한다.**

- 사용자에게 보이는 모습(메뉴, 표, 탭, 모달, 색)은 시제품과 같게 유지
- 시제품은 고정 데이터(`HACCP_DATA`)를 화면에서 직접 고치는 구조라, 수정 불가·정정 원칙의 수불과 맞지 않음 → 고쳐 쓰기보다 새로 쓰는 편이 빠름
- 다른 메뉴(CCP, 생산일지, 대시보드 등)는 당분간 기존 고정 데이터로 그대로 동작

## 시제품 검토 결과

### 그대로 쓰는 것

| 항목 | 위치 | 비고 |
|---|---|---|
| 전체 틀 (사이드바, 헤더, 페이지 전환) | `templates/index.html`, `prototype/js/app.js` | 문서 담당자와 공유 |
| 디자인 (카드, 표, 탭, 모달, 토스트, 버튼) | `prototype/css/main.css` | 문서 담당자와 공유 |
| 수불대장 화면 구성 | `inventory.js` `render()` | 수불 내역 / 현재고 탭, 검색, 입고·출고 필터, 기간 빠른 선택, 엑셀 다운로드 |
| 현재고 표 컬럼 | `inventory.js` `renderStock()` | 품목코드, 최소재고, 재고상태, LOT, 소비기한 임박 → `stock/items`, `stock/lots` API 와 대응 |
| 수불대장 인쇄 양식 | `inventory.js` `printItemHistory()` | 회사명, "원료 수 불 대 장", No·날짜·구분·입고·출고·현재고·LOT·소비기한·공급업체·담당자·비고 → 현업 출력 양식 기준 |
| 입출고 등록 입력 항목 | `inventory.js` `openModal()` | 품목, 날짜, 수량, LOT, 소비기한, 공급업체, 담당자, 비고 → 입고 등록 API 와 대응 |

### 바꾸는 것

| 시제품 방식 | 문제 | 바꿀 방향 |
|---|---|---|
| 데이터가 `data.js` 고정값 (`HACCP_DATA`) | 서버와 연결 안 됨 | `/api/v1/inventory/` 호출 |
| 표 칸을 클릭해서 날짜·수량·LOT 직접 수정 | 수불은 수정 불가 (I2), HACCP 기록 원칙과 충돌 | 행마다 "정정" → 사유 입력 → 정정 API |
| LOT 번호 직접 입력 | 서버가 자동 채번 | 입고 후 채번된 번호 표시 |
| 행마다 잔량 저장 | 서버가 계산 | 수불대장 API 의 누적 잔량 표시 |
| "입출고 등록" 하나로 입고·출고 | 유형마다 규칙이 다름 | 입고 등록 / 조정 / 반품 / 폐기 분리 |
| 일괄 업로드, 새 품목 등록을 브라우저에서 처리 | 서버 검증 없음 | 기준정보 API, `seed_master` |
| 단위 변환(kg ↔ g)을 저장값에 반영 | 수량은 품목 기준 단위로만 저장 (S3) | 표시할 때만 변환 |

## 화면 목록과 API

| 화면 | 메뉴 위치 | API | 순서 |
|---|---|---|---|
| 원료 수불대장 — 수불 내역 | 원료 수불대장 | `ledger/`, `ledger/export.csv` | 1 ✅ 10/15 (`inventory-api.js` 수불일지) |
| 원료 수불대장 — 현재고 | 원료 수불대장 탭 | `stock/items/`, `stock/lots/` | 1 ✅ 10/15 (`inventory-api.js` 재고장, LOT별) |
| 입고 등록 (기본정보) | 원료 수불대장 버튼 | `receipts/` POST, `items/`, `suppliers/`, `staff/` | 1 |
| 입고 목록·상세·취소 | 원료 수불대장 | `receipts/`, `receipts/<id>/cancel/` | 2 |
| LOT 상세 + 이력, 판정 반영 | 행 클릭 | `lots/<id>/`, `lots/<id>/judgment/` | 2 |
| 조정 / 반품 / 폐기 / 정정 | LOT 상세 | `movements/...` | 2 |
| 수불대장 인쇄 | 수불대장 버튼 | `ledger/` | 3 |
| 부자재(포장재) 수불대장 | 부자재 수불대장 | 같은 API, `item_type=PACKAGING` | 3 |
| 기준정보 관리 | 설정 | `staff/`, `suppliers/`, `items/` | 3 |
| 기초재고 이관 | 설정 (운영 시작 1회) | `movements/opening-balance/` | 4 |
| 완제품 수불대장, 생산 | 완제품 수불대장, 생산일지 | 0002 이후 | 생산 개발 후 |
| 입고 육안검사 체크리스트 | 입고 등록 안 | 문서 쪽 `get_incoming_inspection_form()` | 문서 쪽 함수 형식 후 |

## 개발 기준

- **파일**: 새 재고 화면은 `prototype/js/modules/inventory.js` 를 대체하는 API 버전으로 작성. 기존 파일은 교체 전까지 보존
- **API 호출**: 공통 `fetch` 도우미 하나 — JSON 처리, `X-CSRFToken` 헤더(쿠키 `csrftoken`), 오류 응답의 `error.message` 를 토스트로 표시
- **수량**: API 는 기준 단위의 문자열(`"50.25"`). 화면 계산에 `parseFloat` 를 쓰지 않음 (표시만)
- **중복 등록 방지**: 등록 화면을 열 때 요청 키(`idempotency_key`, 예: `crypto.randomUUID()`) 를 만들어 저장 버튼에 함께 전송
- **처리자**: 로그인이 없으므로(MVP) 담당자 선택 드롭다운의 `staff_id` 를 전송
- **수정 없음**: 저장된 수불은 화면에서 고칠 수 없게 하고 정정·취소 버튼만 제공
- **외부 리소스 없음**: 폰트·라이브러리 CDN 을 쓰지 않음 (CONTRIBUTING)

## 문서 담당자와 맞출 것

- `app.js`(메뉴, 페이지 전환), `main.css`, `index.html` 은 양쪽이 같이 쓰므로 메뉴 추가·공통 스타일 변경은 미리 공유
- 입고 등록 화면에 들어갈 육안검사 체크리스트는 문서 쪽 정의(`get_incoming_inspection_form()`)로 그림
- 공통 `fetch` 도우미, 모달·토스트 사용법을 같이 쓰면 화면 동작이 통일됨

## 확인 필요

- PM 스토리보드가 이 시제품과 같은 화면인지, 별도 자료(이미지·PDF·피그마 등)인지. 별도라면 비교해서 기준을 정함

## 10/15 구현 상태

- `prototype/js/modules/inventory-api.js` (`InventoryApiPage`): 재고장(LOT별 현재고)·수불일지 두 탭. 원료·부자재·완제품 메뉴가 이 화면을 씀 (`app.js` 의 3줄, `index.html` 에 스크립트 1줄 추가 — 문서 담당자와 공유 필요). 완제품 메뉴는 반제품(벌크)·완제품을 함께 보여 줌.
- 소비기한은 날짜가 없으면 "소비기한 없음"(NONE)과 "미확인"(UNKNOWN) 배지로 구분.
- 조회 전용. 입고 등록·조정·정정 화면은 다음 단계. 기존 `inventory.js` 는 그대로 둠 (다른 화면에서 쓰지 않음).
