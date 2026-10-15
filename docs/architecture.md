# 구조와 확장 기준

## 요청 흐름

- 개발: 브라우저 → Django 개발 서버
- 샌드박스·운영: 브라우저 → Caddy → Waitress → Django → SQLite
- `/`: 기존 HACCP 시제품
- `/test/`: 서버·DB 연결 확인
- `/health/live/`, `/health/ready/`: 상태 확인 JSON
- `/static/`: 프론트엔드 코드·이미지. 운영에서는 Caddy가 수집된 파일 제공
- `/prototype/data.js`: 지정한 시제품 데이터 파일
- `/setup_standard/기타가공품 기준서-250831.pdf`: 기존 화면이 사용하는 기준서 한 개
- `/api/v1/`: 업무 JSON API(문서·결재). 오류 응답은 `{code, message, details}`로 통일
- `/dev/`, `/api/dev/`: 개발 콘솔(개발 설정에서 `HACCP_DEV_CONSOLE`이 켜졌을 때만 등록, 운영 설정에서는 경로 자체가 없음)

프론트엔드와 서버는 같은 출처를 사용합니다. 별도 Node 서버나 빌드 과정은 없습니다. HTML은 `frontend/templates`, 브라우저 코드는 `frontend/static`에 둡니다. 업무 시제품은 `prototype/`, 연결 확인 화면은 `system-test/`로 구분합니다.

HTTP 자동 검사는 `scripts/smoke_process.py`가 `scripts/smoke_server.py`를 자식 프로세스로 실행합니다. 이 서버는 Django의 정적 파일 제공·시작 검사를 유지하면서, 로컬 IP에 대한 역방향 DNS 조회만 생략합니다. macOS CI 러너의 DNS 지연을 피하기 위한 자동검사 전용 구성입니다. 평소 개발용 `project.py run`은 기본 Django 개발 서버를 사용합니다.

## 백엔드

- `backend/config/settings/base.py`: 경로·앱·DB·로깅 공통 설정
- `backend/config/settings/development.py`: 로컬 개발 설정
- `backend/config/settings/production.py`: 비밀키·허용 호스트 검증과 HTTPS 설정
- `backend/config/settings/test.py`: 메모리 DB와 테스트용 설정
- `backend/apps/core`: 초기 화면·테스트 화면·헬스체크·지정 시제품 자료 제공, 공통 오류 응답, 처리 단계 기록(trace)
- `backend/apps/inventory`: 생산·수불 코어(입고·LOT·재고·원료수불대장)와 `/api/v1/inventory/` API. 테이블은 `sql/0001_core.sql`(코어)·`sql/0002_production.sql`(BOM·제조배치·투입·산출)이 만들고 모델은 `managed=False`. 결정 사항은 [inventory-decisions.md](inventory-decisions.md), 문서 앱 연동 명세는 [inventory-document-interface.md](inventory-document-interface.md)
- `backend/apps/staff`: 사람 연결 모듈(테이블 없음, 앱 등록 안 함). 사람은 수불 `staff`(`inventory.Staff`). 현재 사용자는 `X-Staff-Id` 헤더로 받고 없거나 비활성(`is_active = 0`)인 id는 거부
- `backend/apps/documents`: 문서 도메인 — 양식 조회, 문서 작성·조회·수정(바뀐 부분만, 버전 확인)·논리 삭제, 문서 생명주기 전이
- `backend/apps/approvals`: 결재 도메인 — 결재 요청(회차)·칸(병렬, 칸마다 결재자 1명), 승인·반려 판정, 결재함·이력 조회
- `backend/apps/document_workflow`: 문서 워크플로우 — 상신(결재선 지정)·승인·반려에서 두 도메인을 한 트랜잭션으로 묶음. 테이블 없음
- `backend/apps/doc_requirements`: 작성 요구 — 수불·생산이 입고 등록·생산 시작 때 같은 트랜잭션에서 부르는 함수(`require_for_lot`·`require_for_batch`)로 필요한 문서를 만들고, LOT·배치별 연결 문서를 조회. 수불·생산 값은 뷰(`v_doc_incoming_lot`·`v_doc_batch`)로만 읽음. 테이블 없음. 문서 영역(`documents`·`approvals`·`document_workflow`·`doc_requirements`)의 결정 사항은 [document-decisions.md](document-decisions.md), 생산·수불 앱 연동 명세는 [document-inventory-interface.md](document-inventory-interface.md)
- `backend/apps/devtools`, `backend/apps/devserver`: 개발 전용(개발 콘솔 API, 개발 시드 명령 `seed_dev_workflow`·`seed_dev_p4`, 정적 파일 no-cache 개발 서버). 개발용 입고 LOT은 수불 입고 서비스로, 생산 배치는 수불 생산 서비스가 들어오기 전까지 개발 전용 INSERT로 만든다(`devtools/inventory_dev.py`). 운영 설정에는 등록하지 않음

계정·로그인·세션·권한·Django 관리자·첨부파일 앱은 제거했습니다. Django의 `contenttypes`는 기본 DB 메타데이터로 유지하며, 계정 테이블은 없습니다. 문서 영역의 업무 테이블은 아래 11개입니다(Django 마이그레이션 `documents 0001·0002`·`approvals 0001`, 수불 `inventory 0002`에 의존). 사람·LOT·배치·품목은 수불 테이블(`staff`·`lots`·`production_batches`·`items`)을 참조합니다.

