"""원료수불대장 CSV download. Opens in Excel (UTF-8 with BOM)."""

import csv

from django.http import HttpResponse

from .api import endpoint, ledger_search
from .ledger import stock_ledger
from .models import ExpirationStatus
from .quantity import from_e6

HEADER = [
    "품목코드",
    "품목명",
    "품목유형",
    "단위",
    "LOT",
    "소비기한",
    "일시",
    "구분",
    "입고(+)",
    "출고(-)",
    "잔량",
    "사유",
    "담당자",
]


def _num(value_e6):
    return "" if not value_e6 else str(from_e6(value_e6))


@endpoint("GET")
def ledger_csv(request):
    params = ledger_search(request)
    date_from, date_to = params.pop("date_from"), params.pop("date_to")
    items = stock_ledger(date_from, date_to, **params)

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    filename = f"stock-ledger-{date_from:%Y%m%d}-{date_to:%Y%m%d}.csv"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write("﻿")
    writer = csv.writer(response)
    writer.writerow([f"원료수불대장 {date_from} ~ {date_to}"])
    writer.writerow(HEADER)
    for item in items:
        base = [item.item_code, item.item_name, item.item_type, item.base_unit]
        for lot in item.lots:
            # 날짜가 없으면 '없음'(NONE)과 '미확인'(UNKNOWN)을 구분해 적는다 (0007)
            expiry = lot.expiration_date or ExpirationStatus(lot.expiration_status).label
            lot_cols = [lot.lot_number, expiry]
            writer.writerow(
                [
                    *base,
                    *lot_cols,
                    f"{date_from} 이전",
                    "이월",
                    "",
                    "",
                    str(from_e6(lot.opening_e6)),
                    "",
                    "",
                ]
            )
            for line in lot.lines:
                signed = line.signed_quantity_e6
                writer.writerow(
                    [
                        *base,
                        *lot_cols,
                        line.occurred_at.strftime("%Y-%m-%d %H:%M"),
                        line.movement_name,
                        _num(signed if signed > 0 else 0),
                        _num(-signed if signed < 0 else 0),
                        str(from_e6(line.balance_e6)),
                        line.reason or "",
                        line.staff_name,
                    ]
                )
        writer.writerow(
            [
                *base,
                "품목 합계",
                "",
                "",
                "",
                _num(item.in_e6),
                _num(item.out_e6),
                str(from_e6(item.closing_e6)),
                "",
                "",
            ]
        )
    return response
