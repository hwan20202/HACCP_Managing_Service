"""테스트 도우미 — TransactionTestCase가 끝날 때 표를 비우면 0002의 기본 CCP 2행도 사라진다.

(P15 기본 제공 공정과 같은 문제.) 생산 시작을 부르는 테스트 준비에서 다시 넣는다.
운영 코드에서는 쓰지 않는다.
"""

from django.utils import timezone

from .models import CcpDefault

DEFAULTS = (("MANUFACTURE", True), ("PACKAGING", False))  # 0002와 같음(ADM-R04)


def ensure_ccp_defaults():
    now = timezone.now()
    for process_type, on in DEFAULTS:
        CcpDefault.objects.get_or_create(
            process_type=process_type,
            defaults={"ccp_1p": on, "ccp_2b": on, "ccp_3p": on, "updated_at": now},
        )
