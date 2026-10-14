from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.documents.models import Document
from apps.documents.seed import ensure_staff, ensure_templates, seed_documents


class Command(BaseCommand):
    help = "개발·사용 테스트용 가상 staff, 양식, 문서를 넣는다(문서가 없을 때만)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--no-documents", action="store_true", help="staff와 양식만 넣고 문서는 넣지 않는다."
        )

    @transaction.atomic
    def handle(self, *args, **options):
        ensure_staff()
        ensure_templates()
        if options["no_documents"]:
            self.stdout.write("staff 1~5, 양식 3개를 확인했습니다.")
            return
        if Document.objects.exists():
            raise CommandError(
                "이미 문서가 있습니다. 기존 데이터를 지우지 않으므로 빈 DB에서 실행하세요."
            )
        created = seed_documents()
        self.stdout.write(f"staff 1~5, 양식 3개, 문서 {len(created)}건을 넣었습니다.")
