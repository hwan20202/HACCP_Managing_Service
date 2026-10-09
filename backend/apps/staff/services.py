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
    if not Staff.objects.filter(pk=staff_id).exists():
        raise InvalidStaff()
    return staff_id


def existing_ids(ids):
    wanted = {i for i in ids if isinstance(i, int) and not isinstance(i, bool)}
    if not wanted:
        return set()
    return set(Staff.objects.filter(pk__in=wanted).values_list("staff_id", flat=True))
