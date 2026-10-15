"""REQ-CMD-01 주기 문서 만들기 (dev-notes/doc-requirements/p9-s2-spec.md 5장).

    manage.py make_periodic_documents --actor 3                         # 오늘
    manage.py make_periodic_documents --actor 3 --date 2026-10-13
    manage.py make_periodic_documents --actor 3 --from 2026-10-01 --to 2026-10-13 --type D10,D12

종료 코드: 0 실패 줄 없음 / 1 실패 줄 있음(나머지는 만들어짐)
          / 2 입력·사용자·규칙 오류 또는 예기치 못한 오류(DB 등 — 전체 롤백)
            — 아무것도 안 만듦(D-144 A1).
운영에서는 하루 한 번(작업 시작 전) 스케줄러로 부른다 — docs/deployment.md.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.core.http import ApiError
from apps.doc_requirements import periodic

LABELS = {
    "created": "만듦",
    "existing": "이미 있음",
    "skipped_rule": "대상 아님",
    "failed": "실패",
}


def format_line(line):
    head = f"{line['work_date']} {line['type_code']} {line['result']:<12}"
    number = f"#{line['document_id']}" if line.get("document_id") else "-"
    text = f"{head} {number} {line['record_key']}"
    if line["result"] == "existing":
        text += f" ({line['status']})"
    elif line["result"] == "skipped_rule":
        text += f" ({line['reason']})"
    elif line["result"] == "failed":
        text += f" [{line['code']}] {line['message']}"
    return text


def format_totals(totals):
    return "합계: " + " · ".join(f"{LABELS[k]} {totals[k]}" for k in LABELS)


class Command(BaseCommand):
    help = (
        "주기 작성 요구 규칙(periodic_rules.json)대로 점검표 문서(D10·D12 매일, D11 매주)를 "
        "찾거나 만든다. 기본은 오늘 하루, 빠진 날은 --from·--to로 최대 31일까지. 미래 날짜 불가."
    )

    def add_arguments(self, parser):
        parser.add_argument("--actor", type=int, required=True, help="만든 사람 staff id")
        parser.add_argument("--date", help="하루(YYYY-MM-DD). --from·--to와 함께 못 씀")
        parser.add_argument("--from", dest="date_from", help="시작일(YYYY-MM-DD)")
        parser.add_argument("--to", dest="date_to", help="끝일(YYYY-MM-DD)")
        parser.add_argument("--type", dest="types", help="양식 코드 쉼표 목록(예: D10,D12)")

    def handle(self, *args, **options):
        day, start, end = options.get("date"), options.get("date_from"), options.get("date_to")
        if day and (start or end):
            raise CommandError("--date와 --from·--to는 함께 쓸 수 없습니다.", returncode=2)
        if bool(start) != bool(end):
            raise CommandError("--from과 --to는 함께 지정하세요.", returncode=2)
        if not (day or start):
            day = periodic._today().isoformat()
        if day:
            start = end = day
        types = None
        if options.get("types"):
            types = [code.strip() for code in options["types"].split(",") if code.strip()]
        try:
            result = periodic.run_periodic(options["actor"], start, end, types)
        except ApiError as error:
            details = "; ".join(
                f"{d.get('path')}: {d.get('message')}" for d in (error.details or [])[:3]
            )
            raise CommandError(
                f"[{error.code}] {error.message}" + (f" — {details}" if details else ""),
                returncode=2,
            ) from None
        except Exception as error:  # noqa: BLE001 — 종료 코드 1("일부 만들어짐")과 섞이지 않게
            raise CommandError(
                f"[예기치 못한 오류] {type(error).__name__}: {error} — 아무것도 만들지 않았습니다.",
                returncode=2,
            ) from error
        for line in result["lines"]:
            self.stdout.write(format_line(line))
        self.stdout.write(format_totals(result["totals"]))
        if result["totals"]["failed"]:
            raise CommandError(f"실패 줄 {result['totals']['failed']}개", returncode=1)
