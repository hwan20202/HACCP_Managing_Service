"""관리 설정(ADM) 예외 — p16-s2-spec.md 7장.

새 검사 코드는 details[].code(invalid_process·not_producible 등).
"""

from apps.core.http import ApiError


class AdmError(ApiError):
    pass


class ValidationFailed(AdmError):
    status, code, message = 400, "VALIDATION_ERROR", "입력값을 확인하세요."


class ItemNotFound(AdmError):
    status, code, message = 404, "ADM_ITEM_NOT_FOUND", "품목을 찾을 수 없습니다."


class VersionConflict(AdmError):
    status, code, message = (
        409,
        "VERSION_CONFLICT",
        "다른 사람이 먼저 저장했습니다. 새로고침한 뒤 다시 저장하세요.",
    )


def detail(path, code, message):
    return {"path": path, "code": code, "message": message}


class StaffNotFound(AdmError):
    status, code, message = 404, "ADM_STAFF_NOT_FOUND", "직원을 찾을 수 없습니다."


SETUP_FINISHED = (
    '이미 직원이 등록되었습니다 — 새로고침 후 화면 머리 "현재 사용자"에서 고르세요.'  # ADM-R62
)
