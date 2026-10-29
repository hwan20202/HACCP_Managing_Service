"""역할 테스트 준비물(P16 묶음 ②): 역할 원본이 DB(ADM 문서 권한)라 dict를 DB에 넣는다.

`use_roles(data)`는 roles.json 모양 dict로 문서 권한 전체를 바꾼다(팀장·사람 비우고 다시 넣기,
파일에 있는 양식은 slots·labels도). 없는 직원 코드는 넣을 수 없어 건너뛴다(P14의 R-W1 자리).
"""

import copy

from apps.admin_settings import store as adm_store
from apps.admin_settings.models import RoleFormMember, RoleLeader
from apps.staff import dev_roles
from apps.staff import services as staff_services
from apps.staff.models import Staff


def default_roles():
    """기본 개발 설정(apps/staff/roles.json)의 사본 — 고쳐서 use_roles에 넘긴다."""
    return copy.deepcopy(dev_roles.dev_data())


EMPTY = {"version": 1, "haccp_leaders": [], "forms": {}}  # 사람 0명(양식 행은 그대로)


def _codes(data):
    codes = set(data.get("haccp_leaders", []))
    for form in data.get("forms", {}).values():
        codes.update(form.get("owners", []))
        codes.update(form.get("writers", []))
    return codes


def put_roles(data):
    """문서 권한 전체를 data로 바꾼다(버전 +1)."""
    # use_roles를 직원 시드보다 먼저 부르는 테스트가 있어 가상 직원(DEV-001~010)은 먼저 만든다
    # (P14 파일 방식은 쓸 때 코드를 찾았다). DEV-404 같은 "없는 코드"는 만들지 않는다.
    numbers = [int(c[4:]) for c in _codes(data) if c[:4] == "DEV-" and c[4:].isdigit()]
    staff_services.ensure_dev_staff(sorted(n for n in numbers if 1 <= n <= 10))
    adm_store.ensure_role_version()
    RoleLeader.objects.all().delete()
    RoleFormMember.objects.all().delete()
    ids = dict(Staff.objects.filter(staff_code__in=_codes(data)).values_list("staff_code", "id"))
    dev_roles.put_file_roles(
        {"haccp_leaders": data.get("haccp_leaders", []), "forms": data.get("forms", {})},
        ids,
        set(ids.values()),
        shape=True,
    )
    adm_store.bump_role_version()


class RolesFileMixin:
    def use_roles(self, data):
        put_roles(data)
