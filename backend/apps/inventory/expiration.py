"""소비기한 유무 (lots.expiration_status, 0007) and the date an incoming LOT is numbered by.

Confirmed (docs/history/planning/inventory-erd-review-20261014.md):
    원료 LOT 채번   소비기한 있음(KNOWN) -> LOT 약어 + 소비기한
                    소비기한 없음(NONE)  -> LOT 약어 + 입고일
    A missing date is not "없음": a raw material receipt must say KNOWN or NONE.
    Other incoming items (포장재, 구매 반제품) keep the received date; their status is recorded
    (KNOWN with a date, otherwise what was given, else UNKNOWN).

Scope (10/15): one LOT per receipt — a repeated base date gets -2, -3. Only the status is
stored: no per-item expiration policy and no new rule blocking NONE / UNKNOWN LOTs from use.
"""

from .errors import InventoryError
from .models import ExpirationStatus

RAW = "RAW"


def resolve_status(status, expiration_date, error=InventoryError):
    """Check status against the date. Returns the status, KNOWN when only a date is given, or
    None when neither is given (undetermined — the caller decides whether that is allowed)."""
    status = (status or "").strip().upper() or None
    if status is not None and status not in ExpirationStatus.values:
        raise error("소비기한 유무는 KNOWN(있음) / NONE(없음) / UNKNOWN(미확인) 중 하나입니다.")
    if status == ExpirationStatus.KNOWN and not expiration_date:
        raise error("소비기한 '있음'이면 소비기한 날짜를 입력하세요.")
    if status in (ExpirationStatus.NONE, ExpirationStatus.UNKNOWN) and expiration_date:
        raise error("소비기한 날짜가 있으면 소비기한 유무는 '있음'(KNOWN)입니다.")
    if status is None and expiration_date:
        return ExpirationStatus.KNOWN
    return status


def incoming_number_date(item, status, expiration_date, received_date, error=InventoryError):
    """(status to store, date to number the LOT by) for an incoming LOT."""
    if item.item_type_id == RAW:
        if status not in (ExpirationStatus.KNOWN, ExpirationStatus.NONE):
            raise error(
                "원료는 소비기한 유무를 '있음'(날짜 입력) 또는 '없음' 중 하나로 정해야 합니다. "
                "날짜를 비워 두는 것만으로는 '없음'으로 보지 않습니다."
            )
        return status, expiration_date if status == ExpirationStatus.KNOWN else received_date
    return status or ExpirationStatus.UNKNOWN, received_date
