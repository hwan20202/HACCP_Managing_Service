from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.devtools.seed_print import (
    seed_print,
    seed_print_monthly,
    seed_print_receiving,
    seed_print_weekly,
    seed_print_weekly_d12,
)


class Command(BaseCommand):
    help = (
        "P12 출력 확인용: 새 제조 배치 1개와 CCP-1P(승인·개선조치 확인됨)·CCP-2B(결재중)·"
        "CCP-3P(정정 중)를 만들고, 그날 입고일에 D03 육안검사 10건(2쪽), "
        "지난주 D10·D12 점검표, 지난달 D11 방충방서점검표를 만든다. "
        "같은 날짜로 다시 실행하면 그대로 둔다."
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
        rcv = seed_print_receiving(options.get("date"))
        state = "만들었습니다" if rcv["created"] else "이미 있습니다(그대로 둠)"
        self.stdout.write(
            f"D03 입고일 {rcv['date']} → /print/?kind=receiving&type=D03&date={rcv['date']}"
        )
        self.stdout.write(f"출력 확인용 D03 묶음을 {state}.")
        week = seed_print_weekly(options.get("date"))
        state = "만들었습니다" if week["created"] else "이미 있습니다(그대로 둠)"
        self.stdout.write(
            f"D10 주 {week['week_start']} → /print/?kind=weekly&type=D10&date={week['week_start']}"
        )
        self.stdout.write(f"출력 확인용 D10 주를 {state}.")
        week = seed_print_weekly_d12(options.get("date"))
        state = "만들었습니다" if week["created"] else "이미 있습니다(그대로 둠)"
        self.stdout.write(
            f"D12 주 {week['week_start']} → /print/?kind=weekly&type=D12&date={week['week_start']}"
        )
        self.stdout.write(f"출력 확인용 D12 주를 {state}.")
        month = seed_print_monthly(options.get("date"))
        state = "만들었습니다" if month["created"] else "이미 있습니다(그대로 둠)"
        self.stdout.write(
            f"D11 월 {month['month']} → /print/?kind=monthly&type=D11&month={month['month']}"
        )
        self.stdout.write(f"출력 확인용 D11 월을 {state}.")
