# apps/staff — 역할 파일 안내

`roles.json`은 **서버 실행 중에는 읽지 않습니다**(P16, ADM-R45). 문서 권한(HACCP팀장·양식별 담당자·작성 권한자·결재 칸)은 DB(`role_config`·`role_leader`·`role_form`·`role_form_member`)에 있고, 화면 [문서 권한]에서 고칩니다.

이 파일의 쓰임:

- **기존 서버 이관 입력** — P16 이전에 역할 파일을 쓰던 서버는 `migrate` 뒤 한 번 옮깁니다.
  `python manage.py import_roles --file <roles.json> --actor <활성 직원 코드> [--replace]`
  - 파일의 직원 코드가 `staff`에 하나라도 없으면 아무것도 넣지 않고 실패합니다.
  - 사람이 이미 있으면 `--replace` 없이는 거부합니다. `--replace`는 HACCP팀장과 **파일에 있는 양식**만 파일대로 바꾸고, 파일에 없는 양식은 그대로 둡니다.
- **참고** — 개발 직원(DEV-001~005) 기준 기본 구성의 예시입니다. 새 설치는 빈 문서 권한에서 화면으로 지정합니다.
