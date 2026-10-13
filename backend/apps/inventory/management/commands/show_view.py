"""Print a read view (v_*) of the inventory schema: its columns and a few rows.

    python backend/manage.py show_view                         # list the views
    python backend/manage.py show_view v_doc_incoming_lot
    python backend/manage.py show_view v_doc_batch --limit 20
    python backend/manage.py show_view v_doc_incoming_lot --sql  # the CREATE VIEW statement

For checking what the document app will read. Read-only: only views (names starting with v_)
can be shown.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import connection


def _views(cursor):
    cursor.execute(
        "SELECT name, sql FROM sqlite_master WHERE type = 'view' AND name LIKE 'v\\_%' ESCAPE '\\'"
        " ORDER BY name"
    )
    return dict(cursor.fetchall())


class Command(BaseCommand):
    help = "v_ 로 시작하는 조회 뷰의 컬럼과 데이터 몇 줄을 보여줍니다."

    def add_arguments(self, parser):
        parser.add_argument("view", nargs="?", help="뷰 이름 (생략하면 목록)")
        parser.add_argument("--limit", type=int, default=10, help="보여줄 행 수 (기본 10)")
        parser.add_argument("--sql", action="store_true", help="뷰 정의(CREATE VIEW) 출력")

    def handle(self, *args, view=None, limit=10, sql=False, **options):
        with connection.cursor() as cursor:
            views = _views(cursor)
            if not view:
                for name in views:
                    self.stdout.write(name)
                return
            if view not in views:
                raise CommandError(f"뷰를 찾을 수 없습니다: {view} (목록: {', '.join(views)})")
            if sql:
                self.stdout.write(views[view])
                return
            cursor.execute(f'SELECT COUNT(*) FROM "{view}"')
            total = cursor.fetchone()[0]
            cursor.execute(f'SELECT * FROM "{view}" LIMIT %s', [max(limit, 0)])
            columns = [column[0] for column in cursor.description]
            rows = cursor.fetchall()

        self.stdout.write(f"{view}: {len(columns)}개 컬럼, {total}행")
        for index, column in enumerate(columns, 1):
            self.stdout.write(f"  {index:>2}. {column}")
        for number, row in enumerate(rows, 1):
            self.stdout.write(f"\n[{number}]")
            for column, value in zip(columns, row, strict=True):
                self.stdout.write(f"  {column:<22} {value!r}")
        if total > len(rows):
            self.stdout.write(f"\n... {total - len(rows)}행 더 있음 (--limit 로 조절)")
