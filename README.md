# HACCP Managing Service

사내 HACCP 관리 시스템의 초기 개발 기반입니다. 현재는 기존 시제품 화면, 연결 확인 화면(`/test/`), 헬스체크만 있습니다. 로그인·업무 데이터의 서버 저장은 [보완 계획](#8-알려진-문제점과-보완-계획)에 있습니다.

## 1. 기술 스택

| 구성요소 | 버전 | 역할 |
|---|---|---|
| HTML·CSS·바닐라 JS | - | 화면 (빌드 도구 없음) |
| Python | 3.14.x | 실행 언어 |
| Django | 5.2.18 LTS | 웹 프레임워크 (URL·화면·ORM·마이그레이션 내장) |
| SQLite | Python 내장, 3.37 이상 (STRICT 테이블) | DB (별도 서버 불필요) |
| Waitress | 3.0.2 | 운영용 서버 (Windows 지원) |
| Caddy | 2.11.7 | 운영용 HTTPS·정적 파일 서버 |
| Ruff | 0.16.10 | 코드 검사·형식 정리 |

## 2. 구조

```text
개발: 브라우저 → Django 개발 서버(127.0.0.1:8000) → SQLite
운영: 브라우저 → Caddy(HTTPS) → Waitress(127.0.0.1:8001) → Django → SQLite
```

```text
backend/
  manage.py            Django 명령 실행 파일
  config/settings/     설정: base(공통) · development · production · test
  config/urls.py       주소 → 뷰 연결
  apps/core/           시제품·테스트 화면, 헬스체크
  apps/<업무앱>/        models.py(DB 테이블), views.py(요청 처리), migrations/(DB 변경 기록)
frontend/templates/    HTML
frontend/static/       CSS·JS·이미지
scripts/project.py     초기화·실행·검사 명령 모음
data/                  DB·원본 자료·로그·백업 (README와 시제품 data.js만 Git 포함)
docs/                  배포·구조·검증 문서
```

## 3. 시작하기

모든 명령은 프로젝트 최상위 폴더에서 실행합니다. 저장소를 받으려면 Git이 필요합니다. Node.js·Caddy는 개발 서버 실행에 필요하지 않습니다.

### 3-1. Python 3.14 설치 확인

| OS | 확인 명령 | 정상 결과 |
|---|---|---|
| Windows | `py -3.14 --version` | `Python 3.14.x` |
| macOS / Ubuntu | `python3.14 --version` | `Python 3.14.x` |

정상 결과가 아니면 설치합니다.

- **Windows**: Microsoft Store에서 "Python install manager"를 설치합니다. 새 PowerShell에서 `py install 3.14`를 실행합니다. `py install`에서 `can't open file` 오류가 나면 기존 런처와 충돌했을 수 있습니다. `pymanager install 3.14`를 사용하거나 [공식 문제 해결 안내](https://docs.python.org/3.14/using/windows.html#troubleshooting)에 따라 런처를 정리한 뒤 위 확인 명령을 다시 실행합니다.
- **macOS**: Homebrew가 설치되어 있다면 `brew install python@3.14`를 실행합니다. 또는 [Python 공식 설치 파일](https://www.python.org/downloads/macos/)을 사용합니다.
- **Ubuntu**: 저장소에서 Python 3.14를 제공하면 `sudo apt install python3.14 python3.14-venv`를 실행합니다. 제공하지 않으면 [uv 설치 안내](https://docs.astral.sh/uv/getting-started/installation/)에 따라 uv를 먼저 설치하고 `uv python install 3.14`를 실행합니다. 새 터미널에서 `python3.14 --version`을 다시 확인합니다. [uv의 Python 설치 안내](https://docs.astral.sh/uv/guides/install-python/)를 참고하며 시스템 기본 Python은 교체하지 않습니다.

### 3-2. 처음 한 번

```bash
git clone <저장소 주소>
cd HACCP_Managing_Service
```

`git clone`은 기본 브랜치를 받습니다. 아직 `main`에 병합하지 않은 변경을 시험하려면 `git switch <브랜치명>`으로 해당 작업 브랜치를 선택합니다. 가상환경은 OS마다 새로 만들며 다른 PC에서 복사하지 않습니다.

Windows (PowerShell):

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements/dev.txt
.\.venv\Scripts\python.exe scripts/project.py init
.\.venv\Scripts\python.exe scripts/project.py run
```

macOS / Ubuntu:

```bash
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements/dev.txt
.venv/bin/python scripts/project.py init
.venv/bin/python scripts/project.py run
```

- `init`은 `.env`(비밀키 자동 생성), `data/` 폴더, DB를 만듭니다. 다시 실행해도 기존 자료는 유지됩니다.
- [http://127.0.0.1:8000/](http://127.0.0.1:8000/)에 시제품 화면, [/test/](http://127.0.0.1:8000/test/)에 `정상 연결`이 보이면 완료입니다.
- 기본 `HACCP_DATA_DIR=data`에서는 Git에 포함된 시제품 데이터(`data.js`)를 바로 사용합니다. 데이터 경로를 바꿨다면 [자료 안내](data/README.md)에 따라 복사합니다. 실제 자료이므로 수정하지 말고, 저장소는 비공개로 유지합니다.
- `/test/`의 정상 연결은 서버·DB 준비 상태를 뜻합니다. 업무 화면에서 입력한 내용의 서버 저장·PC 간 공유는 아직 구현되지 않았습니다.

### 3-3. 매일 작업 순서

아래부터 `python`은 가상환경 Python입니다. Windows는 `.\.venv\Scripts\python.exe`, macOS / Ubuntu는 `.venv/bin/python`으로 바꿔 씁니다.

```bash
git pull
python -m pip install -r requirements/dev.txt   # 바뀐 의존성 반영
python scripts/project.py init                  # 새 마이그레이션 반영
python scripts/project.py check                 # 커밋 전 검사
python scripts/project.py run                   # 개발 서버 (Ctrl+C로 종료)
```

개발 서버 실행 중에 검사하려면 별도 터미널을 사용합니다. 새 작업의 브랜치 생성·PR 규칙은 [협업 안내](CONTRIBUTING.md)를 따릅니다.

## 4. 개발 명령어

| 목적 | 명령 |
|---|---|
| 개발 서버 (다른 포트) | `python scripts/project.py run --port 8010` |
| 마이그레이션 생성 | `python backend/manage.py makemigrations` |
| 마이그레이션 적용 | `python backend/manage.py migrate` |
| 마이그레이션 상태 | `python backend/manage.py showmigrations` |
| 설정 검사 | `python backend/manage.py check` |
| Django 셸 | `python backend/manage.py shell` |
| DB 셸 (`sqlite3` 프로그램 필요) | `python backend/manage.py dbshell` |
| 정적 파일 수집 (실제 운영 환경) | `python scripts/project.py --env-file .env.production --production collectstatic` |

마이그레이션 명령은 `init`으로 초기화한 뒤 사용합니다. 운영 명령은 [배포 안내](docs/deployment.md)에 따라 `.env.production`을 준비한 상태를 전제로 합니다.

### 모델을 바꿀 때

`models.py` 수정 → `makemigrations` → `migrate` → 생성된 `migrations/` 파일을 코드와 함께 커밋합니다.

### 업무 앱을 추가할 때 (예: inventory)

1. `mkdir backend/apps/inventory`
2. `python backend/manage.py startapp inventory backend/apps/inventory`
3. `backend/apps/inventory/apps.py`의 `name`을 `"apps.inventory"`로 변경
4. `backend/config/settings/base.py`의 `INSTALLED_APPS`에 `"apps.inventory"` 추가
5. `python -m ruff check --fix .`로 자동 생성 파일의 미사용 import를 정리하고 `python -m ruff format .` 실행

## 5. 테스트·검사

| 목적 | 명령 |
|---|---|
| 전체 검사 (커밋 전) | `python scripts/project.py check` |
| 서버 띄워 HTTP 확인 | `python scripts/smoke_process.py` |
| 테스트 클래스 하나 | `python backend/manage.py test apps.core.tests.LiveTests --settings=config.settings.test` |
| 자동 수정 | `python -m ruff check --fix .` 다음 `python -m ruff format .` |

- 테스트에는 항상 `--settings=config.settings.test`를 붙입니다. 메모리 DB를 써서 내 DB는 바뀌지 않습니다.
- 현재 테스트 중 400·404·405·503 로그는 오류 상황을 일부러 재현한 것입니다. 테스트 결과의 `OK`와 명령의 정상 종료를 확인합니다.
- 전체 검사에는 Django 테스트와 자동검사 서버의 DNS 회귀 테스트가 포함됩니다. DNS 회귀 테스트는 임시 로컬 포트를 사용합니다.
- HTTP 검사는 서버 응답·일부 정적 파일·헬스체크를 확인합니다. 준비 안내 화면도 통과할 수 있으므로, 시제품 데이터 로딩과 업무 화면은 브라우저에서도 확인합니다.
- HTTP 검사용 서버는 macOS CI의 역방향 DNS 지연을 피하도록 `scripts/smoke_server.py`를 사용합니다. 실패 시 서버 로그·마지막 연결 오류를 확인하며, 시작 단계가 멈추면 15초 후 호출 위치를 출력합니다.

## 6. 설정

| `.env` 항목 | 용도 |
|---|---|
| `DJANGO_SECRET_KEY` | 비밀키. `init`이 생성. 공유 금지 |
| `DJANGO_ALLOWED_HOSTS` | 접속 허용 호스트 |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | 허용 출처 (`http(s)://호스트:포트`) |
| `HACCP_DATA_DIR` | 시제품 자료·DB·업로드·로그·백업·수집한 정적 파일의 루트 (기본 `data`) |
| `DJANGO_HTTPS_ENABLED` | 운영 HTTPS 사용 여부 |

어떤 설정 파일을 쓸지는 `DJANGO_SETTINGS_MODULE`이 정합니다.

| 실행 | 설정 |
|---|---|
| `manage.py` | development (기본) |
| `manage.py ... --settings=config.settings.test` | test |
| `wsgi.py` 직접 사용 | production (환경변수가 없을 때 기본값) |
| `project.py serve` | 항상 production |
| `project.py`의 `init`, `check`, `collectstatic`, `caddy`, `backup` | development. `--production`을 붙이면 production |

- 값의 우선순위: 프로세스 환경변수 → 선택한 환경 파일 → 코드 기본값
- `project.py`는 기본적으로 `.env`를 읽습니다. `--production`만으로 `.env.production`을 선택하지 않으므로, 실제 운영에서는 명령 앞에 `--env-file .env.production --production`을 붙입니다. `manage.py`에서 환경 파일을 바꾸려면 `HACCP_ENV_FILE` 환경변수를 지정합니다.
- 환경 파일 경로와 `HACCP_DATA_DIR`의 상대 경로는 프로젝트 최상위 폴더 기준입니다.
- 운영 구성(Caddy·Waitress·Windows 서비스)은 [배포 안내](docs/deployment.md)를 따릅니다.

## 7. 자주 겪는 문제

| 증상 | 해결 |
|---|---|
| `That port is already in use` | `run --port 8010` |
| `This project is tested with Python 3.14` | `.venv` 삭제 후 Python 3.14로 다시 생성 |
| `ModuleNotFoundError` | 가상환경 Python을 사용 중인지 확인하고 `python -m pip install -r requirements/dev.txt` 실행 |
| `unable to open database file` | `init` 실행 |
| `/health/ready/`가 503 | 서버 로그 확인. 미적용 마이그레이션은 `init`으로 반영하고, 계속 실패하면 데이터 경로·DB 접근 권한·필수 테이블 확인 |
| `/`에 "시제품 데이터가…" 안내 | `git pull`. `HACCP_DATA_DIR`을 바꿨다면 `data.js`를 같은 경로 구조로 복사 |
| 기준서 PDF가 404 | PDF는 Git에 없음. `HACCP_DATA_DIR/reference/setup_standard/기타가공품 기준서-250831.pdf`에 배치 (기본 루트는 `data/`) |
| 개발 DB 초기화 | 서버 종료 → 필요한 DB 백업 → `HACCP_DATA_DIR/db/app.sqlite3` 삭제 → `init`. 지정한 DB의 기록이 모두 삭제됨 |

## 8. 알려진 문제점과 보완 계획

| 문제 | 영향 | 보완 단계 |
|---|---|---|
| 로그인·권한 없음 | 사내망 누구나 데이터 열람 | 2 |
| 업무 데이터 서버 저장 없음 | 화면 변경은 메모리·`localStorage`에만 남음 | 3 |
| 실제 자료 `data.js`가 Git에 포함 | 저장소 접근자가 열람 가능. 나중에 파일을 삭제해도 이전 커밋에는 남음 | 1 (비공개 확인), 3 (DB로 대체) |
| SQLite 동시 쓰기 설정(WAL) 없음 | 저장 기능 추가 후 잠금 오류 가능 | 1 |
| HTTPS 운영 시 직접 헬스체크 301, 실제 접속자 IP 미전달 | Waitress의 HTTP 주소를 감시하면 리다이렉트됨. Django는 프록시 IP를 받음 | 1 |
| 정적 파일 버전 관리 없음 | 배포 후 이전 JS·CSS가 남을 수 있음 | 4 |
| 백업 수동, 복구 명령 없음 | 백업 누락·복구 지연 | 4 |
| macOS CI의 서버 시작 확인 실패 | DNS 지연을 주입해 동일 증상 재현 후 자동검사 서버 수정. 로컬 검증 통과, 수정본의 GitHub CI 재실행 필요 | 1 |

| 단계 | 작업 |
|---|---|
| 1. 기반 정비 | 저장소 비공개 유지, 저장 기능 도입 전 SQLite WAL 검토, 헬스체크·프록시 IP 처리, macOS CI 수정 검증 |
| 2. 보안 | 로그인·권한, 인증 기능과 관련 마이그레이션 도입 전 User 모델 결정, API 방식 결정, 감사 로그 |
| 3. 업무 기능 | 업무 앱별 모델, 엑셀 이관, `data.js`를 DB 데이터로 대체 |
| 4. 운영 | Windows 서비스 검증, 정적 파일 버전 관리, 자동 백업·복구 훈련 |

수정 전 CI는 `7cb7bb9`에서도 Windows·Ubuntu 통과, macOS 실패를 확인했습니다. 실제 확인 범위와 실행 링크는 [검증 기록](docs/verification.md)에 있습니다. 현재는 `contenttypes` 마이그레이션만 사용하며, 인증 앱을 추가할 때 사용자 모델과 의존 관계를 먼저 설계합니다.

## 9. 관련 문서

- [배포 안내](docs/deployment.md): 운영 서버·Windows 서비스·HTTPS·백업
- [구조 안내](docs/architecture.md): 구조와 확장 기준
- [협업 안내](CONTRIBUTING.md): 브랜치·PR·DB 변경 규칙
- [검증 기록](docs/verification.md): 검증 환경과 결과
- [자료 안내](data/README.md): `data/` 폴더 구성
