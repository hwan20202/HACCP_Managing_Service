> 개발 당시 기록입니다. 현재 사용·설치 기준은 [문서 목차](../../README.md)의 전달본과 참고 명세를 확인하세요.

# 호스팅 QA 준비 검증 — 2026-10-16

기준 브랜치 `feature/inventory-production`, 기존 커밋 `3f884f9` 이후의 QA 배포 준비 변경을 검증한 기록이다. 이 검증에서는 서버 접속·배포·원격 DB 수정·main 병합을 하지 않았다. 서버 OS는 사용자 확인값 Ubuntu 24.04.4 LTS이며 상품 종류와 접속 범위는 미확인이다.

## 변경

- 전용 `config.settings.qa`: DEBUG=False, 코드 밖 영구 QA 데이터, 운영 경로와 중첩 방지, 개발 콘솔 차단, QA 배너와 문서 메뉴.
- `project.py --qa`: migrate/collectstatic/serve/backup의 데이터 경로를 통일. migrate 후 초기 프로토타입 표시 자료는 없을 때만 복사. DB·첨부는 교체하지 않음.
- `install_document_templates`: 샘플 없이 양식만 등록, 기존 내용과 비활성 상태 보존.
- Seeder: 명시적 QA 허용, 운영 차단, 기본 LOT 규칙 등록, DB 완료 기록으로 날짜 변경/재실행 중복 방지, 기존 QA BOM 구성 검증.
- QA 화면: 실제 입고 API를 사용하는 최소 입고 등록. 소비기한 유무는 명시 선택, 직원·공급처는 QA 마스터 사용. 개발 API를 공개하지 않음.
- 배포 준비 파일: `.env.qa.example`, Caddy 접근 제한 예시, Linux systemd 예시, `cafe24-qa-deployment.md`.

## 격리 DB 리허설

프로젝트의 `data/db/app.sqlite3` 대신 **저장소 밖 신규 파일 DB**를 사용했다. 모든 데이터 변경은 이 DB에만 수행했다.

```text
C:/Users/82108/.codex/visualizations/2026/10/14/01a13a57-1ca0-73b2-837b-e510615de8d1/
  hosted-qa-rehearsal-v2/results.json
  hosted-qa-rehearsal-v2/qa-data/
```

해당 디렉터리의 `qa.env`는 생성된 비밀키를 가진 로컬 시험용 설정이며 Git에 넣지 않는다. 리허설에서만 HTTP/루프백을 사용했다.

| 명령/조건 | 확인 결과 |
| --- | --- |
| QA init → 양식 등록 | 새 DB에 전체 migrate, 활성 양식 9종(과거 버전 포함 실제 10행) |
| prepare | 품목 24, BOM 3, LOT 30, 입고 28, 배치 0, 수불 30, 문서 84 |
| prepare 재실행 | 건수 동일 |
| prepare → run | LOT 33, 완료 배치 3, 수불 58, 문서 93; LOT별 예상 재고 대조 통과 |
| run 재실행 → prepare | 건수 동일 |
| init 재실행 → collectstatic | 기존 DB 건수 및 첨부 보존용 파일 내용 동일 |
| backup --writes-stopped | DB+첨부 ZIP+버전 정보 생성 |
| QA 허용 false | 적재 거부 |
| production 설정 + QA 허용 true | 적재 거부 |
| QA 경로를 기존 저장소 data로 지정 | 설정 단계에서 거부 |

리허설 스크립트 자체의 첫 시도에서는 문서 테이블명을 잘못 조회해 중단됐다. 그 DB는 보존하고 새 `v2` 경로에서 전체 리허설 13단계를 완료했다. 업무 코드 실패를 우회한 것은 아니다.

## 자동/브라우저 검증

- Django 전체: **766개 발견, 735개 통과, 31개 건너뜀, 실패·오류 0**(40.569초). 설정·서비스 공통 변경에 대한 회귀 검사 한 번 수행. 로그: 아티팩트 루트 `qa-hosted-full-tests.log`.
- 이번 관련 테스트 20개 통과. 신규 회귀 7개는 날짜 변경·수동 거래 후 재적재 보존, prepare/run 전환, 운영/미허용 QA 차단, 기존 거래 혼합/명시적 날짜 변경 차단, 양식만 반복 설치, 비활성 양식 보존, QA 배너 구분이다.
- Ruff 검사/format 215개 파일, JavaScript 문법 검사, 스크립트 HTTP 회귀 1개, makemigrations 누락 검사 통과. 권한 제한으로 임시 폴더/루프백 접근에 실패한 최초 실행은 권한 허용 후 동일 검사를 다시 수행해 통과했다.
- QA 배포 설정의 `check --deploy`는 오류 0, 경고 2(W005·W021). 기존 production 정책에 따라 다른 하위 도메인까지 HSTS를 강제하거나 preload를 신청하지 않는 설정에서 발생했다. 실제 도메인 범위를 모르는 상태에서 이 값을 변경하지 않았다.
- DEBUG=False QA 설정의 로컬 브라우저: 배너, 개발 콘솔 메뉴 숨김, QA 입고 버튼, 소비기한 기본값 빈 선택, 실제 입고 저장 후 재고·수불 표시, 제조배치 메뉴·직원·반제품 조회, JavaScript 예외 없음 **8항목 통과**, HTTP 오류 0.
- 브라우저 검증 도구의 첫 두 실행에서 모달 닫힘/비동기 데이터 로딩 대기 조건을 수정했다. 실제 입고는 각 실행에서 성공했으므로 격리 DB에는 추가 입고 3건이 남는다. 각각 재고·수불 1건과 문서 3건이 연결된다. 기존 로컬 개발 DB 거래는 추가하지 않았다.
- 브라우저 결과: `qa-hosted-browser-results.json`, 캡처: `qa-hosted-screen.png`, `qa-hosted-last.png` (위 아티팩트 루트).

로컬 QA 서버는 runserver --insecure로 정적 자산을 제공하는 시험이었다. 실제 Caddy/Waitress 연결·인증·HTTPS 검증 결과로 해석하지 않는다. 첨부 보존은 보존용 파일과 백업 ZIP으로 확인했으며 실제 서버 파일 업로드/다운로드·결재 전체 흐름은 배포 후 별도로 확인한다.

## 기존 개발 DB 보존

기존 개발 DB는 삭제·초기화·Seeder 실행·마이그레이션을 하지 않았다. 확인 당시 품목 30, BOM 4, LOT 34, 입고 28, 제조배치 4, 수불 61, 문서 96이었다. 기존 보고서의 재고·생산 거래는 그대로 유지한다.

실제 배포 전 필요한 결정과 실행 순서는 `cafe24-qa-deployment.md`를 따른다. 현재 OS 정보만으로 카페24 상품이나 외부 공개 정책을 확정하지 않는다.
