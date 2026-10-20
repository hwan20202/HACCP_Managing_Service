# 샌드박스 검증과 Windows 11 배포

카페24 Ubuntu에서 별도 QA 사이트를 준비하는 경우 [카페24 QA 배포 준비](cafe24-qa-deployment.md)를 먼저 확인합니다. 해당 가이드는 QA DB·첨부 영구 저장, 명시적 최초 적재, 이후 코드 배포를 구분합니다.

개발 명령은 README에 있습니다. 여기서는 **Caddy → Waitress → Django → SQLite** 구성을 다룹니다. 기본 설정은 모두 로컬 접속만 허용하며, 아래 운영 단계에서 실제 주소와 HTTPS를 설정합니다.

## 1. 같은 PC에서 운영 구성 시험

README의 `init`을 마친 상태에서 진행합니다. 이 시험은 `.env`의 `DJANGO_HTTPS_ENABLED=false`와 로컬 HTTP를 사용합니다. **외부 사용자에게 제공할 실제 운영 설정과 구분**합니다.

[Caddy 2.11.7 공식 릴리스](https://github.com/caddyserver/caddy/releases/tag/v2.11.7)에서 OS·CPU에 맞는 실행 파일을 받습니다. 릴리스의 체크섬 파일은 SHA-512이며 배포 파일과 비교할 수 있습니다. 프로젝트 안에 `tools/caddy`(macOS·Ubuntu) 또는 `tools/caddy.exe`(Windows)로 둡니다. 바이너리는 Git에서 제외합니다.

### macOS / Ubuntu

먼저 정적 파일을 수집합니다.

```bash
.venv/bin/python scripts/project.py --production collectstatic
```

터미널 A:

```bash
.venv/bin/python scripts/project.py serve
```

터미널 B:

```bash
.venv/bin/python scripts/project.py caddy --binary ./tools/caddy
```

터미널 C:

```bash
.venv/bin/python scripts/project.py smoke --url http://127.0.0.1:8080
```

### Windows / PowerShell

```powershell
.\.venv\Scripts\python.exe scripts/project.py --production collectstatic
```

각각 다른 터미널에서 실행합니다.

```powershell
# 터미널 A
.\.venv\Scripts\python.exe scripts/project.py serve

# 터미널 B
.\.venv\Scripts\python.exe scripts/project.py caddy --binary .\tools\caddy.exe

# 터미널 C
.\.venv\Scripts\python.exe scripts/project.py smoke --url http://127.0.0.1:8080
```

[http://127.0.0.1:8080](http://127.0.0.1:8080)에서 확인합니다. Waitress는 `127.0.0.1:8001`에서 Django만 실행하고, Caddy는 `127.0.0.1:8080`에서 화면·파일 요청을 받습니다. Waitress 주소에서 CSS가 제공되지 않는 것은 의도된 구성입니다. 개발·시험 프로세스 종료는 각 터미널에서 `Ctrl+C`입니다.

Ubuntu 샌드박스에서도 동일한 Python 명령과 Caddyfile을 사용합니다. 서비스 관리자, 인증서, 파일 권한은 OS별로 다르므로 Ubuntu 시험만으로 Windows 운영 검증을 대체하지 않습니다.

## 2. Windows 11 운영 준비

아래 예시는 코드 폴더가 `C:\HACCP`, 실행 데이터가 `C:\HACCPData`인 경우입니다. 다른 경로를 사용하면 명령과 환경 설정을 해당 경로에 맞춥니다. 초기 업무 화면을 사용하려면 Git에 포함된 `C:\HACCP\data\legacy-prototype\src\js\data.js`를 `C:\HACCPData\legacy-prototype\src\js\data.js`로 복사합니다. 기준서 열람을 사용하려면 별도로 전달받은 PDF도 데이터 폴더에 배치합니다. 자세한 위치는 [자료 안내](../data/README.md)를 참고하세요. 엑셀 원본은 배포에 필요하지 않습니다.

1. 운영 PC에 Python 3.14를 설치합니다. 서비스 계정도 실행할 수 있도록 **모든 사용자용 설치 경로**를 권합니다. 사용자 개인 프로필 안에 설치한 Python은 서비스 계정 접근 권한을 별도로 확인해야 합니다.
2. 소스만 복사하고 운영 PC에서 `.venv`를 새로 생성합니다. `.venv`는 Mac·Ubuntu에서 복사하지 않습니다.
3. 프로젝트 루트에서 다음을 실행합니다.

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements/production.txt
.\.venv\Scripts\python.exe scripts/project.py --env-file .env.production --production init
```

`.env.production`이 없으면 예시에서 새 비밀키를 생성하여 만듭니다. `.env.production`을 열어 다음 항목을 실제 환경에 맞춥니다.

`--production`은 Django 설정 모듈을 선택합니다. 환경 파일은 별도 옵션이므로 실제 운영 명령에서는 `--env-file .env.production`도 지정해야 합니다. 생략하면 이 문서 1절의 로컬 시험처럼 `.env`를 사용합니다.

```dotenv
DJANGO_ALLOWED_HOSTS=haccp.company.example
DJANGO_CSRF_TRUSTED_ORIGINS=https://haccp.company.example
DJANGO_HTTPS_ENABLED=true
HACCP_DATA_DIR=C:/HACCPData
```

`haccp.company.example`은 설명용 이름입니다. 회사에서 사용할 실제 이름과 DNS를 설정해야 합니다. `DJANGO_SECRET_KEY`는 생성한 값을 유지하고 공개하지 않습니다. 데이터 경로를 변경한 경우 다시 `init`을 실행합니다.

```powershell
.\.venv\Scripts\python.exe scripts/project.py --env-file .env.production --production init
.\.venv\Scripts\python.exe scripts/project.py --env-file .env.production --production collectstatic
```

배포 설정 검사는 환경 파일을 지정하여 실행합니다.

```powershell
$env:HACCP_ENV_FILE = '.env.production'
.\.venv\Scripts\python.exe backend/manage.py check --deploy --settings=config.settings.production
Remove-Item Env:HACCP_ENV_FILE
```

위 HTTPS 설정으로 `check --deploy`를 실행하면 `security.W005`, `security.W021` 경고가 나옵니다. 회사의 다른 하위 도메인에 HTTPS를 강제하거나 브라우저 HSTS preload 정책을 자동 적용하지 않도록 한 선택입니다. 회사 도메인 전체 정책을 확정한 뒤 적용 여부를 결정합니다. 로컬 HTTP 시험 설정에서는 HTTPS 관련 경고가 추가로 발생합니다. 다른 오류·경고는 배포 전에 확인합니다.

### HTTPS와 사내 주소

- 공개적으로 검증 가능한 회사 도메인: 회사 네트워크와 인증서 발급 조건에 맞춰 Caddy의 자동 HTTPS를 사용합니다.
- 내부 DNS·사내 인증서 사용: `infra/caddy/Caddyfile`의 사이트 블록에 회사 인증서를 지정하거나 `tls internal`을 추가합니다. `tls internal`을 쓴다면 **접속하는 직원 PC와 서버의 신뢰 저장소에 Caddy CA 인증서를 등록**해야 합니다. 서비스 계정이 만든 CA와 개인 계정이 만든 CA는 다를 수 있습니다.
- 서버 앞에 기존 HTTPS 프록시가 있는 환경은 현재 로컬 Caddy 구성과 별도로 접속·전달 헤더 정책을 맞춰야 합니다.

공식 설명: [Caddy HTTPS](https://caddyserver.com/docs/automatic-https), [Windows 서비스](https://caddyserver.com/docs/running#windows-service).

Windows 방화벽에서는 실제로 사용할 443 포트를 필요한 사내 접속 범위에 허용합니다. 80 포트는 HTTP 리다이렉트나 인증서 발급 방식에서 필요할 때 허용합니다. Waitress의 8001 포트는 로컬 전용으로 유지합니다.

HTTPS 운영 시 헬스체크는 Caddy를 거친 실제 HTTPS 주소의 `/health/live/`와 `/health/ready/`를 확인합니다. 현재 설정에서는 Waitress의 HTTP 주소로 직접 요청하면 HTTPS로 리다이렉트됩니다. 잘못된 Host 값으로 요청하면 400이므로 등록한 호스트 이름도 함께 확인합니다.

## 3. Windows 서비스 등록

이 단계는 **대상 Windows PC의 관리자 PowerShell**에서 수행합니다. 현재 개발 Mac에서 실행하거나 설치하지 않습니다.

1. Caddy 실행 파일을 `tools/caddy.exe`에 둡니다.
2. [WinSW 2.12.0](https://github.com/winsw/winsw/releases/tag/v2.12.0)의 대상 PC에 맞는 실행 파일을 다운로드합니다. 예를 들어 x64 PC에서는 x64 바이너리를 사용합니다.
3. 환경 파일을 준비한 뒤 서비스 XML을 생성합니다.

```powershell
.\.venv\Scripts\python.exe scripts/windows_services.py --site haccp.company.example
```

이 명령은 서비스 설치 없이 `tools/services/haccp-app.xml`, `haccp-proxy.xml`만 생성합니다. 생성된 파일에는 실제 절대 경로, 자동 시작, 장애 시 10초 후 재시작, 로그 순환 설정이 들어 있습니다.

4. WinSW 실행 파일을 두 번 복사해서 같은 폴더에 `haccp-app.exe`, `haccp-proxy.exe`로 둡니다.
5. 서비스는 기본적으로 **LocalService** 계정을 사용합니다. 이 계정에 프로젝트 읽기·실행과 실행 데이터 수정 권한을 부여합니다. 아래 경로는 예시이며 자신의 설치 경로를 사용하세요.

```powershell
icacls C:\HACCP /grant '*S-1-5-19:(OI)(CI)RX' /T
icacls C:\HACCPData /grant '*S-1-5-19:(OI)(CI)M' /T
```

서비스가 사용하는 Python 설치 폴더에도 읽기·실행 권한이 있어야 합니다. 실제 비밀 설정과 업로드 자료의 다른 사용자 접근 권한은 회사 정책에 맞게 관리합니다.

6. 서비스를 설치하고 시작합니다.

```powershell
.\tools\services\haccp-app.exe install
.\tools\services\haccp-proxy.exe install
.\tools\services\haccp-app.exe start
.\tools\services\haccp-proxy.exe start
.\tools\services\haccp-app.exe status
.\tools\services\haccp-proxy.exe status
```

접속 주소에서 초기 업무 화면·`/test/` 연결 상태·기준서 열람·헬스체크를 확인한 뒤, PC를 재부팅하고 **Windows 로그인 전에도 서비스에 접속되는지** 확인합니다. 로그는 `HACCP_DATA_DIR/logs/services`에 저장됩니다. Caddy 인증서·상태는 `HACCP_DATA_DIR/caddy`, 자동 저장 설정은 `HACCP_DATA_DIR/config/caddy`에 모읍니다. 인증서 폴더도 별도 백업 대상에 포함하세요.

운영 PC는 전원 연결 상태의 자동 절전을 해제하고, Windows 업데이트 재부팅 시간을 업무 일정과 맞춥니다. 시스템 업데이트 자체를 비활성화하지 않습니다.

중지·제거:

```powershell
.\tools\services\haccp-proxy.exe stop
.\tools\services\haccp-app.exe stop
# 제거가 필요한 경우에만 실행
.\tools\services\haccp-proxy.exe uninstall
.\tools\services\haccp-app.exe uninstall
```

### 3.1 점검표 주기 문서 자동 생성 (문서 영역)

일반위생관리 점검표(D10)·공정별 이물관리 점검표(D12)는 평일 매일, 방충방서점검표(D11)는 매주 문서가 필요합니다. 규칙은 `backend/apps/doc_requirements/periodic_rules.json`(요일·시작일·켜기/끄기)에 있고, 아래 명령이 **오늘** 문서를 만듭니다(이미 있으면 그대로). 하루 한 번, 작업 시작 전에 Windows 작업 스케줄러로 실행합니다.

1. 실행 파일 `tools\periodic.cmd`를 만듭니다(경로·staff id는 실제 값으로). `--actor`는 "만든 사람"으로 기록될 직원 id입니다.

```bat
@echo off
cd /d C:\HACCP
set HACCP_ENV_FILE=.env.production
.venv\Scripts\python.exe backend\manage.py make_periodic_documents --actor 1 --settings=config.settings.production >> C:\HACCPData\logs\periodic.log 2>&1
```

2. 관리자 PowerShell에서 평일 오전 6시 작업으로 등록합니다(서비스와 같은 LocalService 계정).

```powershell
schtasks /Create /TN "HACCP 주기 문서" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 06:00 /RU "NT AUTHORITY\LOCAL SERVICE" /TR "C:\HACCP\tools\periodic.cmd"
schtasks /Run /TN "HACCP 주기 문서"      # 한 번 실행해 로그 확인
```

- 종료 코드: 0 정상 · 1 일부 줄 실패(양식 비활성 등, 나머지는 만들어짐) · 2 입력·직원·규칙 파일 오류(아무것도 안 만듦). 로그의 마지막 줄이 `합계: 만듦 n · 이미 있음 n · 대상 아님 n · 실패 n`입니다.
- PC가 꺼져 있어 빠진 날은 자동으로 채우지 않습니다. 필요하면 직접 보충합니다(최대 31일, 미래 날짜 불가): `make_periodic_documents --actor 1 --from 2026-10-01 --to 2026-10-14`.
- 규칙 파일을 바꾸면 재시작 없이 다음 실행부터 반영됩니다. 운영 시작일이 정해지면 `start_date`를 고쳐 커밋합니다. 다른 경로의 규칙 파일은 `.env.production`의 `HACCP_PERIODIC_RULES`로 지정합니다.
- 화면에서도 같은 일을 할 수 있게 됩니다(작성 요구 화면의 [주기 문서 만들기], 날짜를 골라 하나만 만드는 [새 문서] — 문서 영역 C4 S5 화면 구현 뒤).

### 역할 설정(결재선)

상신하면 결재선이 역할 설정 파일로 자동으로 만들어집니다(HACCP팀장·양식별 담당자·양식별 결재 칸). 기본 파일 `backend/apps/staff/roles.json`에는 가상 개발 직원(DEV-001~005)만 있으므로 운영에서는 실제 직원 코드로 만든 파일을 지정합니다.

1. `backend/apps/staff/roles.json`을 `C:\HACCPData\roles.json`으로 복사해 직원 코드(`staff_code`)를 고칩니다. 형식: `{"version": 1, "haccp_leaders": [코드...], "forms": {"양식유형": {"owners": [코드...], "slots": "owner" | "owner_leader" | "leader", "labels": {"owner": "작성자"}}}}`(`labels`는 선택).
2. `.env.production`에 `HACCP_ROLES_FILE=C:/HACCPData/roles.json`을 넣습니다.
3. 서비스를 다시 시작합니다(설정 파일은 서버 시작 뒤 처음 쓸 때 한 번 읽습니다 — 파일을 바꾸면 재시작해야 반영). 직원 등록·비활성(직원 마스터 가져오기)은 재시작 없이 바로 반영됩니다 — 비활성 직원은 역할에서 빠지고, 칸을 처리할 사람이 0명이 되면 그 양식은 상신이 막힙니다.
4. `backend\manage.py check --settings=config.settings.production`으로 확인합니다. 형식 오류는 Error(`document_workflow.E002` — 이 상태로는 모든 상신이 409로 막힘), 없는 코드·비활성 직원·처리할 사람이 없는 칸은 Warning(`W002`)입니다. 화면에서는 [역할 보기](`GET /api/v1/roles`)에서 같은 내용을 봅니다.
5. 역할 파일은 아래 5장 백업 명령에 들어가지 않습니다. 고치기 전에 같은 폴더에 날짜를 붙인 사본(예: `roles.2026-10-20.json`)을 남기고, 별도 백업에 포함합니다. 회차마다 결재 후보·처리한 사람은 DB에 저장되므로 지난 결재 기록은 DB 백업으로 남습니다.
6. 이 기능의 DB 변경(결재 칸 표 다시 만들기, `approvals` 0003)은 적용 전에 5장 백업을 먼저 합니다. 0003을 되돌리는 마이그레이션은 역할 칸이 있는 DB에서는 실패하므로, 되돌리기는 백업 복구로 합니다.

## 4. 코드 업데이트

1. 서비스를 중지하고 아래 방법으로 DB·업로드를 백업합니다.
2. 소스를 업데이트하고 가상환경에 고정된 운영 의존성을 설치합니다.
3. `.env.production`과 `HACCP_DATA_DIR`을 유지한 상태로 `init`, `collectstatic`을 실행합니다.
4. 소스나 Python 경로가 바뀌었다면 서비스 XML을 다시 생성합니다.
5. 서비스를 시작하고 실제 접속 주소의 상태 및 주요 동작을 확인합니다.

프론트엔드 JS/CSS를 수정한 경우에도 `collectstatic`을 다시 실행합니다.

## 5. DB·파일 백업과 복구

DB와 첨부파일이 같은 시점을 나타내도록 **앱 서비스를 중지해 쓰기를 멈춘 상태**에서 실행합니다.

```powershell
.\tools\services\haccp-app.exe stop
.\.venv\Scripts\python.exe scripts/project.py --env-file .env.production --production backup --writes-stopped
.\tools\services\haccp-app.exe start
```

명령은 SQLite backup API로 일관된 DB 복사본을 만들고 업로드 파일을 ZIP으로 보관합니다. 결과는 `HACCP_DATA_DIR/backups/<UTC시각>/`의 `app.sqlite3`, `uploads.zip`, `manifest.json`입니다. 이 디렉터리를 다른 디스크나 사내 백업 저장소에도 복사해야 운영 PC 장애에 대비할 수 있습니다.

문서 첨부 파일(시험성적서·원산지 증빙, PDF·JPG·PNG 20MB 이하)은 `HACCP_DATA_DIR/uploads/files/YYYY/MM/`에 무작위 이름으로 저장되고 원래 이름은 DB에만 있으므로, DB와 `uploads.zip`은 항상 같은 백업 시점의 것을 함께 복구합니다. Caddy의 요청 본문 상한(`infra/caddy/Caddyfile`의 `max_size 30MB`)은 20MB 파일과 요청 머리말을 받을 수 있도록 그대로 둡니다. 시제품의 메모리·브라우저 `localStorage` 데이터는 서버 백업 대상이 아닙니다.

`.env.production`, 역할 설정 파일(`HACCP_ROLES_FILE`), Caddy 인증서·상태, 시제품 데이터와 `data/reference` 원본은 이 명령에 포함되지 않습니다. 필요한 자료는 접근을 제한한 별도 백업으로 보관합니다.

복구 순서:

1. 앱 서비스를 중지합니다.
2. 현재 `db/`와 `uploads/`를 별도 이름으로 보존합니다. 실행 중인 DB 파일 위에 덮어쓰지 않습니다.
3. 복구할 `app.sqlite3`를 `HACCP_DATA_DIR/db/app.sqlite3`로 배치합니다.
4. **빈** `HACCP_DATA_DIR/uploads/`에 같은 백업의 `uploads.zip`을 풉니다.
5. 서비스 계정의 파일 권한을 확인하고, 백업과 호환되는 코드에서 `init`을 실행한 뒤 서비스를 시작합니다.
6. `/health/ready/`, 초기 업무 화면과 `/test/`를 확인합니다.

## 6. 운영 범위

현재 로그인·계정·Django 관리자 기능은 없습니다. 문서 첨부 파일은 `/api/v1/files/<id>`로 제공되며 계정 구분 없이 접근할 수 있으므로 사내망 밖에 노출하지 않습니다. 초기 업무 화면은 시제품 상태이며 서버 DB에 업무 데이터를 저장하지 않습니다. 지정한 시제품 데이터와 기준서는 접속한 사용자에게 제공됩니다. 업무 저장·파일 관리·데이터 이관은 후속 개발 범위입니다.

SQLite는 운영 PC 로컬 디스크에 두고 앱 인스턴스 하나를 기준으로 운영합니다. 샌드박스와 운영이 같은 DB 파일을 공유하지 않습니다.
