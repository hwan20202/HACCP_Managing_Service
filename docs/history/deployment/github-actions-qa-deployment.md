> 개발 당시 기록입니다. 현재 사용·설치 기준은 [문서 목차](../../README.md)의 전달본과 참고 명세를 확인하세요.

# GitHub Actions → 카페24 QA 코드 배포

## 반영 순서

`feature/qa-deployment-workflow` PR → main 병합 → 수동 배포 검증 → main 자동 배포 활성화 순서로 진행한다. main에 직접 커밋할 필요가 없다. 원격 서버에 이 문서의 작업을 실행한 상태는 아니다.

기존 `Project checks` workflow에 배포 job을 추가했다. PR·작업 브랜치는 검사만 하며 서버에 접속하지 않는다. Windows·macOS·Ubuntu 검사, HTTP smoke, JS 검사가 모두 통과해야 QA 배포 job이 실행된다.

## 김정환: GitHub 설정 확인

[Actions Secrets](https://github.com/hwan20202/HACCP_Managing_Service/settings/secrets/actions):

| Secret | 값 |
| --- | --- |
| `QA_SSH_PRIVATE_KEY` | 배포 전용 OpenSSH 개인키 전체. 암호구 없는 키, BEGIN/END 포함 |

[Actions Variables](https://github.com/hwan20202/HACCP_Managing_Service/settings/variables/actions):

| Variable | 값 |
| --- | --- |
| `QA_SSH_HOST` | `175.118.124.141` |
| `QA_SSH_PORT` | `22` |
| `QA_SSH_USER` | `root` — 현재 서버 재배포 스크립트 기준 |
| `QA_SSH_KNOWN_HOSTS` | 별도 경로로 지문을 확인한 서버 호스트 공개키 한 줄. `175.118.124.141 ssh-ed25519 AAAA…` 형식 |
| `QA_AUTO_DEPLOY` | 최초에는 미등록 또는 `false`. 수동 검증 완료 후 `true` |

개인키만 Secrets, 나머지는 위 이름으로 Variables에 등록해야 한다. 비기본 SSH 포트라면 known_hosts는 `[호스트]:포트 ...` 형식이다. SSH 비밀번호와 웹 QA 비밀번호는 사용하지 않는다. 호스트 키 검증은 끄지 않는다.

현재 키는 root 권한으로 배포한다. workflow 수정과 main 반영 권한을 관리한다. 배포 계정 분리는 별도 전환 작업이다.

## 오주영: 최초 수동 실행

1. 위 설정을 확인하고 PR을 main에 병합한다. `QA_AUTO_DEPLOY`를 아직 켜지 않았다면 병합만으로 배포되지 않는다.
2. [Actions](https://github.com/hwan20202/HACCP_Managing_Service/actions) → **Project checks → Run workflow → Branch: main**을 선택한다.
3. 검사 job들 이후 **Deploy Cafe24 QA (code only)** 결과를 확인한다.
4. 웹 QA에서 기존 입고·생산·문서·첨부가 보존됐는지 확인하고, 정적 파일 새로고침 후 화면을 확인한다.
5. 완료되면 김정환이 `QA_AUTO_DEPLOY=true`를 설정한다. 이후 main push/PR 병합은 같은 검사·배포 흐름을 자동 실행한다.

수동 실행도 main만 배포한다. 검사를 기다리는 사이 main이 더 진행되면 구버전 실행은 생략하며 최신 main 실행을 사용한다. 다른 브랜치를 선택하면 배포 job은 건너뛴다.

수동 실행은 workflow가 기본 브랜치에 있어야 가능하다. [GitHub 수동 실행 문법](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#onworkflow_dispatch).

## 자동 배포가 하는 일

1. 검사한 커밋의 `git archive`를 생성하고 SHA-256을 계산한다.
2. 검증한 SSH 호스트 키와 배포 키로 접속해 `/root/biodot-actions-실행ID-시도번호/`에 전송한다.
3. 서버 스크립트를 **`--code-only --branch main`**으로 실행한다. 기존의 `package_cafe24_qa.py`는 사용하지 않는다.
4. 설치된 코드와 migration·SQL·의존성·Python 버전을 비교하고, 모델 migration 누락·DB 미적용 migration 여부를 확인한다. 해당 변경이 있으면 서비스를 중지하기 전에 실패한다.
5. 격리 DB로 서버 회귀 검사를 수행한다. 이 검사는 기존 QA DB를 초기화하지 않는다.
6. 기존 `biodot-qa`·`caddy` 서비스를 중지하고 DB·첨부·설정을 백업한다.
7. DB migration 여부를 다시 검사하고, 버전별 별도 정적 파일 디렉터리에 collectstatic을 실행한다. migrate 적용·Seeder·초기 양식 적재는 실행하지 않는다.
8. 코드와 정적 파일 경로를 전환하고 재시작한다. 내부 ready 응답과 외부 HTTPS 인증 차단(401)을 확인한다.
9. 커밋·백업·정적 파일 위치를 서버에 기록한다. 배포 실패 시 이전 코드·환경설정·정적 파일 경로로 복구하며 데이터는 덮어쓰지 않는다.

배포는 한 번에 한 건만 실행하고 새 push 때문에 진행 중인 배포를 취소하지 않는다. 서버의 배포 잠금도 유지한다. 배포에는 짧은 중단 시간이 있다. 수동 강제 취소를 정상적인 복구 절차로 사용하지 않는다.

## 서버에서 최초 확인할 항목

- `/opt/biodot-qa/current/` 코드와 `.venv/bin/python` 또는 `/opt/biodot-qa/bin/python3.14`가 기존 서버 구성과 일치해야 한다.
- `/etc/biodot/qa.env`와 `/etc/biodot/caddy.env`가 준비돼 있어야 한다. QA 데이터는 `/srv/biodot/qa-data*` 아래에 있어야 한다.
- `biodot-qa` 서비스는 `--qa`를 사용하고 Caddy는 `/etc/biodot/caddy.env`의 `HACCP_STATIC_DIR`을 사용해야 한다. 새로운 서비스나 프록시 설정을 자동 설치하지 않는다.
- 사이트 주소는 서버 `HACCP_SITE_ADDRESS`에서 읽는다. 도메인을 바꾸면 DNS·Caddy·Django 호스트/CSRF 설정도 맞춘다.
- SSH 방화벽이 GitHub-hosted runner의 접속을 허용하는지 확인한다. 로컬 PC 접속 성공만으로 runner 접속이 보장되지는 않는다.
- 백업 시 DB에 쓰는 프로세스가 앱 서비스뿐인지 확인한다. cron·별도 작업자가 있다면 쓰기 중지 절차를 먼저 보완한다. 이 workflow는 알 수 없는 외부 작업을 자동 중지하지 않는다.
- 코드·별도 정적 파일·백업을 모두 보관하므로 여유 공간과 보관 주기를 확인한다. 기존 파일을 일괄 삭제하지 않는다.

## 배포가 중단되면

| 원인 | 처리 |
| --- | --- |
| 설정값 누락·키 오류·접속 거부 | GitHub 설정, 공개키, 호스트 키, 방화벽 확인. 인증 우회하지 않음 |
| migration/SQL 변경·미적용 migration·누락된 migration | 수동 DB 배포로 전환. 백업과 호환성 검토 후 진행 |
| 의존성·Python 변경 | 별도 가상환경 준비와 수동 배포 |
| main이 새 커밋으로 진행됨 | 최신 main의 workflow 실행 |
| 서버 검사·재시작·상태 확인 실패 | Actions 로그와 서버 deployment.json 확인. 자동 복구 결과 확인 후 대응 |

자동 배포를 끄려면 `QA_AUTO_DEPLOY=false`로 설정한다. 수동 실행은 계속 가능하다.

CCP 양식 변경 커밋 `7c61469`에는 `documents/0005_ccp_fixed_phase_rows`·`0006_ccp2b_elapsed_duration`·`0007_ccp1p_gauss_8000` 데이터 마이그레이션이 포함된다. 이 커밋을 QA에 반영할 때는 현재 QA 코드·적용된 마이그레이션을 먼저 확인하고 별도 수동 DB 적용 절차를 작성해야 한다. 기존 `0004_ccp3p_v2` 전용 일회성 배포 절차를 재사용하거나 `--code-only`로 진행하지 않는다. 문서 이관 대상은 작성중 문서이며, 완료·결재 문서와 스냅샷은 당시 버전을 유지한다.

## 보관·복구 경로

```text
/opt/biodot-qa/current/              실행 코드
/opt/biodot-qa/previous-code-*/      이전 코드
/opt/biodot-qa/static-커밋-시각/      버전별 정적 파일
/opt/biodot-qa/backups/시각/         DB·첨부·설정·deployment.json
/srv/biodot/qa-data*/               기존 업무 데이터(계속 유지)
```

코드 배포 실패 복구는 DB 백업 복원을 수행하지 않는다. 업무 DB를 덮어쓸 필요가 있는 복구는 별도로 판단한다. QA DB에 새 migration이 필요한 첫 전환은 자동 배포가 거부하는 것이 정상이며 수동 준비 후 재실행한다.
