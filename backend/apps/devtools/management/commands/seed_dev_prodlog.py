from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.devtools import prodlog_dev
from apps.staff import services as staff_services


class Command(BaseCommand):
    help = (
        "P15 S5 개발 시드(운영 제외): 생산일지 양식·공정 기준정보 설치 + 개발 품목·BOM + "
        "배치(생산 시작 직후·투입 완료·일부 투입·취소). 실행할 때마다 배치를 새로 만든다."
    )

    def add_arguments(self, parser):
        parser.add_argument("--staff", type=int, help="기록할 직원 id. 기본값 첫 활성 직원")
        parser.add_argument(
            "--scenario",
            action="append",
            choices=prodlog_dev.SCENARIOS,
            help="만들 배치(여러 번 가능). 기본값 네 가지 모두",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("개발 설정(DEBUG)에서만 실행합니다.")
        staff = options.get("staff") or next(iter(staff_services.active_ids()), None)
        if staff is None:
            raise CommandError("활성 직원이 없습니다. 먼저 직원을 넣으세요.")
        for scenario in options.get("scenario") or prodlog_dev.SCENARIOS:
            out = prodlog_dev.make(scenario, staff)
            self.stdout.write(
                f"{scenario}: 배치 {out['batch_number']}(id {out['batch_id']}) · 생산일지 "
                f"#{out['prod_log_id']} · 문서 "
                + ", ".join(d["type_code"] for d in out["documents"])
            )
