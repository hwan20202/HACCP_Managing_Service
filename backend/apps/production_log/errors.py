"""생산일지·생산 기준정보(PLG) 예외 — p15-s2-spec.md 6장."""

from apps.core.http import ApiError


class PlgError(ApiError):
    pass


class ValidationFailed(PlgError):
    status, code, message = 400, "VALIDATION_ERROR", "입력값을 확인하세요."


class TemplateInvalid(PlgError):
    status, code, message = 400, "PLG_TEMPLATE_INVALID", "템플릿 공정 구성을 확인하세요."


class ProcessNotFound(PlgError):
    status, code, message = 404, "PLG_PROCESS_NOT_FOUND", "공정을 찾을 수 없습니다."


class TemplateNotFound(PlgError):
    status, code, message = 404, "PLG_TEMPLATE_NOT_FOUND", "공정 템플릿을 찾을 수 없습니다."


class NameTaken(PlgError):
    status, code, message = 409, "PLG_NAME_TAKEN", "같은 이름이 이미 있습니다."


class SimilarName(PlgError):
    status, code, message = (
        409,
        "PLG_SIMILAR_NAME",
        "비슷한 이름이 있습니다. 그래도 저장하려면 확인하세요.",
    )


class ConfirmRequired(PlgError):
    status, code, message = (
        409,
        "PLG_CONFIRM_REQUIRED",
        "입력 방식을 바꾸면 이 공정을 쓰는 템플릿에도 반영됩니다. 확인하세요.",
    )


class BuiltinLocked(PlgError):
    status, code, message = (
        409,
        "PLG_BUILTIN_LOCKED",
        "기본 제공 공정은 이 항목을 바꿀 수 없습니다.",
    )


class InUse(PlgError):
    status, code, message = (
        409,
        "PLG_IN_USE",
        "이미 쓰인 적이 있어 삭제할 수 없습니다. 사용 중지하세요.",
    )


class VersionConflict(PlgError):
    status, code, message = (
        409,
        "VERSION_CONFLICT",
        "다른 사용자가 먼저 수정했습니다. 최신 내용을 다시 불러오세요.",
    )


class TransactionRequired(PlgError):
    status, code, message = 500, "TRANSACTION_REQUIRED", "트랜잭션 안에서 호출해야 합니다."
