"""원료수불대장 (stock ledger) for a period.

For each LOT with stock activity: opening balance (before the period), every movement in the
period with the running balance, inflow / outflow totals and the closing balance. LOTs are
grouped by item with item totals.

Period bounds are dates, both inclusive: date_from 00:00:00 <= occurred_at < date_to + 1 day.
Quantities are *_e6 integers (rule S3); format with quantity.from_e6 for display.

The query reads the base tables rather than v_stock_ledger because the view has no lot / item
ids. SchemaTests keep the two in agreement (see test_ledger.py).
"""

import datetime
from dataclasses import dataclass, field

from django.db import connection

from .fields import parse_kst_text, to_kst_text
from .stock import item_type_clause


@dataclass
class LedgerLine:
    movement_id: int
    occurred_at: datetime.datetime
    movement_code: str
    movement_name: str
    signed_quantity_e6: int
    balance_e6: int
    reason: str | None
    staff_name: str
    corrects_movement_id: int | None


@dataclass
class LedgerLot:
    lot_id: int
    lot_number: str
    status: str
    expiration_date: datetime.date | None
    expiration_status: str = "UNKNOWN"  # KNOWN 있음 / NONE 없음 / UNKNOWN 미확인 (0007)
    opening_e6: int = 0
    in_e6: int = 0
    out_e6: int = 0
    lines: list[LedgerLine] = field(default_factory=list)

    @property
    def closing_e6(self):
        return self.opening_e6 + self.in_e6 - self.out_e6


@dataclass
class LedgerItem:
    item_id: int
    item_code: str
    item_name: str
    item_type: str
    base_unit: str
    lots: list[LedgerLot] = field(default_factory=list)

    @property
    def opening_e6(self):
        return sum(lot.opening_e6 for lot in self.lots)

    @property
    def in_e6(self):
        return sum(lot.in_e6 for lot in self.lots)

    @property
    def out_e6(self):
        return sum(lot.out_e6 for lot in self.lots)

    @property
    def closing_e6(self):
        return sum(lot.closing_e6 for lot in self.lots)


_BASE = """
FROM stock_movements m
JOIN stock_movement_types t ON t.code = m.movement_type_code
JOIN lots l                 ON l.id = m.lot_id
JOIN items i                ON i.id = l.item_id
"""


def _filters(item_type, item_id, lot_id, lot_number=None):
    clauses, params = [], []
    type_clause, type_params = item_type_clause(item_type)
    if type_clause:
        clauses.append(type_clause)
        params.extend(type_params)
    if lot_number:
        clauses.append("l.lot_number LIKE %s")
        params.append(f"%{lot_number.strip()}%")
    if item_id:
        clauses.append("i.id = %s")
        params.append(item_id)
    if lot_id:
        clauses.append("l.id = %s")
        params.append(lot_id)
    return clauses, params


