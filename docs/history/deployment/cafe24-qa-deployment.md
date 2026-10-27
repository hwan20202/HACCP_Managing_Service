> 개발 당시 기록입니다. 현재 사용·설치 기준은 [문서 목차](../../README.md)의 전달본과 참고 명세를 확인하세요.

# 카페24 QA 배포 준비 — 2026-10-16

현재 브랜치 `feature/inventory-production`, 기준 커밋 `3f884f9`의 Seeder·배포 구성을 점검하고 필요한 준비만 보완했다. 이 문서의 서버 명령은 **실행 계획**이다. 원격 접속·배포·원격 DB 변경·main 병합은 수행하지 않았다. SSH 비밀번호는 설정 파일에 사용하지 않는다.

## 확인한 환경과 아직 필요한 정보

사용자가 SSH로 확인한 OS는 **Ubuntu 24.04.4 LTS**다. 카페24 상품명, 도메인, 외부 접속 범위, 기존 프록시·서비스·저장 공간·백업 구성은 미확인이다. OS와 root 계정만으로 단독/VPS/매니지드 여부를 확정하지 않는다.

| 확인할 정보 | 배포에 미치는 영향 |
| --- | --- |
| 상품명·서비스 약관/관리 범위 | 장기 실행 프로세스, 패키지 설치, systemd·프록시 설정 가능 여부 |
| 기존 서비스와 80/443 사용 현황 | 기존 Nginx/Caddy를 유지하며 QA 사이트 추가 가능 여부 |
| 도메인·DNS, 접속 허용 범위 | HTTPS 인증서, 호스트/CSRF 설정, 접근 제한 방식 |
| 실제 Python·SQLite 버전, CPU·메모리·디스크 | 프로젝트 실행 가능 여부, 백업/첨부 용량 계획 |
| 영구 디스크 및 스냅샷·외부 백업 | 재배포·서버 재설치·장애 시 데이터 보존 |

