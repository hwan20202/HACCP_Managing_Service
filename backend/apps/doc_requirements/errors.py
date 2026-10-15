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


class SourceUnavailable(RequirementError):
    # 수불·생산 뷰가 아직 없는 DB(운영 첫 배포 등). s2-spec 밖 — S4 구현 메모 G1
    status, code, message = 503, "REQ_SOURCE_MISSING", "수불·생산 뷰가 아직 준비되지 않았습니다."


class SimulatedFailure(RequirementError):
    # 개발 API D04·D05 fail_after 전용(롤백 확인)
    status, code, message = 500, "SIMULATED_FAILURE", "롤백 확인을 위한 의도된 실패입니다."


class RulesInvalid(RequirementError):
    # P9 VR-P9-01~05: 규칙 파일이 없거나 형식이 틀림 — 아무것도 만들지 않음(S1a-Q4 a)
    status, code, message = 500, "RULES_INVALID", "주기 규칙 파일이 올바르지 않습니다."


class NotPeriodic(RequirementError):
    # P9 VR-P9-11: 규칙 파일에 없는 양식으로 주기 문서를 직접 만들려 함
    status, code, message = 400, "NOT_PERIODIC", "주기 작성 요구 양식이 아닙니다."


class InvalidFilter(RequirementError):
    # P10 REQ-F10·A08: GET 목록 조회라 DOC F04·APR 결재함과 같은 코드(p10-s2-spec 2.1 B5)
    status, code, message = 400, "INVALID_FILTER", "조회 조건을 확인하세요."