| 테이블 | 소유 앱 | 내용 |
|---|---|---|
| `document_template` | documents | 양식(유형·버전·섹션 정의 JSON). 버전의 내용은 만든 뒤 바꾸지 않음 |
| `document` | documents | 문서 기본 정보·상태(작성중/작성완료/결재중/승인/반려/정정 중)·작성 요구 키(`record_key`)·버전·논리 삭제 |
| `doc_section` | documents | 문서 섹션 행(값 JSON, 기록 시각·기록자) |
| `document_ref` | documents | 문서 ↔ 업무 대상(LOT·생산 배치+공정·품목) 연결. 수불 테이블에 DB FK |
| `file`, `document_file` | documents | 첨부 파일과 문서 연결(기능은 후속) |
| `deviation_action`, `deviation_checker` | documents | 이탈 개선조치와 확인자 |
| `document_correction` | documents | 승인 문서의 정정 기록(시작자·사유·정정 전 작성완료 기록, 열린 정정은 문서마다 1개) |
| `approval_request` | approvals | 결재 회차(상태, 상신 시점 문서 스냅샷, 결재함 요약) |
| `approval` | approvals | 결재 칸(결재자, 대기/승인/반려/미처리 종료, 의견) |

준비 상태 검사는 SQLite 연결과 마이그레이션·필수 테이블(위 테이블 포함)을 확인합니다.

업무 기능은 도메인 단위의 별도 앱으로 추가합니다. 도메인 앱끼리는 서로 import하지 않고(DB의 FK는 허용), 여러 도메인을 묶는 처리는 워크플로우 앱이 각 도메인의 공개 서비스 함수만 호출해 수행합니다. 이 경계는 각 앱의 테스트(import 검사)로 확인합니다. 상태 변경은 서비스 함수 안에서 조건부 UPDATE로 검사와 잠금을 함께 처리합니다. 새 업무 JSON API는 `/api/v1/` 아래에 두고, 헬스체크는 `/health/`를 유지합니다.

## 시제품과 데이터

기존 HTML·CSS·기능 JavaScript를 `frontend/`에 복사했습니다. 앞으로 화면을 수정하는 위치는 이 실행 사본이며 `data/legacy-prototype`의 원본은 보존합니다. 시제품 화면은 기존 전역 변수 `HACCP_DATA`와 일부 브라우저 `localStorage`를 사용하며, 시제품 데이터의 서버 저장·동기화는 아직 없습니다.

문서·결재 기능은 서버 DB에 저장하며, 화면은 정식 화면으로 옮기기 전까지 사이드바의 "개발 검증 (임시)" 탭(`frontend/static/temp-entry/`)으로 들어갑니다. 이 탭은 `HACCP_TEMP_ENTRY`로 켜고 끄며(개발 기본 켜짐, 운영 기본 꺼짐), 시제품에 손댄 곳에는 `[임시 진입점 Tn]` 주석을 달아 정식 메뉴로 옮길 때 되돌릴 수 있게 했습니다. 임시 화면은 시제품 모듈·`HACCP_DATA`·`localStorage`를 쓰지 않고 `/api/v1/`만 사용합니다. 문서함·결재함 메뉴는 `HACCP_DOC_MENU`(`dev` = 개발 검증 섹션, `haccp` = HACCP 관리 섹션 맨 위)로 자리를 정하며, `haccp`이면 `HACCP_TEMP_ENTRY`와 관계없이 보입니다(화면 id `doc-box`·`approval-box`, 예전 `temp-doc`·`temp-approval`도 같은 화면). 문서함의 마지막 탭만 브라우저 `localStorage`에 기억합니다.

실제 데이터는 `HACCP_DATA_DIR/legacy-prototype/src/js/data.js`, PDF는 `HACCP_DATA_DIR/reference/setup_standard/`의 지정 파일을 읽습니다. 초기 개발 테스트용 `data.js`는 Git에 포함하므로 기본 데이터 경로에서는 저장소 복제 후 초기 화면을 사용할 수 있습니다. PDF는 별도 전달합니다. 원본 자료를 서버 DB로 자동 이관하지 않습니다. 데이터 경로를 변경하고 `data.js`를 배치하지 않은 경우에는 초기 화면에 준비 안내를 표시하며, `/test/`와 서버 검증은 계속 동작합니다.

자료 제공은 위 두 경로에 한정하며 임의 파일 경로나 디렉터리 목록을 제공하지 않습니다. PDF만 같은 출처의 iframe에 표시할 수 있도록 허용합니다. 계정 기능이 없으므로 지정 시제품 자료에는 로그인 제한이 없습니다.

SQLite는 운영 PC의 로컬 디스크에 둡니다. 개발자마다 자신의 DB를 생성하며 네트워크 공유 폴더나 동기화 드라이브의 DB를 동시에 사용하지 않습니다. `uploads/files/`에는 문서 첨부 파일이 저장됩니다(DB에는 경로·원래 이름·해시만).

## 설정의 경계

프로세스 환경변수 → 지정한 환경 파일 → 코드 기본값 순서입니다. `manage.py`는 `HACCP_ENV_FILE`로 환경 파일을 선택합니다. 프로젝트 도구는 `--env-file`로 선택하며 생략하면 `.env`를 사용합니다. `--production`은 Django 설정 모듈만 선택하고 환경 파일을 바꾸지 않습니다. `serve`는 항상 운영 설정을 사용하고 `127.0.0.1`에만 바인딩합니다.

Caddy가 받은 HTTP/HTTPS 정보를 덮어써 전달하고 Waitress는 로컬 프록시만 신뢰합니다. 정적 파일 루트는 `HACCP_DATA_DIR/static`입니다. `collectstatic`은 이 생성 폴더를 비우고 현재 정적 파일을 다시 수집하므로 원본 자료를 넣지 않습니다. 실제 HTTPS 배포 전 호스트·DNS·인증서와 사내 접속 범위를 설정합니다.
