"""REQ가 만드는 오류(s2-spec 2.3). 그 밖의 오류는 DOC·공통 코드를 그대로 올린다."""

from apps.core.http import ApiError


class RequirementError(ApiError):
    pass


class ValidationFailed(RequirementError):
    # DOC ValidationFailed와 같은 코드(VR-01). REQ는 DOC 오류 모듈을 import하지 않는다(NFR-03).
    status, code, message = 400, "VALIDATION_ERROR", "입력값을 확인하세요."


class TransactionRequired(RequirementError):
    status, code, message = 500, "TRANSACTION_REQUIRED", "트랜잭션 안에서 호출해야 합니다."


class LotNotFound(RequirementError):
    status, code, message = 404, "LOT_NOT_FOUND", "입고 LOT을 찾을 수 없습니다."


class LotNotIncoming(RequirementError):
    status, code, message = 409, "LOT_NOT_INCOMING", "입고 LOT이 아닙니다."


class BatchNotFound(RequirementError):
    status, code, message = 404, "BATCH_NOT_FOUND", "생산 배치를 찾을 수 없습니다."


class BatchCancelled(RequirementError):
    status, code, message = 409, "BATCH_CANCELLED", "취소된 생산 배치입니다."


class RequirementLimit(RequirementError):
    status, code, message = (
        409,
        "REQUIREMENT_LIMIT",
        "같은 날 육안검사 일지가 너무 많습니다(상한 9). HACCP 담당자에게 문의하세요.",
    )


class SourceUnavailable(RequirementError):
    # 수불·생산 뷰가 아직 없는 DB(운영 첫 배포 등). s2-spec 밖 — S4 구현 메모 G1
    status, code, message = 503, "REQ_SOURCE_MISSING", "수불·생산 뷰가 아직 준비되지 않았습니다."


class SimulatedFailure(RequirementError):
    # 개발 API D04·D05 fail_after 전용(롤백 확인)
    status, code, message = 500, "SIMULATED_FAILURE", "롤백 확인을 위한 의도된 실패입니다."
