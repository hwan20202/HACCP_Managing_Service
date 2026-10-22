"""Optional number of pieces, independent of mass and never used to compute stock."""

from .errors import InventoryError


def optional_ea(value):
    if value in (None, ""):
        return None
    if isinstance(value, bool) or not str(value).isdigit():
        raise InventoryError("EA는 0 이상의 정수로 입력하세요.")
    result = int(value)
    if result > 9_000_000_000_000_000_000:
        raise InventoryError("EA 입력 범위를 초과했습니다.")
    return result
