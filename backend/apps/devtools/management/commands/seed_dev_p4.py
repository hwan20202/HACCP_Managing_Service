from django.apps import apps
from django.core.management.base import BaseCommand, CommandError

from apps.devtools.seed_p4 import seed_p4


class Command(BaseCommand):
    help = (
        "P4 가상 데이터: 수불 임시 데이터(품목·입고 LOT·생산 배치)와 작성 요구 양식 6종, "
        "N1로 만든 작성 요구 문서(입고 LOT마다 D01·D02·D03, 배치마다 CCP)를 넣는다. "
        "같은 날짜로 다시 실행하면 이미 있는 문서는 그대로 둔다. "
        "seed_dev_workflow 뒤에 실행해도 된다."
    )

    def add_arguments(self, parser):
        parser.add_argument("--date", help="작업일(YYYY-MM-DD). 기본값 오늘")

    def handle(self, *args, **options):
        if not apps.is_installed("apps.devstock"):
            raise CommandError("apps.devstock이 설치된 설정(development·test)에서만 실행합니다.")
        made = seed_p4(options.get("date"))
        self.stdout.write(f"작성 요구 문서 {made['documents']}건을 넣었습니다.")
