from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.devtools.seed_workflow import seed_workflow
from apps.documents.models import Document
from apps.documents.seed import ensure_staff


class Command(BaseCommand):
    help = (
        "개발·사용 테스트용 가상 데이터(P3): staff, 양식, 문서, 결재를 넣는다. "
        "결재 데이터는 WF 함수로 만든다(상신·승인·반려·재상신). "
        "문서가 없을 때만 동작한다."
    )

    @transaction.atomic
    def handle(self, *args, **options):
        ensure_staff()
        if Document.objects.exists():
            raise CommandError(
                "이미 문서가 있습니다. 기존 데이터를 지우지 않으므로 빈 DB에서 실행하세요 "
                "(data/db/app.sqlite3 삭제 → init → seed_dev_workflow)."
            )
        made = seed_workflow()
        self.stdout.write(
            f"staff 1~5, 양식 3개, draft·삭제 문서 {made['drafts']}건, "
            f"결재 시나리오 {made['scenarios']}건, 결재함 페이지용 {made['paging']}건, "
            f"어긋난 데이터(PS-05) {made['mismatch']}건을 넣었습니다."
        )
