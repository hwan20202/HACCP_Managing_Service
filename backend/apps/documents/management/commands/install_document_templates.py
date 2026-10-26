"""Install current reference forms without any sample staff, LOTs or documents."""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.documents.seed import ensure_p4_templates, ensure_p8_templates, ensure_p15_templates


class Command(BaseCommand):
    help = "기본 양식 D01~D03·CCP-1P/2B/3P·D10~D12 등록 (기존 내용·활성 상태 보존)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--production-log",
            action="store_true",
            help="P15 생산일지(PROD-LOG)도 등록. 등록하면 생산 시작 때 생산일지가 만들어진다",
        )

    def handle(self, *args, **options):
        with transaction.atomic():
            forms = {**ensure_p4_templates(), **ensure_p8_templates()}
            if options.get("production_log"):
                forms.update(ensure_p15_templates())
            inactive = [code for code, form in forms.items() if not form.is_active]
            if inactive:
                raise CommandError(f"기존 비활성 양식은 자동 활성화하지 않습니다: {inactive}")
        self.stdout.write("양식 확인: " + ", ".join(sorted(forms)))
        self.stdout.write("기존 양식 내용을 덮어쓰거나 업무·샘플 문서를 생성하지 않았습니다.")
