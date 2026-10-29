"""기존 역할 파일(roles.json) → DB 문서 권한(P16 ADM-R41~R44, F21).

이미 `roles.json`을 쓰던 서버(개발·QA·파일 운영)를 옮길 때만 쓴다. 새 설치는 처음 설정 화면에서
직원 등록 → 문서 권한 화면에서 지정(R40).

    python manage.py import_roles --file data/roles.json --actor DEV-001 [--replace]

실패하면 아무것도 넣지 않고 종료 코드 2: 형식 오류, --actor가 활성 직원이 아님, 파일의 직원 코드가
staff에 없음(목록 출력), 문서 권한에 이미 사람이 있는데 --replace 없음.
파일은 지우지 않는다(R45).
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.admin_settings import services


class Command(BaseCommand):
    help = "roles.json(HACCP팀장·양식 담당자·작성 권한자·결재 칸)을 DB 문서 권한으로 가져온다"

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True, help="roles.json 경로")
        parser.add_argument("--actor", required=True, help="이력에 남을 사람 — 활성 직원 코드")
        parser.add_argument(
            "--replace", action="store_true", help="이미 있는 사람·slots·labels를 파일대로 바꿈"
        )

    def handle(self, *args, **options):
        path = Path(options["file"]).expanduser()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as error:
            raise CommandError(f"파일을 읽지 못했습니다: {error}", returncode=2) from None
        try:
            with transaction.atomic():
                report = services.import_roles(data, options["actor"], options["replace"])
        except services.ImportFailed as failed:
            lines = "".join(f"\n  - {line}" for line in failed.lines)
            raise CommandError(f"{failed.message}{lines}", returncode=2) from None
        self.stdout.write(
            f"가져왔습니다 — 버전 {report['version']}, 팀장 {report['leaders']}명, "
            f"양식 {len(report['forms'])}개: {', '.join(report['forms']) or '없음'}"
        )
        if report["skipped"]:
            self.stdout.write(
                self.style.WARNING(
                    "양식이 설치되지 않아 건너뜀(R43): " + ", ".join(report["skipped"])
                )
            )
        if report["inactive_codes"]:
            self.stdout.write(
                self.style.WARNING(
                    "비활성 직원은 넣었지만 효과는 없음: " + ", ".join(report["inactive_codes"])
                )
            )
