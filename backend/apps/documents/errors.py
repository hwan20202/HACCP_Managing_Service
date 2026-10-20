"""문서 도메인 예외. code·status는 API 공통 오류 응답에 그대로 쓰인다(s2-spec 4.3)."""

from apps.core.http import ApiError


class DocumentError(ApiError):
    pass


class ValidationFailed(DocumentError):
    status, code, message = 400, "VALIDATION_ERROR", "입력값을 확인하세요."


class NoChanges(DocumentError):
    status, code, message = 400, "NO_CHANGES", "바꿀 내용이 없습니다."


class InvalidFilter(DocumentError):
    status, code, message = 400, "INVALID_FILTER", "조회 조건을 확인하세요."


class TemplateNotFound(DocumentError):
    status, code, message = 404, "TEMPLATE_NOT_FOUND", "양식을 찾을 수 없습니다."


class DocumentNotFound(DocumentError):
    status, code, message = 404, "DOCUMENT_NOT_FOUND", "문서를 찾을 수 없습니다."


class TemplateInactive(DocumentError):
    status, code, message = 409, "TEMPLATE_INACTIVE", "사용할 수 없는 양식입니다."


class DocumentLocked(DocumentError):
    status, code, message = 409, "DOCUMENT_LOCKED", "현재 상태에서는 문서를 수정할 수 없습니다."


class DocumentNotDeletable(DocumentError):
    status, code, message = (
        409,
        "DOCUMENT_NOT_DELETABLE",
        "현재 상태이거나 상신 이력이 있어 삭제할 수 없습니다.",
    )


class VersionConflict(DocumentError):
    status, code, message = (
        409,
        "VERSION_CONFLICT",
        "다른 사용자가 먼저 수정했습니다. 최신 내용을 다시 불러오세요.",
    )


class SectionRowNotFound(DocumentError):
    status, code, message = 409, "SECTION_ROW_NOT_FOUND", "대상 행이 이 문서에 없습니다."


class DuplicateRound(DocumentError):
    status, code, message = 409, "DUPLICATE_ROUND", "같은 측정시점이 이미 있습니다."


class InvalidTransition(DocumentError):
    status, code, message = 409, "INVALID_TRANSITION", "현재 상태에서 할 수 없는 상태 변경입니다."


class TransactionRequired(DocumentError):
    """생명주기 전이 함수는 WF가 연 트랜잭션 안에서만 호출한다(S2-Q6)."""

    status, code, message = 500, "TRANSACTION_REQUIRED", "트랜잭션 안에서 호출해야 합니다."


class TemplateRequirementOnly(DocumentError):
    status, code, message = (
        409,
        "TEMPLATE_REQUIREMENT_ONLY",
        "이 양식은 입고·생산 시작 때 자동으로 만들어집니다.",
    )


class CompletionIncomplete(DocumentError):
    status, code, message = (
        400,
        "COMPLETION_INCOMPLETE",
        "작성완료할 수 없습니다. 빠진 항목을 채우세요.",
    )


class DeviationNotFound(DocumentError):
    status, code, message = 404, "DEVIATION_NOT_FOUND", "개선조치를 찾을 수 없습니다."


class CorrectionHasChanges(DocumentError):
    """정정 시작 뒤 수정한 문서는 정정을 취소할 수 없다(D-075, P6-FR-16)."""

    status, code, message = (
        409,
        "CORRECTION_HAS_CHANGES",
        "정정 시작 뒤 수정한 내용이 있어 취소할 수 없습니다. 작성완료 후 재상신하세요.",
    )


# ---------------------------------------------------------------- 파일(F14~F18, 스프린트 3 — D-058)


class FilesNotAllowed(DocumentError):
    status, code, message = 409, "FILES_NOT_ALLOWED", "이 양식은 파일을 첨부하지 않습니다."


class FileRejected(DocumentError):
    """details[].reason = type / size / name (DOC-VR-20)."""

    status, code, message = 400, "FILE_REJECTED", "올릴 수 없는 파일입니다."


class FileNotFound(DocumentError):
    status, code, message = 404, "FILE_NOT_FOUND", "파일을 찾을 수 없습니다."


class FileNotLinked(DocumentError):
    status, code, message = 409, "FILE_NOT_LINKED", "이 문서에 연결된 파일이 아닙니다."


class FileAlreadyLinked(DocumentError):
    status, code, message = 409, "FILE_ALREADY_LINKED", "이미 연결된 파일입니다."


class FileTemplateMismatch(DocumentError):
    status, code, message = (
        409,
        "FILE_TEMPLATE_MISMATCH",
        "다른 종류 문서의 파일은 연결할 수 없습니다.",
    )


class DocumentNotSkippable(DocumentError):
    """P8 VR-P8-05: 작성 안 함은 skippable 양식의 작성 요구 문서(record_key)만."""

    status, code, message = (
        409,
        "DOCUMENT_NOT_SKIPPABLE",
        "작성 안 함으로 바꿀 수 없는 문서입니다(주기 작성 요구 문서만).",
    )


class AlreadyChecked(DocumentError):
    # P11 F31: 다른 확인자가 먼저 확인(p11-s2-spec 3.3). details에 checked_by·checked_at
    status, code, message = 409, "ALREADY_CHECKED", "이미 확인된 개선조치입니다."


class NotChecker(DocumentError):
    # P11 F31: 현재 사용자가 이 개선조치의 확인자가 아님 · P14 R05: 팀장도 아님
    status, code, message = 403, "NOT_CHECKER", "확인자나 HACCP팀장만 확인할 수 있습니다."
