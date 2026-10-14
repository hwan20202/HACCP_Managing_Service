"""Current stock queries: per LOT, per item, expiring LOTs.

"Usable" follows I5 / v_lot_availability: status AVAILABLE and no open hold.
Quantities are *_e6 integers (rule S3).
"""

import datetime
from dataclasses import dataclass

from django.db import connection

from .fields import kst_now


@dataclass
class LotStock:
    lot_id: int
    lot_number: str
    lot_kind: str
    status: str
    item_id: int
    item_code: str
    item_name: str
    item_type: str
    base_unit: str
    quantity_e6: int
    is_usable: bool
    active_hold_count: int
    manufactured_date: datetime.date | None
    expiration_date: datetime.date | None
    received_date: datetime.date | None
    supplier_name: str | None
    days_to_expiry: int | None
    expiration_status: str  # KNOWN 있음 / NONE 없음 / UNKNOWN 미확인 (0007)


@dataclass
class ItemStock:
    item_id: int
    item_code: str
    item_name: str
    item_type: str
    base_unit: str
    minimum_stock_e6: int
    total_e6: int
    usable_e6: int
    quarantine_e6: int
    unusable_e6: int  # REJECTED, or AVAILABLE but on hold
    lot_count: int
    nearest_expiration: datetime.date | None

    @property
    def below_minimum(self):
        return self.minimum_stock_e6 > 0 and self.usable_e6 < self.minimum_stock_e6


def _date(value):
    return datetime.date.fromisoformat(value) if value else None


def item_type_codes(item_type):
    """'RAW' / 'SEMI,FINISHED' / ['SEMI', 'FINISHED'] / None -> list of codes (empty = all)."""
    if not item_type:
        return []
    if isinstance(item_type, str):
        item_type = item_type.split(",")
    return [code.strip().upper() for code in item_type if code and code.strip()]


def item_type_clause(item_type):
    """SQL clause on i.item_type and its params, or (None, []) for all types."""
    codes = item_type_codes(item_type)
    if not codes:
        return None, []
    return f"i.item_type IN ({', '.join(['%s'] * len(codes))})", codes


def lot_stock(
    *,
    item_type=None,
    item_id=None,
    status=None,
    include_empty=False,
    expiring_within_days=None,
    today=None,
    lot_number=None,
    manufactured_from=None,
    manufactured_to=None,
    expiration_status=None,
):
    """LOTs with their current quantity, ordered by item code then expiration (FEFO).

    item_type: one code or several ('SEMI,FINISHED'). lot_number: part of the LOT number.
    manufactured_from / _to: 제조일 (lots.manufactured_date, 생산 LOT 검색용) — not 수불 dates.
    LOTs without a 소비기한 date come after the dated ones, oldest received (or made) first.
    """
    today = today or kst_now().date()
    clauses, params = ["i.is_active = 1 OR inv.quantity_e6 > 0"], []
    if not include_empty:
        clauses.append("inv.quantity_e6 > 0")
    type_clause, type_params = item_type_clause(item_type)
    if type_clause:
        clauses.append(type_clause)
        params.extend(type_params)
    if lot_number:
        clauses.append("l.lot_number LIKE %s")
        params.append(f"%{lot_number.strip()}%")
    if manufactured_from:
        clauses.append("l.manufactured_date >= %s")
        params.append(manufactured_from.isoformat())
    if manufactured_to:
        clauses.append("l.manufactured_date <= %s")
        params.append(manufactured_to.isoformat())
    if expiration_status:
        clauses.append("l.expiration_status = %s")
        params.append(expiration_status)
    if item_id:
        clauses.append("i.id = %s")
        params.append(item_id)
    if status:
        clauses.append("l.status = %s")
        params.append(status)
    if expiring_within_days is not None:
        clauses.append("l.expiration_date IS NOT NULL AND l.expiration_date <= %s")
        params.append((today + datetime.timedelta(days=expiring_within_days)).isoformat())
    where = " AND ".join(f"({clause})" for clause in clauses)
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT l.id, l.lot_number, l.lot_kind, l.status,
                   i.id, i.item_code, i.name, i.item_type, i.base_unit,
                   COALESCE(inv.quantity_e6, 0), a.is_usable, a.active_hold_count,
                   l.manufactured_date, l.expiration_date, r.received_date, s.name,
                   l.expiration_status
            FROM lots l
            JOIN items i               ON i.id = l.item_id
            JOIN v_lot_availability a  ON a.lot_id = l.id
            LEFT JOIN inventory inv    ON inv.lot_id = l.id
            LEFT JOIN incoming_receipts r ON r.lot_id = l.id
            LEFT JOIN suppliers s      ON s.id = r.supplier_id
            WHERE {where}
            ORDER BY i.item_code, l.expiration_date IS NULL, l.expiration_date,
                     COALESCE(r.received_date, l.manufactured_date), l.lot_number
            """,
            params,
        )
        rows = cursor.fetchall()
    result = []
    for row in rows:
        expiration = _date(row[13])
        result.append(
            LotStock(
                *row[:10],
                bool(row[10]),
                row[11],
                _date(row[12]),
                expiration,
                _date(row[14]),
                row[15],
                (expiration - today).days if expiration else None,
                row[16],
            )
        )
    return result


def item_stock(*, item_type=None, item_id=None, include_inactive=False, today=None):
    """Stock totals per item, including active items with no stock (for minimum-stock checks)."""
    lots = lot_stock(item_type=item_type, item_id=item_id, today=today)
    clauses, params = [], []
    if not include_inactive:
        clauses.append("is_active = 1")
    type_clause, type_params = item_type_clause(item_type)
    if type_clause:
        clauses.append(type_clause.replace("i.item_type", "item_type"))
        params.extend(type_params)
    if item_id:
        clauses.append("id = %s")
        params.append(item_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id, item_code, name, item_type, base_unit, minimum_stock_e6 FROM items "
            f"{where} ORDER BY item_code",
            params,
        )
        items = {row[0]: ItemStock(*row, 0, 0, 0, 0, 0, None) for row in cursor.fetchall()}
    for lot in lots:
        item = items.get(lot.item_id)
        if item is None:  # inactive item that still holds stock
            continue
        item.total_e6 += lot.quantity_e6
        item.lot_count += 1
        if lot.is_usable:
            item.usable_e6 += lot.quantity_e6
            if lot.expiration_date and (
                item.nearest_expiration is None or lot.expiration_date < item.nearest_expiration
            ):
                item.nearest_expiration = lot.expiration_date
        elif lot.status == "QUARANTINE":
            item.quarantine_e6 += lot.quantity_e6
        else:
            item.unusable_e6 += lot.quantity_e6
    return list(items.values())
