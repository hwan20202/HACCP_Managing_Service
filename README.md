# HACCP Managing Service

사내 HACCP 시스템의 초기 개발 기반입니다. **HTML·CSS·바닐라 JavaScript / Python 3.14 / Django 5.2 LTS / SQLite**를 사용합니다.

개발은 Windows·macOS, 샌드박스는 Ubuntu, 최종 운영은 **Windows 11 + Waitress + Caddy**를 기준으로 합니다. GitHub 연결 없이 로컬에서 실행할 수 있습니다.

현재 구현 범위:

- 초기 화면: 기존 HACCP 시제품 (`legacy-prototype`)
- 별도 `/test/` 시스템 연결 확인 화면과 헬스체크
- 시제품 데이터·기준서 PDF 연결
- 외부 폰트 다운로드 없이 OS 기본 글꼴로 표시하는 업무·인쇄 화면
- 개발·운영 설정 분리, 자료 폴더 정리, 백업 명령
- 운영용 Waitress·Caddy 설정과 Windows 서비스 생성 도구

로그인·계정·권한·Django 관리자 및 관리자 첨부파일 기능은 제거했습니다. 기존 업무 화면은 시제품의 JavaScript 데이터와 일부 브라우저 저장소를 사용하며, 업무 데이터의 DB 저장·엑셀 이관은 아직 구현하지 않았습니다.

## 1. 준비

