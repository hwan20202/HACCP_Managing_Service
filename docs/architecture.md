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

프론트엔드와 서버는 같은 출처를 사용합니다. 별도 Node 서버나 빌드 과정은 없습니다. HTML은 `frontend/templates`, 브라우저 코드는 `frontend/static`에 둡니다. 업무 시제품은 `prototype/`, 연결 확인 화면은 `system-test/`로 구분합니다.

## 백엔드

- `backend/config/settings/base.py`: 경로·앱·DB·로깅 공통 설정
- `backend/config/settings/development.py`: 로컬 개발 설정
- `backend/config/settings/production.py`: 비밀키·허용 호스트 검증과 HTTPS 설정
- `backend/config/settings/test.py`: 메모리 DB와 테스트용 설정
- `backend/apps/core`: 초기 화면·테스트 화면·헬스체크·지정 시제품 자료 제공

계정·로그인·세션·권한·Django 관리자·첨부파일 앱은 제거했습니다. Django의 `contenttypes`는 기본 DB 메타데이터로 유지하며, 현재 DB에는 계정 테이블이나 업무 테이블이 없습니다. 준비 상태 검사는 SQLite 연결과 마이그레이션·필수 테이블을 확인합니다.

업무 기능은 요구사항을 확정하면서 `inventory`, `production`, `quality` 등 별도 앱으로 추가합니다. 새 업무 JSON API는 `/api/v1/` 아래에 두고, 헬스체크는 `/health/`를 유지합니다.

## 시제품과 데이터

기존 HTML·CSS·기능 JavaScript를 `frontend/`에 복사했습니다. 앞으로 화면을 수정하는 위치는 이 실행 사본이며 `data/legacy-prototype`의 원본은 보존합니다. 화면은 기존 전역 변수 `HACCP_DATA`와 일부 브라우저 `localStorage`를 사용합니다. 업무 데이터의 서버 저장·동기화는 아직 없습니다.

실제 데이터는 `HACCP_DATA_DIR/legacy-prototype/src/js/data.js`, PDF는 `HACCP_DATA_DIR/reference/setup_standard/`의 지정 파일을 읽습니다. 초기 개발 테스트용 `data.js`는 Git에 포함하므로 기본 데이터 경로에서는 저장소 복제 후 초기 화면을 사용할 수 있습니다. PDF는 별도 전달합니다. 원본 자료를 서버 DB로 자동 이관하지 않습니다. 데이터 경로를 변경하고 `data.js`를 배치하지 않은 경우에는 초기 화면에 준비 안내를 표시하며, `/test/`와 서버 검증은 계속 동작합니다.

자료 제공은 위 두 경로에 한정하며 임의 파일 경로나 디렉터리 목록을 제공하지 않습니다. PDF만 같은 출처의 iframe에 표시할 수 있도록 허용합니다. 계정 기능이 없으므로 지정 시제품 자료에는 로그인 제한이 없습니다.

SQLite는 운영 PC의 로컬 디스크에 둡니다. 개발자마다 자신의 DB를 생성하며 네트워크 공유 폴더나 동기화 드라이브의 DB를 동시에 사용하지 않습니다. `uploads/`는 후속 파일 기능을 위한 예약 폴더입니다.

## 설정의 경계

프로세스 환경변수 → 지정한 환경 파일 → 코드 기본값 순서입니다. `manage.py`는 `HACCP_ENV_FILE`로 환경 파일을 선택합니다. 프로젝트 도구는 `--env-file`로 선택하며 생략하면 `.env`를 사용합니다. `--production`은 Django 설정 모듈만 선택하고 환경 파일을 바꾸지 않습니다. `serve`는 항상 운영 설정을 사용하고 `127.0.0.1`에만 바인딩합니다.

Caddy가 받은 HTTP/HTTPS 정보를 덮어써 전달하고 Waitress는 로컬 프록시만 신뢰합니다. 정적 파일 루트는 `HACCP_DATA_DIR/static`입니다. `collectstatic`은 이 생성 폴더를 비우고 현재 정적 파일을 다시 수집하므로 원본 자료를 넣지 않습니다. 실제 HTTPS 배포 전 호스트·DNS·인증서와 사내 접속 범위를 설정합니다.
