# 자료와 실행 데이터

코드 이외의 자료를 이 폴더에 모았습니다. Git에는 이 README와 초기 개발 테스트용으로 승인한 `legacy-prototype/src/js/data.js`만 포함합니다. PDF·엑셀·DB·업로드·백업과 나머지 보존 원본은 제외합니다.

| 위치 | 내용 |
|---|---|
| `reference/setup_standard/` | 원본 PDF 기준서 |
| `reference/기초데이터/` | 원본 엑셀 대장 |
| `reference/missing_sections.txt` | 기존 작업 메모 |
| `reference/migration-manifest.json` | 기존 파일 40개의 이전 위치·현재 위치·SHA-256 |
| `legacy-prototype/` | 기존 HTML·JS·CSS·테스트 HTML·백업 파일 전체 |
| `legacy-prototype/src/js/data.js` | Git에 포함하는 기존 시제품 데이터. 신규 복제 환경의 초기 화면 테스트용 |
| `db/app.sqlite3` | 새 Django 시스템의 로컬 DB |
| `uploads/` | 문서 첨부 파일. DB와 같은 시점으로 백업·복구 |
| `static/` | 운영용으로 수집한 공개 정적 파일 |
| `logs/` | 운영 및 로컬 검증 로그 |
| `backups/` | DB·업로드 백업 |
| `handover/` | Git 제외 전달 자료. v8 기준정보 초기 DB·원본·검증 목록 및 별도 전달 ZIP |
| `caddy/`, `config/caddy/` | Caddy 인증서·상태·자동 저장 설정 |

원본 한글 파일명은 그대로 보존했습니다. macOS의 한글 정규화 형식 차이 때문에 다른 OS에서 표기가 같아도 파일명 내부 표현이 다를 수 있습니다. 기준서 제공 경로는 한글 파일명을 정규화해 비교하므로 macOS·Windows 파일명의 내부 표현 차이를 처리합니다.

기존 화면의 실행 코드는 `frontend/`에 복사해 사용합니다. 데이터는 `legacy-prototype/src/js/data.js`를 읽고, 기준서 열람은 `reference/setup_standard/기타가공품 기준서-250831.pdf`를 읽습니다. 원본 데이터와 PDF를 수정하거나 DB로 가져오지는 않습니다.

`data` 전체를 웹 서버의 공개 경로로 지정하지 마세요. Caddy는 `static` 하위만 직접 제공하고, Django는 지정 시제품 자료와 문서 첨부 API를 통해 허용된 자료를 제공합니다. 개인별 로그인은 없습니다. 원본·엑셀·백업·초기 DB 전달 파일을 공개 경로에 두지 않습니다.

기본 `HACCP_DATA_DIR=data`에서는 저장소 복제 후 별도 자료 전달 없이 초기 화면을 테스트할 수 있습니다. 포함한 `data.js`는 기존 시제품 자료이며 가상으로 생성한 샘플이 아닙니다. 이 파일의 원본 내용은 수정하지 않습니다. 시제품 고정 자료와 서버 저장에 연결된 입고·생산·문서 화면은 구분합니다. 시제품 자료 파일만으로 서버 DB의 업무 기록이 준비되는 것은 아닙니다.

운영에서는 `HACCP_DATA_DIR`을 예를 들어 `C:/HACCPData`로 지정해 DB·업로드를 코드 배포 폴더와 분리합니다. 경로를 바꾸면 위의 시제품 데이터와 PDF도 새 데이터 폴더에 같은 구조로 복사합니다. 기존 원본은 이 프로젝트의 `data/`에 보존합니다. 기준서 PDF 등 Git에서 제외한 자료는 필요한 팀원에게 사내 승인된 방법으로 별도로 전달합니다.
