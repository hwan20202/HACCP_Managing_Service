"""Expiration date from an item's shelf life (소비기한).

Manufacturing method sheets state shelf life as "제조일로부터 24개월" (months); some items may use
days. items.shelf_life_months / shelf_life_days hold one of them (DB CHECK: not both).

    add_months(2026-10-13, 24) -> 2028-10-13
    month end is kept in range: 2026-01-31 + 1 month -> 2026-02-28

The label date is the day before (10/14 PM 미팅 B3: 하루 전이 원칙, 같은 날도 법적 문제는 없음):
    expiration_for(item, 2026-10-13)  with 24 months -> 2028-10-12
The manufacturing date is the batch's 생산 시작일 (B2).
"""

import calendar
import datetime

END_DAY_OFFSET = datetime.timedelta(days=-1)  # 하루 전 (10/14 PM 미팅 B3)


def add_months(day, months):
    month_index = day.month - 1 + months
    year, month = day.year + month_index // 12, month_index % 12 + 1
    return datetime.date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def expiration_for(item, manufactured_date):
    """Expiration date for a LOT of `item` made on `manufactured_date`, or None if unknown."""
    if manufactured_date is None:
        return None
    if item.shelf_life_months:
        return add_months(manufactured_date, item.shelf_life_months) + END_DAY_OFFSET
    if item.shelf_life_days:
        return manufactured_date + datetime.timedelta(days=item.shelf_life_days) + END_DAY_OFFSET
    return None
