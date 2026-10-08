# 함께 개발하기

1. README에 따라 자신의 OS에서 `.venv`와 `.env`, DB를 생성합니다.
2. GitHub 연결 후에는 `main`에서 `feature/작업명`, `fix/작업명` 브랜치를 만듭니다.
3. 수정 후 가상환경 Python으로 `scripts/project.py check`를 실행합니다.
4. 화면이나 API 변경은 실제 서버에서도 확인합니다.
5. PR에 목적·변경 내용·확인 결과를 적습니다.

## 코드와 자료

- HTML·CSS·JavaScript: `frontend/`
- Python·Django: `backend/`
- 실행·배포: `scripts/`, `infra/`
- 기준서·엑셀·실행 DB·업로드·백업: `data/` (Git 제외)
- 초기 화면 테스트용 기존 데이터: `data/legacy-prototype/src/js/data.js` (승인된 Git 추적 예외)

추가하는 테스트 자료는 가상의 값으로 작성하고, 업무 데이터나 비밀키를 JS·템플릿·테스트 코드에 복사하지 않습니다. 기존 시제품 `data.js` 한 파일만 초기 개발 테스트를 위해 Git에 포함하기로 했으며, 다른 실제 자료에는 이 예외를 적용하지 않습니다. 파일명과 코드 식별자는 영문을 사용하고 사용자 문구는 한국어로 작성합니다.

기존 시제품의 보존 원본인 `data/legacy-prototype/`은 수정하지 않습니다. 실행 화면은 `frontend/`에서 수정합니다. 업무 화면과 인쇄 화면은 외부 폰트 서버에 접속하지 않고 OS 기본 글꼴을 사용합니다.

## DB 변경

모델 변경 후 가상환경 Python으로 `backend/manage.py makemigrations`를 실행하고 생성된 마이그레이션 파일을 PR에 포함합니다. 팀원은 업데이트 후 `scripts/project.py init`으로 적용합니다. 기존 DB나 다른 사람이 이미 적용한 마이그레이션을 임의로 덮어쓰지 않습니다.

## 의존성

`requirements/`는 직접·간접 의존성 버전을 고정합니다. 업데이트 시 지원 중인 Django 5.2 LTS 패치를 우선하고 세 OS 검사 결과를 확인합니다. `base.txt`는 공통, `production.txt`는 Waitress, `dev.txt`는 검사 도구까지 포함합니다. 전역 Python이나 다른 프로젝트의 패키지는 변경하지 않습니다.
