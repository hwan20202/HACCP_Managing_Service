from apps.core.http import ApiError

from .models import Staff


class StaffHeaderMissing(ApiError):
    status = 400
    code = "STAFF_HEADER_MISSING"
    message = "현재 사용자(X-Staff-Id)를 지정하세요."


class InvalidStaff(ApiError):
    status = 403
    code = "INVALID_STAFF"
    message = "등록되지 않은 사용자입니다."


def actor_from_header(value):
    """X-Staff-Id 헤더 값을 확인하고 staff_id를 돌려준다."""
    if value is None or str(value).strip() == "":
        raise StaffHeaderMissing()
    text = str(value).strip()
    if not text.isdigit():
        raise InvalidStaff()
    staff_id = int(text)
    if not Staff.objects.filter(pk=staff_id, is_active=True).exists():  # D-128 D1 비활성 거부
        raise InvalidStaff()
    return staff_id


def optional_actor_from_header(value):
    """헤더가 선택인 조회(P11 B2): 없으면 None, 있으면 actor_from_header와 같이 확인한다."""
    if value is None or str(value).strip() == "":
        return None
    return actor_from_header(value)


def existing_ids(ids):
    wanted = {i for i in ids if isinstance(i, int) and not isinstance(i, bool)}
    if not wanted:
        return set()
    return set(
        Staff.objects.filter(pk__in=wanted, is_active=True).values_list("id", flat=True)
    )  # D-128 D1: 비활성 직원은 결재자·담당자·확인자로 지정할 수 없음


def active_ids():
    """활성 직원 id 목록(오름차순)."""
    return list(Staff.objects.filter(is_active=True).order_by("id").values_list("id", flat=True))


def active_people():
    """활성 직원 [{id, staff_code, name}] id 순.

    P14 ROLE-A02 — 화면 사람 표시 "이름(코드)", DR-07.
    """
    return [
        {"id": sid, "staff_code": code, "name": name}
        for sid, code, name in Staff.objects.filter(is_active=True)
        .order_by("id")
        .values_list("id", "staff_code", "name")
    ]


def ensure_dev_staff(ids):
    """개발·테스트용 가상 직원(코드 DEV-001…). 이미 있으면 그대로 둔다."""
    for staff_id in ids:
        Staff.objects.get_or_create(
            id=staff_id,
            defaults={"staff_code": f"DEV-{staff_id:03d}", "name": f"개발직원{staff_id}"},
        )


def names_of(ids):
    """P12 출력: 직원 id → 이름(비활성 포함 — 지난 기록의 사람). 없는 id는 빠진다. SQL 1."""
    wanted = {i for i in ids if isinstance(i, int) and not isinstance(i, bool)}
    if not wanted:
        return {}
    return dict(Staff.objects.filter(pk__in=wanted).values_list("id", "name"))
