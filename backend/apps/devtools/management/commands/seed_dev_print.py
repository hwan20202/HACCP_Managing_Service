from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.devtools.seed_print import seed_print


class Command(BaseCommand):
    help = (
        "P12 출력 확인용: 새 제조 배치 1개와 CCP-1P(승인·개선조치 확인됨)·CCP-2B(결재중)·"
        "CCP-3P(정정 중)를 만든다. 같은 날짜로 다시 실행하면 그대로 둔다."
    )

    def add_arguments(self, parser):
        parser.add_argument("--date", help="작업일(YYYY-MM-DD). 기본값 오늘")

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("개발 설정(DEBUG)에서만 실행합니다.")
        out = seed_print(options.get("date"))
        state = "만들었습니다" if out.pop("created") else "이미 있습니다(그대로 둠)"
        for code, document_id in sorted(out.items()):
            self.stdout.write(f"{code} 문서 #{document_id} → /print/?document_id={document_id}")
        self.stdout.write(f"출력 확인용 CCP 문서를 {state}.")