카페24 일반 웹호스팅은 PHP/Apache 중심이며 이 Django 장기 실행 구성을 그대로 적용할 대상으로 보지 않는다([공식 안내](https://help.cafe24.com/faq/web-hosting/introduce/setup-management/ai-coding-tools-web-hosting-guide/)). 개발자 VPS는 Ubuntu 24.04·Python 3.12·Nginx 등을 기본 제공하지만, 이것이 현재 상품이라는 근거는 없다. 프로젝트는 **Python 3.14.x, SQLite 3.37 이상**을 사용하므로 기본 Python에 맞춰 버전을 낮추거나 제공 PostgreSQL로 DB를 바꾸지 않는다([개발자 VPS FAQ](https://help.cafe24.com/docs/server-hosting/dev-vps/faq/)). 설치 권한과 버전은 실제 배포 전 확인한다.

## Seeder 점검 결과

실제 구현: `backend/apps/inventory/management/commands/seed_qa_inventory.py`, 참고 자료: `backend/apps/inventory/seed/qa_reference.json`.

| 단계 | 빈 QA DB에서의 누적 결과 | 목적 |
| --- | --- | --- |
| `prepare` (기본) | 품목 24, BOM 3(21행), 입고 28, 기초재고 2, LOT 30, 수불 30, 문서 84, 생산배치 0 | 사람이 입고·생산·문서 작업을 진행할 시작 상태 |
| `run` | 품목 24, BOM 3, 입고 28, LOT 33, 수불 58, 문서 93, 완료 배치 3 | 준비 단계와 생산·경계 시나리오까지 자동 실행 |

수량은 이번 **샘플 없는 새 QA DB** 실측값이다. 기존 로컬 DB에는 예전 샘플·브라우저 거래가 있어 전체 건수가 다르다.

- 실제 자료: 두 BOM 파일의 공통 품목명·코드·약어·선정한 세 제품 BOM. 각 파일 해시·셀/행 출처를 fixture에 기록한다. 대상은 한동 효력환, 녹용분말, 녹용추출분말이며 녹용추출액은 구매분으로 준비한다.
- QA 가정: 기준단위 kg, 입고일·소비기한·수량·공급처·직원·검사 판정·기초재고·산출량. 포장 단위나 원료별 실제 소비기한 정책을 확정한 자료가 아니다.
- `prepare`도 단순 마스터 등록만 하는 명령은 아니다. 반복 입고·날짜 있음/없음·부적합·HOLD·기초재고·구매 반제품을 준비하고, 입고 업무 서비스로 D01~D03 문서를 연결한다.
- `run`은 녹용분말 제조 → 효력환 투입·분할 산출, 구매 추출액 FEFO → 추출분말 제조, 사용 불가 LOT 거부, 기초재고 소진 등을 검증한다. 예상 재고·현재고·수불 기말을 대조한다.
- 실행 전 SQLite backup API로 `db/app-before-qa-*.sqlite3` 백업을 만든다. 적재는 한 DB 트랜잭션에서 실행한다. 첨부까지 포함한 백업은 별도 `project.py backup`을 사용한다.
- 실제 참조 품목 코드를 QA 접두사로 바꾸지 않는다. 직원 `QA_REF`, 공급처 `QA_REF_*`, 거래 멱등키 `QA-REF-*`, BOM 메모·감사 로그·적재 JSON 및 사이트 배너로 식별한다. 운영 데이터와의 분리는 **DB 자체를 분리**해서 보장한다.
- 기존 동일 품목은 코드·이름·단위·분류 등을 대조하고, QA BOM은 수량과 구성까지 확인한 뒤 재사용한다. 확인된 가상 샘플 코드·약어 충돌은 ID/참조를 유지하며 이동하고 감사 로그에 기록한다. 실제 품목 충돌이나 다른 BOM은 덮어쓰지 않는다. 신규 호스팅 QA DB에 기존 거래만 있고 적재 완료 기록이 없으면 혼합 적재를 거부한다.

### 이번 보완

기존에는 DEBUG 개발 설정에서만 허용되었고, 같은 날짜의 거래 키를 재사용하는 방식이었다. 날짜가 바뀌면 추가 묶음이 만들어질 수 있고, 수동 거래 후 재실행 시 초기 예상 재고와 달라 실패할 수 있었다.

이제 `audit_logs`의 `qa_dataset/reference-v1` 완료 기록에 고정 기준일·단계·fixture 해시·LOT ID·출처를 보관한다. 같은 DB에서 다음 날 기본 명령을 실행해도 새 묶음을 만들지 않는다. `prepare` 재실행과 완료 후 `run`은 건너뛰며, 이후 사용자 거래를 보존한다. 다른 날짜 지정/다른 fixture는 거부한다. `prepare → run`은 기존 기준일을 사용한다. 다만 수동 QA로 재고가 변한 뒤 `run`을 추가 실행하면 시나리오 예상값 대조에서 거부될 수 있으므로 자동 시나리오는 **사람이 거래하기 전에** 선택한다.

새 QA 설정은 `DEBUG=False`이며, Seeder는 QA 설정과 `HACCP_QA_SEED_ENABLED=true`가 동시에 있어야 실행된다. production 설정에서는 이 환경변수만 켜도 실행되지 않는다. 개발 설정의 기존 사용은 유지한다. 기존 로컬 DB에 이 기록을 소급 삽입하거나 Seeder를 재실행하지 않았다.

## 배치할 구성

현재 코드의 Caddy → Waitress → Django → SQLite를 유지할 수 있는 서버라면 다음처럼 구성한다. 이미 Nginx가 있다면 교체하지 않고 동등한 QA 가상 호스트를 추가하는 방안을 먼저 검토한다.

```text
브라우저 → HTTPS 프록시 + QA 접근 제한 → 127.0.0.1:8002 Waitress
                                             ↓
                                  /srv/biodot/qa-data/
                                    db/app.sqlite3
                                    uploads/files/...
                                    qa/*.json
                                    backups/...
                                    static/...
운영 앱 → 별도 설정/포트 → /srv/biodot/production-data/
코드와 가상환경: /opt/biodot-qa/current/ (교체 가능한 코드 경로)
비밀 환경 파일: /etc/biodot/qa.env (저장소 밖)
```

경로·계정은 제안값이다. QA 데이터 경로는 절대 경로, 코드 밖, 운영 `HACCP_DATA_DIR`와 겹치지 않게 검사한다. 운영이 별도 서버라면 물리적으로도 분리된다. SQLite는 한 서버의 로컬 영구 디스크에 두며 공유 네트워크 파일시스템이나 여러 서버가 같은 SQLite 파일을 쓰는 구성은 사용하지 않는다. DB 파일뿐 아니라 WAL 사용 디렉터리에도 앱 계정의 쓰기 권한이 필요하다.

QA 서비스는 root 대신 전용 계정으로 실행한다. 예시는 `infra/linux/haccp-qa.service.example`이며 아직 설치하지 않았다. DB·첨부·백업·비밀 파일은 앱 계정으로 제한하고, 프록시에는 `static/` 읽기와 필요한 상위 디렉터리 통과 권한만 준다. QA의 collectstatic은 공개 정적 파일 0644·디렉터리 0755로 생성하고, 첨부는 기존 0600 설정을 유지한다. 실제 계정·소유권·상위 디렉터리 권한은 서버에서 확인해야 한다.

`uploads/`를 프록시의 공개 정적 경로로 만들지 않는다. 파일은 기존 파일 API로 제공한다. DB·첨부·양식은 코드 배포로 복사되지 않으며 이 영구 디렉터리에 남는다. 호스팅 상품의 백업 제공 여부는 미확인이므로 DB+첨부 백업의 별도 보관·복구 검증이 필요하다.

현재 앱은 직원 선택 기반이며 역할별 로그인/권한이 완성되지 않았다. 공개 전 접속 정책을 결정해야 한다. `infra/caddy/Caddyfile.qa`는 전체 HTML/API/정적/파일 경로 앞에 QA 비밀번호 인증을 두는 **선택 가능한 준비안**이다. SSH 비밀번호를 재사용하지 않는다. 도메인·인증·프록시 배치는 아직 확정/적용하지 않았고 Caddy 바이너리 검증도 미수행이다. 기존 프록시가 있으면 그 프록시에서 접근 제한을 적용한다. 앱 포트는 외부에 직접 노출하지 않는다.

## 최초 QA 준비 순서

아래는 상품·권한·경로 확인과 별도 배포 승인 후 서버에서 실행할 순서다. OS 전체 설치 명령이나 기존 웹서버 변경 명령은 포함하지 않는다. 코드 배포 위치와 Python 3.14 가상환경·의존성 설치가 준비되어 있다고 전제한다.

1. `.env.qa.example`을 `/etc/biodot/qa.env`로 복사하고 생성한 비밀키, 실제 도메인·CSRF origin, **QA 전용 데이터 경로**를 설정한다. 예시 도메인과 해시를 그대로 사용하지 않는다. 환경 파일은 앱 계정만 읽도록 한다. Seeder 허용값은 기본 `false`로 둔다.
2. 앱 계정이 QA 데이터 디렉터리만 쓸 수 있는지, 운영 경로와 다른지 확인한다. 서비스를 아직 외부에 열지 않는다.
3. 프로젝트 루트에서 다음을 실행한다. `HACCP_ENV_FILE`을 실제 경로로 고정하므로 명령이 개발 `.env`를 읽지 않는다.

```bash
export HACCP_ENV_FILE=/etc/biodot/qa.env

# 디렉터리 준비 → migrate. 기존 DB·첨부는 보존.
.venv/bin/python scripts/project.py --env-file "$HACCP_ENV_FILE" --qa init

# 샘플 직원/문서/수불 없이 기본 양식만 등록. 기존 양식 내용·활성 상태 보존.
.venv/bin/python backend/manage.py install_document_templates --settings=config.settings.qa

# 최초 한 번, 이 명령에만 적재를 허용. 기본은 사람이 진행할 시작 재고.
HACCP_QA_SEED_ENABLED=true .venv/bin/python backend/manage.py seed_qa_inventory --stage prepare --settings=config.settings.qa

# 정적 파일 수집. DB·업로드 디렉터리는 지우지 않음.
.venv/bin/python scripts/project.py --env-file "$HACCP_ENV_FILE" --qa collectstatic

# 배포 설정 점검. 운영 HTTPS/쿠키 설정 포함.
.venv/bin/python backend/manage.py check --deploy --settings=config.settings.qa
```

완료된 시나리오도 필요하면 사람이 거래하기 전에 다음 명령을 **명시적으로 추가**한다. 첫 명령부터 `--stage run`을 골라도 내부에서 준비 단계까지 실행한다. 일반 배포 스크립트·systemd 시작 명령에는 넣지 않는다.

```bash
HACCP_QA_SEED_ENABLED=true .venv/bin/python backend/manage.py seed_qa_inventory --stage run --settings=config.settings.qa
```

4. `qa/QA-REF-<기준일>-prepare.json` 또는 `run.json`에서 출처·가정·LOT별 예상/실제 잔량을 확인한다. 문서 양식은 D01~D03, CCP-1P/2B/3P, D10~D12다. 새 등록 명령은 기존 비활성 양식을 자동 활성화하지 않고 오류로 알린다. `seed_dev_p4`나 `seed_master --sample`로 대신하지 않는다.
5. `HACCP_QA_SEED_ENABLED=false`인 서비스 환경으로 Waitress를 실행하고, 확인한 프록시에 HTTPS와 합의한 접근 제한을 적용한다. 서비스 예시 실행문은 다음이다. 이 문서는 프로세스를 원격 시작하지 않았다.

```bash
.venv/bin/python scripts/project.py --env-file "$HACCP_ENV_FILE" --qa serve --port 8002
```

Caddy를 새로 쓰기로 결정한 경우에만 인증 해시·환경변수를 준비하고 다음 예시를 실제 도메인으로 바꾼다. 이미 80/443을 쓰는 웹서버와 동시에 실행하지 않는다. Caddy 명령의 site/bind/upstream 옵션은 환경 파일 값보다 우선하므로 명시한다.

```bash
.venv/bin/python scripts/project.py --env-file "$HACCP_ENV_FILE" --qa caddy --binary /usr/bin/caddy --site qa.example.com --bind 0.0.0.0 --upstream-port 8002
```

6. 외부 브라우저에서 QA 배너, 접근 제한, 입고→D01~D03, 생산 시작→CCP, 투입·산출, 문서 작성·결재·파일 업로드/다운로드, 재고·수불을 확인한다. QA 입고 버튼은 QA 설정에서만 표시하고 실제 입고 API를 호출한다. 소비기한 유무는 빈 선택으로 시작한다. 개발 콘솔·개발 API는 활성화하지 않는다.

## 이후 코드 배포와 별도 재준비

일반 재배포는 QA 쓰기 중지 → DB+첨부 백업 → 의존성/코드 반영 → `--qa init`(migrate) → `--qa collectstatic` → 서비스 재시작 → 확인 순서다. **Seeder는 재배포 단계에 없다.** 백업은 쓰기가 중지된 후 다음 명령을 사용한다.

```bash
.venv/bin/python scripts/project.py --env-file "$HACCP_ENV_FILE" --qa backup --writes-stopped
```

백업 위치는 QA 데이터의 `backups/<시각>/`이며 SQLite 사본·uploads.zip·버전 정보가 포함된다. 같은 디스크의 사본만으로 서버 장애에 대비할 수 없으므로 별도 저장소에도 보관한다. 새 양식 버전 도입 때만 양식 등록을 별도로 수행하며 기존 내용을 덮어쓰지 않는다. 코드 checkout·재배포 때 `/srv/biodot/qa-data`와 환경 파일을 교체하지 않는다.

QA를 처음부터 다시 준비하려면 기존 앱을 멈추고 DB+첨부를 백업한 뒤, **새 빈 QA 전용 디렉터리와 별도 환경 파일**을 준비해 위 최초 순서를 명시적으로 실행한다. 이전 DB·첨부는 보존하고 확인 후 서비스 경로를 전환한다. 같은 DB에 flush/reset/선별 삭제를 실행하는 명령은 제공하지 않았다. 날짜 옵션을 바꾸어 우회 적재하지 않는다. 운영 설정에서는 QA 적재가 거부된다.

## 검증 근거와 남은 범위

기존 보고서의 이미 완료된 범위를 재사용했다.

| 근거 | 확인된 범위 | 이번에 다시 하지 않은 것 |
| --- | --- | --- |
| `qa-data-source-review-20261015.md` | 두 참고본 공통 품목·BOM 선정, 충돌/불명확 데이터 배제 | 자료 전체를 재해석해 최종 마스터 확정 |
| `qa-inventory-document-20261015.md` | 기존 입고·문서 연결, 메뉴 및 오류 경로 검증 | 동일 기본 흐름 전체 수동 반복 |
| `qa-integrated-inventory-20261016.md` | 3개 서비스 시나리오, 브라우저 제조배치 1건, 예상/현재고/수불 대조, 통합 화면 16항목·가용재고 조회 10항목 | 기존 로컬 DB의 생산 시나리오 재실행 |

이번 추가 검증은 `qa-hosted-preparation-20261016.md`에 기록했다. 실제 카페24 Ubuntu, systemd, 파일 권한, 프록시 인증·HTTPS·DNS, 재부팅, 외부 접속, 실제 파일 업로드와 결재까지의 서버 통합 QA는 아직 미검증이다. 31개 건너뛴 동시성/성능 검사를 모두 수행했다고 보지 않는다. 역할 권한·CCP 이탈 자동 HOLD·취소 문서 정책·P11/P12 등 기존 미구현 범위도 이번 배포 준비로 완료된 것은 아니다.
