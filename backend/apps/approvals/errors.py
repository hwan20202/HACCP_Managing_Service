"""결재 도메인 예외 (approval/s2-spec.md 3.4)."""

from apps.core.http import ApiError


class ApprovalError(ApiError):
    pass


class InvalidSlots(ApprovalError):
    status, code, message = 400, "INVALID_SLOTS", "결재선(슬롯)을 확인하세요."


class InvalidDecision(ApprovalError):
    status, code, message = 400, "INVALID_DECISION", "결재 처리 값을 확인하세요."


class CommentRequired(ApprovalError):
    status, code, message = 400, "COMMENT_REQUIRED", "반려 사유를 입력하세요."


class InvalidFilter(ApprovalError):
    status, code, message = 400, "INVALID_FILTER", "조회 조건을 확인하세요."


class NotYourSlot(ApprovalError):
    status, code, message = (
        403,
        "NOT_YOUR_SLOT",
        "이 결재 칸을 처리할 수 있는 사람(결재자·후보)이 아닙니다.",
    )


class NotRequester(ApprovalError):
    # P10 A7 상신 취소(p10-s2-spec 3.2) — P14: 팀장도 취소(ROLE-R02)
    status, code, message = 403, "NOT_REQUESTER", "상신한 사람이나 HACCP팀장만 취소할 수 있습니다."


class ApprovalNotFound(ApprovalError):
    status, code, message = 404, "APPROVAL_NOT_FOUND", "결재 칸을 찾을 수 없습니다."


class RequestNotFound(ApprovalError):
    status, code, message = 404, "REQUEST_NOT_FOUND", "결재 요청을 찾을 수 없습니다."


class OpenRequestExists(ApprovalError):
    status, code, message = 409, "OPEN_REQUEST_EXISTS", "이 문서는 이미 결재 진행 중입니다."


class RequestClosed(ApprovalError):
    status, code, message = 409, "REQUEST_CLOSED", "이미 끝난 결재 요청입니다."


class AlreadyDecided(ApprovalError):
    status, code, message = 409, "ALREADY_DECIDED", "이미 처리한 결재 칸입니다."


class TransactionRequired(ApprovalError):
    status, code, message = 500, "TRANSACTION_REQUIRED", "트랜잭션 안에서 호출해야 합니다."
