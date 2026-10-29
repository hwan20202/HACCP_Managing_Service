"""직원 관리 쓰기 — 관리 설정(ADM)이 부르는 수불 `staff` 표 함수.

P16 묶음 ②, ADM-R20~R22·R24.

수불 업무 기록 경로·목록·CSV 가져오기·`/staff/` API는 그대로다. 이 파일만 새로 생긴다
(`dev-notes/interfaces/staff-admin-notice.md`).

- **스스로 커밋하지 않는다** — 관리 설정 이력 기록과 한 트랜잭션에서 실행
  (호출자 `transaction.atomic`).
- 이름 1~40자, 코드 1~20자(앞뒤 공백 정리). 코드는 비활성 포함 유일, 등록 뒤 바꾸지 않음.
- 삭제 없음 — 비활성·다시 활성만.
"""

import re

from .models import Staff

NAME_MAX = 40
CODE_MAX = 20
CODE_PATTERN = re.compile(r"^([A-Za-z]+)-(\d+)$")
FALLBACK_PREFIX = "S"


class StaffAdminError(Exception):
    """검사 실패 — field·code(invalid·duplicate_code·not_found)·message."""

    def __init__(self, field, code, message):
        super().__init__(message)
        self.field, self.code, self.message = field, code, message


def _text(value, field, limit):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= limit:
        raise StaffAdminError(field, "invalid", f"1~{limit}자 글자여야 합니다.")
    return value.strip()


def next_code():
    """R21: `^[A-Za-z]+-\\d+$` 형식이 가장 많은 접두어의 최대 번호 + 1(자릿수 유지). 없으면 S-001.

    여러 접두어가 같은 수면 먼저(알파벳순) 것. 제안 코드가 이미 있으면 다음 번호. SQL 1.
    """
    codes = set(Staff.objects.values_list("staff_code", flat=True))
    groups = {}
    for code in codes:
        found = CODE_PATTERN.match(code)
        if found:
            groups.setdefault(found.group(1), []).append(found.group(2))
    if groups:
        prefix = sorted(groups, key=lambda p: (-len(groups[p]), p))[0]
        numbers = groups[prefix]
        width = max(len(n) for n in numbers)
        number = max(int(n) for n in numbers) + 1
    else:
        prefix, width, number = FALLBACK_PREFIX, 3, 1
    while f"{prefix}-{number:0{width}d}" in codes:
        number += 1
    return f"{prefix}-{number:0{width}d}"


def create(name, staff_code):
    """R20: 길이·중복 검사 후 활성 직원 1명. 반환 Staff."""
    name = _text(name, "name", NAME_MAX)
    staff_code = _text(staff_code, "staff_code", CODE_MAX)
    if Staff.objects.filter(staff_code=staff_code).exists():
        raise StaffAdminError("staff_code", "duplicate_code", "이미 있는 직원 코드입니다.")
    return Staff.objects.create(staff_code=staff_code, name=name, is_active=True)


def get(staff_id):
    staff = Staff.objects.filter(pk=staff_id).first()
    if staff is None:
        raise StaffAdminError("staff_id", "not_found", "직원을 찾을 수 없습니다.")
    return staff


def rename(staff_id, name):
    """이름만 바꾼다(코드는 바꾸지 않음 — R22). 반환 (Staff, 이전 이름)."""
    name = _text(name, "name", NAME_MAX)
    staff = get(staff_id)
    before = staff.name
    if before != name:
        Staff.objects.filter(pk=staff_id).update(name=name)
        staff.name = name
    return staff, before


def set_active(staff_id, active):
    """비활성·다시 활성(R24). 반환 (Staff, 이전 활성 여부)."""
    staff = get(staff_id)
    before = staff.is_active
    if before != bool(active):
        Staff.objects.filter(pk=staff_id).update(is_active=bool(active))
        staff.is_active = bool(active)
    return staff, before


def active_count():
    """활성 직원 수(처음 설정 판정 — ADM-R62). SQL 1."""
    return Staff.objects.filter(is_active=True).count()
