"""EFF 오류. code·status는 API 공통 오류 응답에 그대로 쓰인다(p6-s2-spec 4.6)."""

from apps.core.http import ApiError


class InventoryRejected(ApiError):
    """인벤토리가 판정을 받지 않음 → 작성완료 롤백(P6-FR-20).

    details = [{lot_id, lot_number, message}] 1건(P6a: LOT마다 문서).
    """

    status, code, message = 409, "INVENTORY_REJECTED", "수불이 판정을 받지 않았습니다."


class InventoryNotConfigured(ApiError):
    """판정 함수 설정(HACCP_INVENTORY_JUDGMENT)이 없음 — 육안검사 작성완료 불가(P6 S4b G2)."""

    status, code, message = (
        503,
        "INVENTORY_NOT_CONFIGURED",
        "수불 판정 연동이 설정되지 않아 육안검사를 작성완료할 수 없습니다.",
    )
