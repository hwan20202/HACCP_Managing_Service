"""수불·생산 뷰 읽기 — REQ에서 뷰 이름이 나오는 유일한 곳(NFR-04).

뷰 계약: dev-notes/interfaces/doc_views.sql. 개발에서는 devstock이 같은 이름의 뷰를 만든다(D-069).
"""

from django.db import OperationalError, connection

from . import errors

LOT_VIEW = "v_doc_incoming_lot"
BATCH_VIEW = "v_doc_batch"
LOT_COLUMNS = (
    "lot_id",
    "lot_number",
    "lot_kind",
    "item_id",
    "item_name",
    "material_kind",
    "supplier_name",
    "received_date",
    "quantity",
    "unit",
    "expiration_date",
    "origin",
)
BATCH_COLUMNS = (
    "production_batch_id",
    "batch_number",
    "item_id",
    "item_name",
    "process_type",
    "status",
    "manufactured_date",
    "quantity_kg",
)


def _select(view, columns, where, params, order=""):
    sql = f"SELECT {', '.join(columns)} FROM {view}{where}{order}"
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
    except OperationalError as error:
        if "no such table" in str(error):
            raise errors.SourceUnavailable() from error
        raise


def incoming_lot(lot_id):
    rows = _select(LOT_VIEW, LOT_COLUMNS, " WHERE lot_id = %s", [lot_id])
    return rows[0] if rows else None


def incoming_lots_on(day):
    """P7 REQ-BDL-02: 그날 입고 LOT 전부, LOT 번호 순(입고 뷰 received_date 조건)."""
    return _select(
        LOT_VIEW,
        LOT_COLUMNS,
        " WHERE received_date = %s AND lot_kind = 'INCOMING'",
        [day],
        " ORDER BY lot_number",
    )


def batch(batch_id):
    rows = _select(BATCH_VIEW, BATCH_COLUMNS, " WHERE production_batch_id = %s", [batch_id])
    return rows[0] if rows else None


def lots_received_on(day=None, limit=100):
    """개발 목록(REQ-D01): 입고 LOT만, 최근순."""
    where, params = " WHERE lot_kind = 'INCOMING'", []
    if day:
        where, params = where + " AND received_date = %s", [day]
    return _select(
        LOT_VIEW, LOT_COLUMNS, where, params, f" ORDER BY lot_id DESC LIMIT {int(limit)}"
    )


def batches_made_on(day=None, limit=100):
    """개발 목록(REQ-D02)."""
    where, params = "", []
    if day:
        where, params = " WHERE manufactured_date = %s", [day]
    return _select(
        BATCH_VIEW,
        BATCH_COLUMNS,
        where,
        params,
        f" ORDER BY production_batch_id DESC LIMIT {int(limit)}",
    )
