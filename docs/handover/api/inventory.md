# API 명세 — 수불 쪽

입고·재고·수불·생산·BOM·보류 화면이 서버에 보내는 API입니다. [문서 쪽](document.md)과 같은 틀로 쓰되, **수불 쪽은 규칙이 달라서** 아래 "공통 규칙"을 먼저 봅니다.

> 현재 기준 2026-10-28 · 코드 기준 `2234f02` · 확인한 `origin/main` `c011126`(문서만 변경) · 경로는 모두 `/api/v1/inventory` 아래(표에는 뒷부분만) · 목록 53개(메서드 기준, 42경로)는 `inventory/urls.py`와 1:1로 맞춤
>
> **[수불 담당 확인 전 초안]** `inventory/api.py`와 서비스 함수를 읽고 문서 담당이 썼습니다. 수불 담당이 확인하기 전까지는 참고로만 봅니다.

## 공통 규칙 — 수불 쪽

| 항목 | 규칙 | 문서 쪽과 다른 점 |
|---|---|---|
| 기본 경로 | `/api/v1/inventory/…/` — **끝 슬래시 있음** | 문서 쪽은 없음 |
| 메서드 | 함수마다 허용 메서드를 정함(`endpoint(...)`). 다른 메서드는 405 | 같음 |
| 현재 사용자 | 헤더가 아니라 **본문의 `staff_id`**. 쓰기 요청 대부분이 필수 | 문서 쪽은 `X-Staff-Id` 헤더 |
| CSRF | Django CSRF 검사가 켜져 있음. GET 응답이 `csrftoken` 쿠키를 주고, POST·PATCH는 그 값을 `X-CSRFToken` 헤더로 보냄 | 문서 쪽은 CSRF 검사 없음(사용자 헤더로 대신) |
| 요청 본문 | JSON 객체. 모르는 키를 **거부하지 않음** | 문서 쪽은 400 |
| 수량 | **기준단위의 10진수**(`"50.25"` 문자열이나 숫자). 응답도 10진 문자열. DB에는 `*_e6` 정수 | — |
| 날짜·시각 | 날짜 `YYYY-MM-DD`, 시각 ISO. 시간대가 없으면 KST로 봄 | — |
| 목록 응답 | `{"results": [...]}`, 쪽 나눔이 있으면 `+ "count"`. 쪽 나눔은 `limit`(기본 100, 최대 500)·`offset` | 문서 쪽 `{items, total, page, page_size}` |
| 오류 | `{"error": {"message": "…", "fields": {...}?, "code": "…"?}}`. 400 잘못된 요청·**업무 규칙 위반** · 404 없음 · 405 메서드 · 409 중복·충돌 | 문서 쪽 `{code, message, details}`, 업무 규칙 위반은 대부분 409 |
| 오류 코드 | 수불 오류에는 `code`가 **없고** `message`만 있음. 같은 요청 안에서 문서 쪽 함수가 실패하면 그 오류의 `code`·`details`가 `code`·`fields`로 실려 옴 | — |
| 같은 요청 두 번 | 수불 기록을 만드는 요청은 `idempotency_key`(필수)로 같은 요청을 한 번만 처리 | 문서 쪽은 `expected_version` |

**문서 쪽과 같은 트랜잭션으로 묶인 요청** — 문서 쪽 함수가 실패하면 수불 쪽 변경도 함께 취소됩니다.

| 요청 | 문서 쪽에서 일어나는 일 |
|---|---|
| 입고 등록 `POST receipts/`·`receipts/import/` | LOT마다 D01·D02·D03 생성. 적합 판정이면 D03을 채워 작성완료 시도 |
| 입고 취소 `POST receipts/{id}/cancel/` | 그 LOT의 D01·D02·D03 논리 삭제(결재 상태에 따라 막힘) |
| 생산 시작 `POST batches/{id}/start/` | 제조 배치면 CCP-1P·2B·3P 일지 생성, 생산일지 양식이 설치돼 있으면 생산일지도 |
| (반대 방향) D03 작성완료 | 문서 쪽이 수불 판정 함수(`judgment.apply_incoming_judgment`)를 부름 — API가 아니라 함수 |

## 목록

API ID는 설계 때 번호가 없어 모두 `—`입니다(새로 매기지 않음). 기능 ID는 [수불 기능 안내](../guide/inventory-guide.md)의 번호이며, 직접 대응하는 사용자 기능이 없는 API는 `—`입니다. "상세"의 앵커 이름으로 찾습니다.

**1. 코드·기준정보**