def stock_ledger(date_from, date_to, *, item_type=None, item_id=None, lot_id=None, lot_number=None):
    """Return list[LedgerItem] ordered by item code, LOT number, then time.

    A LOT appears when it has a non-zero opening balance or any movement in the period.
    Dates are 수불 dates (stock_movements.occurred_at). item_type: one code or several
    ('SEMI,FINISHED'); lot_number: part of the LOT number.
    """
    if date_to < date_from:
        raise ValueError("date_to must not be before date_from.")
    start = date_from.isoformat()
    end = (date_to + datetime.timedelta(days=1)).isoformat()
    clauses, params = _filters(item_type, item_id, lot_id, lot_number)
    extra = "".join(f" AND {clause}" for clause in clauses)

    item_cols = "i.id, i.item_code, i.name, i.item_type, i.base_unit"
    lot_cols = "l.id, l.lot_number, l.status, l.expiration_date, l.expiration_status"
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT {item_cols}, {lot_cols}, SUM(m.quantity_e6 * t.direction) {_BASE}"
            f" WHERE m.occurred_at < %s{extra}"
            f" GROUP BY l.id HAVING SUM(m.quantity_e6 * t.direction) <> 0",
            [start, *params],
        )
        openings = cursor.fetchall()
        cursor.execute(
            f"SELECT {item_cols}, {lot_cols}, m.id, m.occurred_at, t.code, t.name,"
            f" m.quantity_e6 * t.direction, m.reason, st.name, m.corrects_movement_id"
            f" {_BASE} JOIN staff st ON st.id = m.staff_id"
            f" WHERE m.occurred_at >= %s AND m.occurred_at < %s{extra}"
            f" ORDER BY i.item_code, l.lot_number, m.occurred_at, m.id",
            [start, end, *params],
        )
        movements = cursor.fetchall()

    items, lots = {}, {}

    def lot_for(row):
        item_id_, code, name, type_, unit, lot_id_, number, status, expiration, exp_status = row[
            :10
        ]
        if item_id_ not in items:
            items[item_id_] = LedgerItem(item_id_, code, name, type_, unit)
        if lot_id_ not in lots:
            lot = LedgerLot(
                lot_id_,
                number,
                status,
                datetime.date.fromisoformat(expiration) if expiration else None,
                exp_status,
            )
            lots[lot_id_] = lot
            items[item_id_].lots.append(lot)
        return lots[lot_id_]

    for row in openings:
        lot_for(row).opening_e6 = row[10]
    balances = {}
    for row in movements:
        lot = lot_for(row)
        movement_id, occurred_at, code, name, signed, reason, staff, corrects = row[10:]
        balance = balances.get(lot.lot_id, lot.opening_e6) + signed
        balances[lot.lot_id] = balance
        if signed > 0:
            lot.in_e6 += signed
        else:
            lot.out_e6 -= signed
        lot.lines.append(
            LedgerLine(
                movement_id,
                parse_kst_text(occurred_at),
                code,
                name,
                signed,
                balance,
                reason,
                staff,
                corrects,
            )
        )

    result = sorted(items.values(), key=lambda item: item.item_code)
    for item in result:
        item.lots.sort(key=lambda lot: lot.lot_number)
    return result


@dataclass
class LedgerChange:
    movement_id: int
    lot_id: int
    lot_number: str
    item_id: int
    item_code: str
    occurred_at: datetime.datetime
    created_at: datetime.datetime
    movement_code: str
    movement_name: str
    signed_quantity_e6: int
    reason: str | None
    staff_name: str
    corrects_movement_id: int | None
    affects: str  # "OPENING" (before date_from: changes the carried-over balance) or "PERIOD"


def stock_ledger_changes_since(
    since, date_from, date_to, *, item_type=None, item_id=None, lot_id=None
):
    """Movements recorded at or after `since` that change the ledger for date_from..date_to.

    For checking whether an approved ledger is still current. A movement matters when it was
    recorded (created_at) at or after the approval and happened (occurred_at) before the end
    of the period: before date_from it changes the opening balance, inside the period it
    changes the lines. Corrections carry the original's occurred_at, so they are caught too.

    `since` is compared at second precision and inclusively, so a movement recorded in the
    same second as the approval is reported (a false alarm is safer than a missed change).
    LOT / item master changes (expiration date, names) are not movements and are not covered.
    """
    if date_to < date_from:
        raise ValueError("date_to must not be before date_from.")
    since_text = to_kst_text(since) if isinstance(since, datetime.datetime) else str(since)
    start = date_from.isoformat()
    end = (date_to + datetime.timedelta(days=1)).isoformat()
    clauses, params = _filters(item_type, item_id, lot_id)
    extra = "".join(f" AND {clause}" for clause in clauses)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT m.id, l.id, l.lot_number, i.id, i.item_code, m.occurred_at, m.created_at,"
            " t.code, t.name, m.quantity_e6 * t.direction, m.reason, st.name,"
            " m.corrects_movement_id"
            f" {_BASE} JOIN staff st ON st.id = m.staff_id"
            f" WHERE m.created_at >= %s AND m.occurred_at < %s{extra}"
            " ORDER BY m.created_at, m.id",
            [since_text, end, *params],
        )
        rows = cursor.fetchall()
    return [
        LedgerChange(
            *row[:5],
            parse_kst_text(row[5]),
            parse_kst_text(row[6]),
            *row[7:],
            "OPENING" if row[5] < start else "PERIOD",
        )
        for row in rows
    ]
