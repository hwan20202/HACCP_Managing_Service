"""수불·생산 뷰 읽기 — REQ에서 뷰 이름이 나오는 유일한 곳(NFR-04).

뷰는 수불 앱(`apps.inventory`, sql/0001_core.sql·0002_production.sql)이 만든다(C2, D-128).
REQ 안에서 쓰는 키는 그대로 두고 여기서만 수불 컬럼을 바꿔 읽는다.
- `material_kind`: 수불 품목 구분 RAW → 원료, PACKAGING → 부자재(종이 양식 D03 "구분" 표기),
  그 밖은 구분 이름
- `quantity`·`unit`: 입고 수량 `quantity_e6` ÷ 10⁶, 품목 기준 단위 `base_unit`
- `origin`: 품목 원산지 `origin_country`
- `quantity_kg`(배치): 계획 수량(D-081 Q6 a)을 kg로 — 단위 kg·g은 환산, 그 밖은
  `unit_weight_mg`(V1)로, 못 바꾸면 NULL
"""

from django.db import OperationalError, connection

from . import errors

LOT_VIEW = "v_doc_incoming_lot"
BATCH_VIEW = "v_doc_batch"
LOT_SELECT = (
    ("lot_id", "lot_id"),
    ("lot_number", "lot_number"),
    ("lot_kind", "lot_kind"),
    ("item_id", "item_id"),
    ("item_name", "item_name"),
    (
        "material_kind",
        "CASE item_type WHEN 'RAW' THEN '원료' WHEN 'PACKAGING' THEN '부자재'"
        " ELSE item_type_name END",
    ),
    ("supplier_name", "supplier_name"),
    ("received_date", "received_date"),
    ("quantity", "quantity_e6 / 1000000.0"),
    ("unit", "base_unit"),
    ("expiration_date", "expiration_date"),
    ("origin", "origin_country"),
)
BATCH_SELECT = (
    ("production_batch_id", "production_batch_id"),
    ("batch_number", "batch_number"),
    ("item_id", "item_id"),
    ("item_name", "item_name"),
    ("process_type", "process_type"),
    ("status", "status"),
    ("manufactured_date", "manufactured_date"),
    (
        "quantity_kg",
        "CASE WHEN planned_quantity_e6 IS NULL THEN NULL"
        " WHEN base_unit = 'kg' THEN planned_quantity_e6 / 1000000.0"
        " WHEN base_unit = 'g' THEN planned_quantity_e6 / 1000000000.0"
        " WHEN unit_weight_mg IS NOT NULL"
        " THEN planned_quantity_e6 / 1000000.0 * unit_weight_mg / 1000000.0"
        " ELSE NULL END",
    ),
)
LOT_COLUMNS = tuple(key for key, _ in LOT_SELECT)
BATCH_COLUMNS = tuple(key for key, _ in BATCH_SELECT)


def _select(view, select, where, params, order=""):
    columns = [key for key, _ in select]
    exprs = ", ".join(expr if expr == key else f"{expr} AS {key}" for key, expr in select)
    sql = f"SELECT {exprs} FROM {view}{where}{order}"
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
    except OperationalError as error:
        if "no such table" in str(error):
            raise errors.SourceUnavailable() from error
        raise


def incoming_lot(lot_id):
    rows = _select(LOT_VIEW, LOT_SELECT, " WHERE lot_id = %s", [lot_id])
    return rows[0] if rows else None


def incoming_lots_on(day):
    """P7 REQ-BDL-02: 그날 입고 LOT 전부, LOT 번호 순(입고 뷰 received_date 조건)."""
    return _select(
        LOT_VIEW,
        LOT_SELECT,
        " WHERE received_date = %s AND lot_kind = 'INCOMING'",
        [day],
        " ORDER BY lot_number",
    )


def batch(batch_id):
    rows = _select(BATCH_VIEW, BATCH_SELECT, " WHERE production_batch_id = %s", [batch_id])
    return rows[0] if rows else None


def batches_by_ids(batch_ids):
    """P11 S5 r1: 배치 여러 개(대시보드 배치별 공정 순서 — 품목·공정 유형). 빈 목록이면 SQL 없음."""
    ids = sorted({int(i) for i in batch_ids})
    if not ids:
        return []
    marks = ", ".join(["%s"] * len(ids))
    # D-171: 생산 상태·시작/종료 일시(대시보드 정렬 — 생산중 → 생산 전 → 생산 종료, 시작 빠른 순)
    select = (
        *BATCH_SELECT,
        ("started_at", "started_at"),
        ("completed_at", "completed_at"),
        # D-172: 배치 영역 머리의 생산 수량(기준 단위) — 계획·산출
        ("planned_qty", "planned_quantity_e6 / 1000000.0"),
        ("output_qty", "output_quantity_e6 / 1000000.0"),
        ("unit", "base_unit"),
    )
    return _select(BATCH_VIEW, select, f" WHERE production_batch_id IN ({marks})", ids)


def lots_received_on(day=None, limit=100):
    """개발 목록(REQ-D01): 입고 LOT만, 최근순."""
    where, params = " WHERE lot_kind = 'INCOMING'", []
    if day:
        where, params = where + " AND received_date = %s", [day]
    return _select(LOT_VIEW, LOT_SELECT, where, params, f" ORDER BY lot_id DESC LIMIT {int(limit)}")


def batches_made_on(day=None, limit=100):
    """개발 목록(REQ-D02)."""
    where, params = "", []
    if day:
        where, params = " WHERE manufactured_date = %s", [day]
    return _select(
        BATCH_VIEW,
        BATCH_SELECT,
        where,
        params,
        f" ORDER BY production_batch_id DESC LIMIT {int(limit)}",
    )
