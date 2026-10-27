from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.production_log.seed import seed_production_master
from apps.staff import services as staff_services


class Command(BaseCommand):
    help = (
        "P15 개발 시드(운영 제외 — S2 Q6): 일반 공정 9개·공정 템플릿 3개(효력환·녹용농축분말·"
        "EXO-Boost 발효녹용)와 기본 제공 공정 설명. 다시 실행해도 있는 것은 그대로 둔다."
    )

    def add_arguments(self, parser):
        parser.add_argument("--staff", type=int, help="기록할 직원 id. 기본값 첫 활성 직원")

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("개발 설정(DEBUG)에서만 실행합니다.")
        staff = options.get("staff") or next(iter(staff_services.active_ids()), None)
        if staff is None:
            raise CommandError("활성 직원이 없습니다. 먼저 직원을 넣으세요.")
        made = seed_production_master(staff)
        self.stdout.write(
            f"일반 공정 {made['processes']}개, 템플릿 {made['templates']}개를 넣고 "
            f"기본 제공 {made['builtins']}개 설명을 채웠습니다."
        )