- Python **3.14.x**: [공식 다운로드](https://www.python.org/downloads/)
- 모든 명령은 이 README가 있는 **프로젝트 최상위 폴더**에서 실행합니다.
- Node.js, npm, Docker, Caddy는 **개발 서버 실행에 필요하지 않습니다**.
- 아래 명령은 가상환경의 Python을 직접 사용하므로 PowerShell 실행 정책 변경이나 가상환경 활성화가 필요하지 않습니다.

### Windows 11 / PowerShell

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements/dev.txt
.\.venv\Scripts\python.exe scripts/project.py init
.\.venv\Scripts\python.exe scripts/project.py check
.\.venv\Scripts\python.exe scripts/project.py run
```

### macOS / Ubuntu

먼저 `python3.14 --version`이 동작해야 합니다. Ubuntu 기본 `python3`가 다른 버전이면 Python 3.14를 별도로 설치하세요. 운영체제의 기본 Python을 교체할 필요는 없습니다.

```bash
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements/dev.txt
.venv/bin/python scripts/project.py init
.venv/bin/python scripts/project.py check
.venv/bin/python scripts/project.py run
```

`init`은 고유 비밀키가 들어간 `.env`, 데이터 폴더, SQLite 테이블을 만듭니다. 다시 실행해도 기존 `.env`와 자료를 덮어쓰지 않고 필요한 마이그레이션만 적용합니다. 가상환경은 OS마다 따로 만들며 복사하지 않습니다.

## 2. 실행 확인

서버 실행 상태에서 [초기 업무 화면](http://127.0.0.1:8000/)을 엽니다. 왼쪽 아래 **시스템 연결 확인**을 누르면 [테스트 화면](http://127.0.0.1:8000/test/)으로 이동합니다. 테스트 화면의 **서비스 응답 / 데이터 연결**이 모두 `정상 연결`이면 됩니다. 서버 종료는 `Ctrl+C`입니다.

| 주소 | 정상 결과 |
|---|---|
| `/` | 기존 HACCP 시제품 화면 (데이터가 없으면 준비 안내) |
| `/test/` | 서버·SQLite 연결 상태 화면 |
| `/health/live/` | HTTP 200, `{"status":"ok","service":"haccp"}` |
| `/health/ready/` | HTTP 200, `{"status":"ok","database":"ok"}` |

DB 연결 실패, 미적용 마이그레이션, 필수 테이블 누락 시 `/health/ready/`는 **HTTP 503**을 반환합니다. 내부 경로나 오류 상세는 응답에 포함하지 않습니다.

다른 터미널에서도 프로젝트 폴더로 이동한 뒤 실제 HTTP 확인을 실행할 수 있습니다.

```powershell
# Windows
.\.venv\Scripts\python.exe scripts/project.py smoke
```

```bash
# macOS / Ubuntu
.venv/bin/python scripts/project.py smoke
```

초기 화면·테스트 화면·CSS·JS·헬스체크와 제거된 관리자 및 비공개 경로 차단을 검사합니다. 포트 8000을 이미 쓰고 있으면 `run --port 8010`, `smoke --url http://127.0.0.1:8010`처럼 맞춰 실행하세요.

## 3. 기존 시제품과 데이터

이 작업 폴더에는 기존 자료가 이미 있어 바로 초기 화면이 표시됩니다. 화면 수정은 `frontend/templates/index.html`과 `frontend/static/prototype/`에서 합니다. `data/legacy-prototype/`의 원본은 그대로 보존합니다.

새로 코드를 받은 팀원은 원본 자료가 Git에 포함되지 않으므로 담당자에게 다음 파일을 별도로 받아 **HACCP_DATA_DIR** 아래에 같은 구조로 배치합니다. 기본 데이터 폴더는 프로젝트의 `data/`입니다.

- `legacy-prototype/src/js/data.js`: 초기 화면의 기존 데이터 (필수)
- `reference/setup_standard/기타가공품 기준서-250831.pdf`: 기존 기준서 열람용 (선택)

데이터가 없어도 서버 초기화·헬스체크·`/test/`는 정상 실행되며, `/`에는 데이터 준비 안내가 표시됩니다. 서버는 지정한 데이터 파일과 기준서 1개만 제공하며 `data/` 전체나 엑셀·백업 파일은 공개하지 않습니다.

시제품의 변경 사항은 대부분 메모리에 있고, CCP 일지 일부는 해당 브라우저의 `localStorage`에 저장됩니다. 서버 DB에 저장하거나 여러 PC가 공유하는 기능은 후속 개발 범위입니다. `/test/`의 정상 연결은 서버와 DB의 준비 상태를 의미하며 업무 저장 완료를 의미하지 않습니다.

## 4. 폴더 구조

```text
frontend/                  HTML, CSS, 바닐라 JavaScript
backend/
  config/                  URL, 공통·개발·운영·테스트 설정
  apps/core/               시제품·테스트 화면·지정 자료 제공·헬스체크
infra/
  caddy/                   공통 HTTPS·정적 파일·프록시 설정
  windows/                 Windows 서비스 안내
scripts/                   OS 공통 초기화·실행·검증·백업 도구
requirements/              버전 고정된 공통·개발·운영 의존성
docs/                      구조·배포·검증 문서
data/                      원본 자료·기존 시제품·DB·업로드·로그·백업
.github/                   향후 GitHub 연결 후 사용할 자동 검사
```

**코드와 분리할 자료는 `data/` 한 곳에 모았습니다.** 기준서·엑셀 원본은 `data/reference/`, 기존 HTML/JS 시제품과 백업은 `data/legacy-prototype/`에 있습니다. 원본 파일 이름과 내용은 보존했습니다. 자세한 위치는 [자료 안내](data/README.md)를 참고하세요.

`data/README.md`를 제외한 `data/` 내용과 `.env`, `.venv`, 다운로드한 실행 파일은 Git 추적 대상에서 제외됩니다. 팀원은 같은 코드를 내려받아 `init`으로 자신의 DB를 생성합니다. GitHub에는 **마이그레이션 파일을 공유**하며 운영 DB와 사내 원본 자료는 올리지 않습니다.

## 5. 설정과 운영 실행

| 설정 | 용도 |
|---|---|
| `DJANGO_SECRET_KEY` | 자동 생성하는 비밀키 |
| `DJANGO_ALLOWED_HOSTS` | 접속을 허용할 호스트 이름·IP (포트 제외) |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | 허용할 출처 (`https://호스트`, 필요 시 포트 포함) |
| `HACCP_DATA_DIR` | DB·업로드·로그·백업·수집한 정적 파일의 루트 |
| `DJANGO_HTTPS_ENABLED` | 운영 HTTPS 리다이렉트와 쿠키 설정 |

환경 파일의 상대 경로와 `HACCP_DATA_DIR`의 상대 경로는 프로젝트 루트 기준입니다. 이미 설정된 프로세스 환경변수가 `.env`보다 우선합니다. 다른 환경 파일을 사용하려면 공통 옵션을 명령 **앞에** 적습니다.

```text
python scripts/project.py --env-file .env.production --production init
```

운영 설정에서는 비밀키가 없거나 짧은 경우, 허용 호스트가 없거나 `*`인 경우 실행을 거부합니다. `.env` 기본값의 HTTP 설정은 **로컬 검증용**입니다.

Waitress + Caddy의 로컬 검증, Windows 서비스 설치, HTTPS, 백업·복구는 [배포 안내](docs/deployment.md)를 따릅니다. 개발용 `run`은 직원들이 상시 사용하는 운영 서버로 쓰지 않습니다.

## 6. 검증과 협업

`scripts/project.py check`는 의존성, 코드 형식, Django 설정, 마이그레이션 누락, 자동 테스트를 확인합니다. 테스트는 별도의 임시 DB·자료 폴더를 사용합니다. 의도적으로 실패 응답을 발생시키는 테스트에서 400·404·405·503 로그가 보일 수 있으며 마지막 `OK`를 확인하세요.

- 실제 확인한 환경과 결과: [검증 기록](docs/verification.md)
- 역할과 확장 기준: [구조 안내](docs/architecture.md)
- 작업 규칙: [협업 안내](CONTRIBUTING.md)
- GitHub 연결 후 Windows·macOS·Ubuntu 자동 검사: `.github/workflows/ci.yml`

로컬 Git 저장소의 `main` 브랜치에서 개발 기반을 관리합니다. GitHub 원격 저장소 연결·push는 수행하지 않았습니다.