| 메서드 | 경로 | 기능 ID | 하는 일 | 구현 | 상세 |
|---|---|---|---|---|---|
| GET | `/item-types/` | `F-INV-00` | 품목 구분 코드 | `api.py::item_types` | [보기](#inv-codes) |
| GET | `/movement-types/` | `F-INV-00` | 수불 유형 코드 | `api.py::movement_types` | [보기](#inv-codes) |
| GET·POST | `/staff/` | `F-INV-00` | 직원 목록·등록 | `api.py::staff_collection` | [보기](#inv-master) |
| GET·PATCH | `/staff/{pk}/` | `F-INV-00` | 직원 한 명·수정 | `api.py::staff_detail` | [보기](#inv-master) |
| GET·POST | `/suppliers/` | `F-INV-00` | 공급처 목록·등록 | `api.py::supplier_collection` | [보기](#inv-master) |
| GET·PATCH | `/suppliers/{pk}/` | `F-INV-00` | 공급처 한 곳·수정 | `api.py::supplier_detail` | [보기](#inv-master) |
| GET·POST | `/items/` | `F-INV-00` | 품목 목록·등록 | `api.py::item_collection` | [보기](#inv-master) |
| GET·PATCH | `/items/{pk}/` | `F-INV-00` | 품목 하나·수정 | `api.py::item_detail` | [보기](#inv-master) |
| POST | `/items/delete/` | `F-INV-08` | 쓰지 않은 품목 지우기(미리 보기 → 확정) | `api.py::item_remove` | [보기](#inv-item-remove) |

**2. 입고·LOT**

| 메서드 | 경로 | 기능 ID | 하는 일 | 구현 | 상세 |
|---|---|---|---|---|---|
| GET | `/receipts/` | `F-INV-01` | 입고 목록 | `api.py::receipt_collection` | [보기](#inv-receipts-get) |
| POST | `/receipts/` | `F-INV-01` | 입고 등록 | `api.py::receipt_collection` | [보기](#inv-receipts-post) |
| POST | `/receipts/import/` | `F-INV-02` | 입고 여러 건(CSV 내용) 올리기 | `api.py::receipt_import` | [보기](#inv-receipts-import) |
| GET | `/receipts/{pk}/` | `F-INV-01` | 입고 한 건 | `api.py::receipt_detail` | [보기](#inv-receipts-get) |
| POST | `/receipts/{pk}/cancel/` | `F-INV-03` | 입고 취소 | `api.py::receipt_cancel` | [보기](#inv-receipts-cancel) |
| GET | `/lots/{pk}/` | `F-INV-06` | LOT 상세 + 수불 이력 | `api.py::lot_detail` | [보기](#inv-lots) |
| POST | `/lots/{pk}/judgment/` | — | 입고 판정 반영(적합·부적합) | `api.py::lot_judgment` | [보기](#inv-lots-judgment) |

**3. 재고·원료수불대장**

| 메서드 | 경로 | 기능 ID | 하는 일 | 구현 | 상세 |
|---|---|---|---|---|---|
| GET | `/stock/lots/` | `F-INV-05` | LOT별 재고 | `api.py::stock_lots` | [보기](#inv-stock) |
| GET | `/stock/items/` | `F-INV-05` | 품목별 재고 | `api.py::stock_items` | [보기](#inv-stock) |
| GET | `/ledger/` | `F-INV-04` | 원료수불대장 | `api.py::ledger` | [보기](#inv-ledger) |
| GET | `/ledger/export.csv` | `F-INV-04` | 원료수불대장 CSV 내려받기 | `exports.py::ledger_csv` | [보기](#inv-ledger) |
| GET | `/ledger/changes/` | `F-INV-04` | 승인 뒤 바뀐 수불 찾기 | `api.py::ledger_changes` | [보기](#inv-ledger-changes) |

**4. 수불 기록**

| 메서드 | 경로 | 기능 ID | 하는 일 | 구현 | 상세 |
|---|---|---|---|---|---|
| POST | `/movements/opening-balance/` | `F-INV-00` | 기초재고 이관 | `api.py::opening_balance` | [보기](#inv-opening) |
| POST | `/movements/adjust/` | `F-INV-07` | 재고조정(증가·감소) | `api.py::adjust` | [보기](#inv-adjust) |
| POST | `/movements/return/` | `F-INV-07` | 공급처 반품 | `api.py::return_view` | [보기](#inv-outflow) |
| POST | `/movements/disposal/` | `F-INV-07` | 폐기 | `api.py::disposal_view` | [보기](#inv-outflow) |
| POST | `/movements/{pk}/correct/` | `F-INV-07` | 수불 기록 정정 | `api.py::correct` | [보기](#inv-correct) |

**5. 생산(제조 배치)**

| 메서드 | 경로 | 기능 ID | 하는 일 | 구현 | 상세 |
|---|---|---|---|---|---|
| GET | `/batches/` | `F-PRD-02` | 배치 목록 | `api.py::batch_collection` | [보기](#inv-batches-get) |
| POST | `/batches/` | `F-PRD-02` | 배치 등록(계획) | `api.py::batch_collection` | [보기](#inv-batches-post) |
| GET | `/batches/preview/` | `F-PRD-02` | 계획 미리 보기(원료 소요량·가용량) | `api.py::batch_preview` | [보기](#inv-batches-preview) |
| GET | `/batches/fefo/` | `F-PRD-04` | 투입 LOT 추천(소비기한 빠른 순) | `api.py::fefo` | [보기](#inv-fefo) |
| GET | `/batches/{pk}/` | `F-PRD-02` | 배치 상세 | `api.py::batch_detail` | [보기](#inv-batch-detail) |
| POST | `/batches/{pk}/start/` | `F-PRD-03` | 생산 시작 | `api.py::batch_start` | [보기](#inv-batch-start) |
| GET | `/batches/{pk}/allocation/` | `F-PRD-04` | BOM 줄 하나의 투입 LOT 제안 | `api.py::batch_allocation` | [보기](#inv-allocation) |
| POST | `/batches/{pk}/bulk-allocation/` | `F-PRD-04` | 남은 원료 전체의 투입 LOT 제안 | `api.py::batch_bulk_allocation` | [보기](#inv-allocation) |
| POST | `/batches/{pk}/usages/` | `F-PRD-04` | 원료 투입(한 건·여러 건) | `api.py::batch_usage` | [보기](#inv-usages) |
| POST | `/batches/{pk}/outputs/` | `F-PRD-05` | 산출 등록 | `api.py::batch_output` | [보기](#inv-outputs) |
| POST | `/batches/{pk}/complete/` | `F-PRD-06` | 완료 | `api.py::batch_complete` | [보기](#inv-batch-complete) |
| POST | `/batches/{pk}/cancel/` | `F-PRD-07` | 취소 | `api.py::batch_cancel` | [보기](#inv-batch-cancel) |
| POST | `/batches/{pk}/switch-bom/` | `F-PRD-02` | 이전 BOM 계획을 활성 BOM으로 재지시 | `api.py::batch_switch_bom` | [보기](#inv-batch-switch-bom) |

**6. BOM**

| 메서드 | 경로 | 기능 ID | 하는 일 | 구현 | 상세 |
|---|---|---|---|---|---|
| GET·POST | `/boms/` | `F-PRD-01` | BOM 목록·등록(새 버전) | `api.py::bom_collection` | [보기](#inv-boms) |
| GET·PATCH | `/boms/{pk}/` | `F-PRD-01` | BOM 한 버전·수정 | `api.py::bom_detail` | [보기](#inv-boms) |
| POST | `/boms/{pk}/delete/` | `F-PRD-01` | BOM 지우기 | `api.py::bom_remove` | [보기](#inv-bom-delete) |

**7. 보류**

| 메서드 | 경로 | 기능 ID | 하는 일 | 구현 | 상세 |
|---|---|---|---|---|---|
| GET | `/holds/` | `F-PRD-08` | 보류 목록 | `api.py::hold_collection` | [보기](#inv-holds-get) |
| POST | `/holds/` | `F-PRD-08` | 보류 등록(LOT 또는 배치) | `api.py::hold_collection` | [보기](#inv-holds-post) |
| GET | `/holds/{pk}/` | `F-PRD-08` | 보류 한 건 | `api.py::hold_detail` | [보기](#inv-holds-get) |
| POST | `/holds/{pk}/release/` | `F-PRD-08` | 보류 해제 | `api.py::hold_release` | [보기](#inv-hold-release) |

## 상세

### 1. 코드·기준정보

<a id="inv-codes"></a>
#### GET `/item-types/` · `/movement-types/` — 코드 목록

| | |
|---|---|
| 응답 | 200 `{results: [{code, name}]}` · 수불 유형은 `direction`(1·-1)도 |
| 알아둘 점 | 코드 값은 마이그레이션이 넣음([ERD — 수불](../erd/inventory.md#item_types)) |

<a id="inv-master"></a>
#### GET·POST `/staff/` · `/suppliers/` · `/items/` — 기준정보 목록·등록 / GET·PATCH `…/{pk}/` — 한 건·수정

세 가지 기준정보가 같은 방식입니다.

| | |
|---|---|
| 쿼리(GET 목록) | `active` = `1`(기본) / `0` / `all` · `q`(코드·이름 검색) · `items/`만 `item_type` |
| 본문(POST) | 직원 `staff_code`·`name`·`is_active` · 공급처 `supplier_code`·`name`·`is_active` · 품목 `item_code`·`item_type`·`name`·`base_unit`(필수) + `short_code`·`unit_weight_mg`·`shelf_life_months` 또는 `shelf_life_days`·`origin_country`·`food_type`·`manufacturing_report_number`·`minimum_stock`·`is_stock_managed`·`is_active` |
| 본문(PATCH) | 바꿀 칸만. 지금 값과 합쳐 다시 검사 |
| 응답 | GET 목록 200 `{results}` · POST 201 한 건 · GET·PATCH 200 한 건 |
| 오류 | 409 같은 코드가 이미 있음 · 400 **코드는 바꿀 수 없음**(새로 등록) · 400 칸 값 · 404 |
| 알아둘 점 | 사용자(`staff_id`)를 받지 않습니다. LOT이 생긴 품목의 구분·재고 관리 여부는 DB 트리거가 막습니다. 직원은 지우지 않고 `is_active = 0` |

<a id="inv-item-remove"></a>
#### POST `/items/delete/` — 쓰지 않은 품목 지우기

| | |
|---|---|
| 본문 | `staff_id` · `item_ids`(목록) · `dry_run`(기본 **true** = 미리 보기만) · 실제로 지울 때 `dry_run: false` + `confirmation: "DELETE_UNUSED_ITEMS"` |
| 응답 | 200 지울 수 있는 품목과 막힌 품목(`blocked: [{id, name, reason}]`) |
| 오류 | 409 다른 업무에 연결된 기록이 있음 |
| 알아둘 점 | 입고만 있고 생산·보류·공유 문서가 없는 품목만 지웁니다. 지울 때 입고 수불 기록도 지우므로 DB의 예외 표(`inventory_purge_scope`)를 씁니다 |

### 2. 입고·LOT

<a id="inv-receipts-get"></a>
#### GET `/receipts/` — 입고 목록 / GET `/receipts/{pk}/` — 한 건

| | |
|---|---|
| 쿼리(목록) | `from`·`to`(입고일) · `supplier_id` · `item_id` · `status`(`COMPLETED`·`CANCELLED`) · `limit`·`offset` |
| 응답 | 200 `{count, results}` · 한 건은 입고(LOT·품목·공급처·담당·수량·상태) |
| 오류 | 400 조건 형식 · 404 |

<a id="inv-receipts-post"></a>
#### POST `/receipts/` — 입고 등록

| | |
|---|---|
| 본문 | `item_id`·`supplier_id`·`staff_id`·`received_date`·`quantity`·`idempotency_key`(필수) · `supplier_lot_number` · `manufactured_date` · `expiration_date` · `expiration_status`(`KNOWN`·`NONE`·`UNKNOWN`) · `judgment`(`PASS`·`FAIL`, 생략하면 판정 대기) · `inspection`(D03 검사값 객체) · `ea_count` |
| 응답 | 201 입고 |
| 부수 효과 | LOT 1개 + 입고 수불 기록 1개 + 현재고. **같은 트랜잭션에서 D01·D02·D03 생성**, `PASS`면 D03을 검사값으로 채워 작성완료 시도(실패해도 입고는 진행) |
| 오류 | 400 필수 값·날짜·수량(요청 키가 없으면 "요청 키(idempotency_key)가 필요합니다.") · 400 원료인데 소비기한 유무가 `KNOWN`·`NONE`이 아님 · 400 재고 비관리 품목 · 문서 쪽 오류(코드 포함)면 입고 전체 취소 |
| 화면 | 입고 화면 **[저장]** |

<a id="inv-receipts-import"></a>
#### POST `/receipts/import/` — 입고 여러 건 올리기

| | |
|---|---|
| 본문 | `rows`(1~500줄. 각 줄은 `item_code`·`supplier_code`·`received_date`·`quantity`와 필요 시 `unit`·소비기한·판정 등 입고 값) · 바깥 본문에 `staff_id`·`idempotency_key`(둘 다 필수) · `dry_run`(기본 true = 검사·미리 보기만). 줄의 `unit`을 비우면 품목 기준단위 사용 |
| 응답 | 200 줄마다 결과(오류 줄 표시). `dry_run: false`면 전부 등록 |
| 오류 | 400 요청 키가 없으면 "업로드 요청 키가 필요합니다." · 줄 오류가 있으면 전체 취소 |
| 화면 | 입고 **CSV 올리기** — 미리 보기에서 오류를 확인한 뒤 저장 |

<a id="inv-receipts-cancel"></a>
#### POST `/receipts/{pk}/cancel/` — 입고 취소

| | |
|---|---|
| 본문 | `staff_id`·`reason`(필수) |
| 응답 | 200 입고(`CANCELLED`) |
| 부수 효과 | 입고 수량만큼 정정 기록, **같은 트랜잭션에서 D01·D02·D03 논리 삭제** |
| 오류 | 400 사용·조정된 LOT, 이미 취소됨 · 문서 쪽 오류(결재 진행 중 등)면 취소 전체 취소 |

<a id="inv-lots"></a>
#### GET `/lots/{pk}/` — LOT 상세

| | |
|---|---|
| 응답 | 200 LOT(번호·품목·상태·소비기한·현재고) + `movements`(수불 이력, 시각 순) |
| 오류 | 404 |

<a id="inv-lots-judgment"></a>
#### POST `/lots/{pk}/judgment/` — 입고 판정 반영

| | |
|---|---|
| 본문 | `result`(`PASS`·`FAIL`) · `staff_id`(필수) · `document_id` · `judged_at` · `reason`(판정을 바꿀 때 필수) |
| 응답 | 200 LOT(`AVAILABLE`·`REJECTED`) |
| 오류 | 400 입고 외 수불이 생긴 LOT은 판정을 바꿀 수 없음 · 400 변경 사유 없음 |
| 알아둘 점 | 평소에는 D03 작성완료 때 문서 쪽이 **함수로** 부릅니다. 이 API는 화면·시험용. 결재 승인·반려는 판정을 바꾸지 않음 |

### 3. 재고·원료수불대장

<a id="inv-stock"></a>
#### GET `/stock/lots/` — LOT별 재고 / GET `/stock/items/` — 품목별 재고

| | |
|---|---|
| 쿼리(LOT별) | `item_type` · `item_id` · `status`(LOT 상태) · `include_empty`(0/1, 기본 0 = 재고 있는 것만) · `expiring_within_days` · `lot_number` · `manufactured_from`·`manufactured_to` · `expiration_status` · `usable_only`(0/1) · `q` |
| 쿼리(품목별) | `item_type` · `item_id` · `below_minimum`(1이면 최소 재고 미달만) |
| 응답 | 200 `{results}` — 수량은 10진 문자열, LOT별은 사용 가능 여부·활성 보류 수 포함 |
| 화면 | 수불대장 → **현재고** |
| 알아둘 점 | 현재고는 **지금** 값입니다. 과거 날짜의 잔량은 `/ledger/`로 봅니다 |

<a id="inv-ledger"></a>
#### GET `/ledger/` — 원료수불대장 / GET `/ledger/export.csv` — CSV

| | |
|---|---|
| 쿼리 | `from`·`to`(필수, 1년 이내) · `item_type` · `item_id` · `lot_id` · `lot_number` · `q` |
| 응답 | 200 `{from, to, results}` — 품목·LOT별 기간 수불과 줄마다 그 직후 잔량, 근거(입고·배치) 연결 · CSV는 파일 |
| 오류 | 400 기간 없음·순서·1년 초과 |
| 화면 | 수불대장 → **수불 내역** · 품목 상세 · **[인쇄 / PDF]** |

<a id="inv-ledger-changes"></a>
#### GET `/ledger/changes/` — 승인 뒤 바뀐 수불

| | |
|---|---|
| 쿼리 | `since`(필수, 승인 일시 `YYYY-MM-DDTHH:MM:SS`) · `from`·`to`(필수) · `item_type`·`item_id`·`lot_id` |
| 응답 | 200 `{changed: true/false, results}` — 그 시각 뒤에 기록된, 그 기간 대장을 바꾸는 수불 |
| 알아둘 점 | 출력해 결재받은 수불대장이 그 뒤 바뀌었는지 확인하는 용도. 화면에서 쓰는 곳은 확인 필요 |

### 4. 수불 기록

수불 기록은 **고치지 않고 더합니다.** 모두 `idempotency_key`가 필수이고, 응답은 201 수불 기록 + `lot_quantity`(그 LOT 현재고) · `lot_status`입니다.

<a id="inv-opening"></a>
#### POST `/movements/opening-balance/` — 기초재고 이관

| | |
|---|---|
| 본문 | `item_id`·`quantity`·`staff_id`·`occurred_at`·`idempotency_key`(필수) · `lot_number` · `manufactured_date` · `expiration_date` · `expiration_status` · `status`(기본 `AVAILABLE`) · `reason` |
| 부수 효과 | LOT을 새로 만들고 `OPENING_BALANCE` 기록. **문서는 만들지 않음** |
| 알아둘 점 | 운영 시작 때 실제 재고를 넣는 용도. 이관 절차는 [설치 안내](../installation.md) · 확인 필요 |

<a id="inv-adjust"></a>
#### POST `/movements/adjust/` — 재고조정

| | |
|---|---|
| 본문 | `lot_id`·`direction`(`IN`·`OUT`)·`quantity`·`reason`·`staff_id`·`idempotency_key`(필수) · `occurred_at`(지난 날짜 가능) |
| 오류 | 400 재고보다 많이 줄임(현재고가 음수가 되면 DB가 막음) |

<a id="inv-outflow"></a>
#### POST `/movements/return/` — 공급처 반품 · `/movements/disposal/` — 폐기

| | |
|---|---|
| 본문 | `lot_id`·`reason`·`staff_id`·`idempotency_key`(필수) · `quantity`(생략하면 **남은 전량**) · `occurred_at` |
| 알아둘 점 | 보류 해제의 처분(반품·폐기)은 기록일 뿐이고, 실제 재고는 이 요청으로 줄입니다 |

<a id="inv-correct"></a>
#### POST `/movements/{pk}/correct/` — 정정

| | |
|---|---|
| 본문 | `reason`·`staff_id`·`idempotency_key`(필수) · `quantity`(생략하면 남은 전량, 입고 정정은 일부만) |
| 부수 효과 | 원 기록 반대 방향의 `CORRECTION_IN`/`OUT` 기록. 실제 수량 = 원 수량 − 정정 합계 |
| 오류 | 400 정정할 수 없는 기록·수량 |

### 5. 생산(제조 배치)

배치 요청의 응답은 모두 **배치 상세**와 같은 모양입니다: 배치 · 투입·산출(정정 뺀 순수량) · 산출 LOT 요약(`output_lot`) · BOM 표준 대비 실제(`bom_check`) · 원료 준비 상태(`readiness`) · 보류(`holds`, `active_hold_count`).

<a id="inv-batches-get"></a>
#### GET `/batches/` — 배치 목록

| | |
|---|---|
| 쿼리 | `status`(`PLANNED`·`IN_PROGRESS`·`COMPLETED`·`CANCELLED`) · `exclude_cancelled`(0/1) · `process_type` · `item_id` · `from`·`to`(제조일, 없으면 계획일) · `limit`·`offset` |
| 응답 | 200 `{count, results}` — 줄마다 `active_hold_count` |

<a id="inv-batches-post"></a>
#### POST `/batches/` — 배치 등록

| | |
|---|---|
| 본문 | `item_id`·`staff_id`(필수) · `process_type`(`MANUFACTURE`만, 생략 가능) · `planned_date` · `planned_quantity` · `manufactured_date`(사후 입력이면 필요) · `bom_id` · `notes` |
| 응답 | 201 배치 상세(`PLANNED`) |
| 오류 | 400 포장 배치(범위 밖) · 400 BOM이 그 품목 것이 아님 · 400 활성 BOM 없음 · 400 보낸 `bom_id`가 더 이상 활성이 아님(그사이 버전 변경) |
| 알아둘 점 | 등록만으로는 원료를 예약·차감하지 않습니다. `bom_id`를 생략하면 그 품목의 활성 BOM을 씁니다. BOM 없는 계획은 만들 수 없습니다 |

<a id="inv-batches-preview"></a>
#### GET `/batches/preview/` — 계획 미리 보기

| | |
|---|---|
| 쿼리 | `item_id`(필수) · `quantity`(계획량) · `planned_date` |
| 응답 | 200 BOM 줄마다 소요량·가용량·부족분 + `bom_id`·`bom_version`(적용될 활성 BOM) · 활성 BOM이 없으면 `bom_problem`에 사유 |
| 화면 | 생산지시·실적 — 계획 등록 전 확인 |

<a id="inv-fefo"></a>
#### GET `/batches/fefo/` — 투입 LOT 추천

| | |
|---|---|
| 쿼리 | `item_id`·`quantity`(필수) · `on_date` |
| 응답 | 200 `{item_id, quantity, covered, shortfall, results}` — 사용 가능한 LOT을 소비기한 빠른 순으로, 부족분 |
| 알아둘 점 | 추천일 뿐 실제 투입을 대신하지 않습니다 |

<a id="inv-batch-detail"></a>
#### GET `/batches/{pk}/` — 배치 상세

| | |
|---|---|
| 응답 | 200 배치 상세(위 모양) + `bom_is_active`(연결 BOM이 현재 활성인지) · `active_bom`(`{id, version}` 또는 null) |
| 오류 | 404 |

<a id="inv-batch-start"></a>
#### POST `/batches/{pk}/start/` — 생산 시작

| | |
|---|---|
| 본문 | `staff_id`(필수) · `started_at` · `manufactured_date`(기본 = 시작일, 생산 LOT 번호 기준일) |
| 응답 | 200 배치 상세(`IN_PROGRESS`) |
| 부수 효과 | **같은 트랜잭션에서 CCP-1P·2B·3P 일지 생성**, 생산일지 양식이 설치돼 있으면 생산일지도 |
| 오류 | 400 상태가 계획이 아님 · 400 활성 보류 · 문서 쪽 오류면 시작 전체 취소 |

<a id="inv-allocation"></a>
#### GET `/batches/{pk}/allocation/` — 줄 하나 제안 / POST `/batches/{pk}/bulk-allocation/` — 남은 원료 전체 제안

| | |
|---|---|
| 쿼리(GET) | `bom_line_id`(필수) · `quantity` · `item_id`(대체 원료) |
| 본문(POST) | `lines: [{bom_line_id, quantity, unit, item_id, alternatives}]` |
| 응답 | 200 줄마다 투입할 LOT과 양의 **제안**(아무것도 기록하지 않음) |
| 화면 | **남은 원료 일괄 투입** — 제안을 고친 뒤 `usages`로 등록 |

<a id="inv-usages"></a>
#### POST `/batches/{pk}/usages/` — 원료 투입

| | |
|---|---|
| 본문(한 건) | `lot_id`·`quantity`·`staff_id`·`idempotency_key`(필수) · `bom_line_id`(BOM 밖 투입이면 생략) · `occurred_at` |
| 본문(여러 건) | `entries: [{lot_id, quantity, bom_line_id}]` · `staff_id`·`idempotency_key`(필수) · `expected_quantity` · `expected_bom_line_id` · `expected_lines`(화면이 본 소요량 — 그사이 바뀌었으면 거부) |
| 응답 | 201 배치 상세 |
| 부수 효과 | 투입마다 `PRODUCTION_USE` 수불 기록 → 재고 차감 |
| 오류 | 400 진행 중 배치가 아님·활성 보류·사용할 수 없는 LOT·재고 부족 |

<a id="inv-outputs"></a>
#### POST `/batches/{pk}/outputs/` — 산출

| | |
|---|---|
| 본문 | `quantity`·`staff_id`·`idempotency_key`(필수) · `ea_count`(참고 개수) · `occurred_at` · 첫 산출만 `lot_number`·`expiration_date` |
| 응답 | 201 배치 상세 |
| 부수 효과 | 첫 산출이면 산출 LOT 생성, 이후 산출은 **같은 LOT에 더함** · `PRODUCTION_OUTPUT` 수불 기록 |

<a id="inv-batch-complete"></a>
#### POST `/batches/{pk}/complete/` — 완료

| | |
|---|---|
| 본문 | `staff_id`(필수) · `completed_at` |
| 응답 | 200 배치 상세(`COMPLETED`) |
| 오류 | 400 필수 원료 투입이 빠짐 · 400 산출 없음 · 400 활성 보류 |

<a id="inv-batch-cancel"></a>
#### POST `/batches/{pk}/cancel/` — 취소

| | |
|---|---|
| 본문 | `staff_id`·`reason`(필수) |
| 응답 | 200 배치 상세(`CANCELLED`) |
| 알아둘 점 | 배치는 지우지 않고 취소합니다. 취소 뒤 CCP 일지·생산일지 처리는 아직 정해지지 않았습니다(생산일지는 읽기 전용이 됨) — [남은 작업](../remaining-work.md) |

<a id="inv-batch-switch-bom"></a>
#### POST `/batches/{pk}/switch-bom/` — 이전 BOM 계획을 활성 BOM으로 재지시

| | |
|---|---|
| 본문 | `staff_id`(필수) |
| 응답 | 201 **새** 배치 상세(활성 BOM 기준 `PLANNED`) |
| 오류 | 400 시작 전(`PLANNED`) 계획이 아님 · 이미 활성 BOM 기준 · 활성 BOM 없음 · 404 |
| 알아둘 점 | 한 트랜잭션에서 새 계획 등록 + 기존 계획 취소(둘 다 되거나 둘 다 안 됨). 계획일·계획량·제조일·메모를 이어받고 배치번호는 새로 정하며 원료 배정은 복사하지 않습니다. 취소 사유와 새 배치 감사 이력에 상대 배치번호를 남깁니다 |

### 6. BOM

<a id="inv-boms"></a>
#### GET·POST `/boms/` — 목록·등록 / GET·PATCH `/boms/{pk}/` — 한 버전·수정

| | |
|---|---|
| 쿼리(GET 목록) | `item_id` · `include_inactive`(0/1, 기본 0) |
| 본문(POST·PATCH) | `staff_id` · `item_id`(만드는 품목) · `base_quantity` · `base_unit` · `is_active` · `lines: [{item_id, quantity, unit, alternatives: [item_id …]}]` · `new_version`·`overwrite`(PATCH) · `notes` |
| 응답 | 목록 200 `{results}`(버전 높은 순, 줄 포함, 각 버전에 `open_batch_count` = 계획·진행 중 배치 수) · POST 201 · GET·PATCH 200 |
| 오류 | 409 저장 충돌 — 다른 사용자가 먼저 변경(활성 BOM은 품목당 하나, 새로 고친 뒤 다시) · 400 칸 값 |
| 활성 | 품목당 0~1개(DB 부분 유니크 인덱스). `is_active: true`로 저장·변경하면 같은 품목의 다른 활성 버전은 같은 트랜잭션에서 비활성이 됩니다 |
| 적용일 | `effective_from`은 입력받지 않습니다(보내도 무시). 새 버전은 등록일, 덮어쓰기는 기존 값을 기록합니다 |
| 알아둘 점 | **배치가 쓴 버전은 고칠 수 없고**(DB 트리거) 새 버전으로 저장됩니다. 생산에 연결된 기록의 기준을 보존하기 위해서입니다 |

<a id="inv-bom-delete"></a>
#### POST `/boms/{pk}/delete/` — BOM 지우기

| | |
|---|---|
| 본문 | `staff_id` · `reason`(기본 "BOM 삭제") |
| 응답 | 200 결과 |
| 오류 | 400·409 배치가 쓴 BOM |

### 7. 보류

<a id="inv-holds-get"></a>
#### GET `/holds/` — 보류 목록 / GET `/holds/{pk}/` — 한 건

| | |
|---|---|
| 쿼리(목록) | `open`(1이면 해제 안 된 것만) · `lot_id` · `batch_id` · `parent_hold_id` · `limit`·`offset` |
| 응답 | 200 `{count, results}` · 한 건 — 대상·원인·사유·근거 문서·해제 정보 |

<a id="inv-holds-post"></a>
#### POST `/holds/` — 보류 등록

| | |
|---|---|
| 본문 | `lot_id` **또는** `batch_id`(하나만) · `source_type`(`CCP`·`INCOMING_INSPECTION`·`FINISHED_INSPECTION`·`MANUAL`)·`reason`·`staff_id`(필수) · `source_document_id`(근거 문서 번호) · `held_at` |
| 응답 | 201 보류 |
| 부수 효과 | 배치 보류면 그 배치의 산출 LOT에 전파 보류(`PROPAGATED`)가 생김. 보류 중인 배치는 시작·투입·산출·완료가 막힘 |
| 오류 | 400 LOT·배치를 둘 다 보내거나 안 보냄 · 400 근거가 필요한 원인인데 근거 문서 없음 |
| 화면 | 제조배치 상세 **보류 관리** |
| 알아둘 점 | CCP 이탈이나 문서 결재가 보류를 자동으로 만들지 않습니다(수동) |

<a id="inv-hold-release"></a>
#### POST `/holds/{pk}/release/` — 보류 해제

| | |
|---|---|
| 본문 | `disposition`(`RELEASE`·`REWORK`·`RETURN`·`DISPOSE`)·`reason`·`staff_id`(필수) · `released_at` |
| 응답 | 200 보류(해제됨) |
| 부수 효과 | 배치 보류를 풀면 열린 전파 보류도 같은 처분으로 해제. 다른 사유로 LOT에 따로 건 보류는 남음 |
| 오류 | 400 이미 해제됨(해제된 보류는 DB가 바꾸지 못하게 막음) |
| 알아둘 점 | 처분은 기록일 뿐 재고를 줄이지 않습니다(반품·폐기는 [수불 기록](#inv-outflow)으로) |
