"""Expiration date from an item's shelf life (소비기한).

Manufacturing method sheets state shelf life as "제조일로부터 24개월" (months); some items may use
days. items.shelf_life_months / shelf_life_days hold one of them (DB CHECK: not both).

    expiration_for(item, 2026-10-13)  with 24 months -> 2028-10-13
    month end is kept in range: 2026-01-31 + 1 month -> 2026-02-28

Whether the label date is that day or the day before ("~까지") is not confirmed with PM yet;
change END_DAY_OFFSET in one place when it is.
"""

import calendar
import datetime

END_DAY_OFFSET = datetime.timedelta(days=0)  # PM 확인 대기: 표시 관행이 하루 전이면 -1일


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
