"""JSON API for inventory: /api/v1/inventory/...

Conventions
- Request bodies are JSON. Numbers are read as Decimal, so 0.1 stays 0.1; quantities may
  also be sent as strings ("50.25"). Quantities are in the item's base unit.
- Responses: a list is {"results": [...]} (+ "count" when paginated); one record is the object.
- Errors: {"error": {"message": "<Korean, show to user>", "fields": {...}?}} with
  400 (invalid request), 404 (not found), 405 (method), 409 (conflict).
- CSRF: the CSRF middleware is on. GET responses set the csrftoken cookie; send it back in
  the X-CSRFToken header on POST / PATCH.
- No login yet (MVP): the acting person is sent as staff_id in the body.
"""

import datetime
import functools
import json
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.csrf import ensure_csrf_cookie

from apps.core.http import ApiError

from . import serializers as out
from .errors import InventoryError, NotFound
from .fields import KST
from .holds import hold_batch, hold_lot, release_hold
from .judgment import apply_incoming_judgment
from .ledger import stock_ledger, stock_ledger_changes_since
from .master_import import parse_item_row, parse_staff_row, parse_supplier_row
from .models import (
    BatchStatus,
    Bom,
    BomLine,
    ExpirationStatus,
    Hold,
    IncomingReceipt,
    Inventory,
    Item,
    ItemType,
    Lot,
    LotStatus,
    ProcessType,
    ProductionBatch,
    ReceiptStatus,
    Staff,
    StockMovement,
    StockMovementType,
    Supplier,
)
from .movements import (
    adjust_stock,
    correct_movement,
    dispose,
    record_opening_balance,
    return_to_supplier,
)
from .production import (
    add_output,
    add_usage,
    add_usages,
    batch_summary,
    cancel_batch,
    complete_batch,
    create_batch,
    fefo_candidates,
    material_readiness,
    start_batch,
)
from .quantity import from_e6, to_e6
from .receiving import ReceiptInput, cancel_receipt, register_receipt
from .stock import item_stock, lot_stock

MAX_PAGE = 500


class BadRequest(InventoryError):
    def __init__(self, message, fields=None):
        super().__init__(message)
        self.fields = fields


class Conflict(InventoryError):
    pass


def error_response(status, message, fields=None, code=None):
    body = {"message": message}
    if code:
        body["code"] = code
    if fields:
        body["fields"] = fields
    return JsonResponse({"error": body}, status=status, json_dumps_params={"ensure_ascii": False})


def ok(data, status=200):
    return JsonResponse(data, status=status, json_dumps_params={"ensure_ascii": False})


def endpoint(*methods):
    """Method check, JSON body parsing and error mapping for one view."""

    def decorate(view):
        @functools.wraps(view)
        def wrapper(request, *args, **kwargs):
            if request.method not in methods:
                return error_response(405, f"허용되지 않는 요청 방식입니다: {request.method}")
            if request.method in {"POST", "PATCH"}:
                try:
                    body = json.loads(request.body or b"{}", parse_float=Decimal)
                except ValueError, UnicodeDecodeError:
                    return error_response(400, "요청 본문이 올바른 JSON이 아닙니다.")
                if not isinstance(body, dict):
                    return error_response(400, "요청 본문은 JSON 객체여야 합니다.")
                request.data = body
            try:
                return view(request, *args, **kwargs)
            except NotFound as error:
                return error_response(404, str(error))
            except Conflict as error:
                return error_response(409, str(error))
            except BadRequest as error:
                return error_response(400, str(error), error.fields)
            except InventoryError as error:
                return error_response(400, str(error))
            except ApiError as error:  # raised by the document app inside a hook (rolled back)
                return error_response(error.status, error.message, error.details, error.code)

        wrapped = ensure_csrf_cookie(wrapper) if "GET" in methods else wrapper
        return wrapped

    return decorate


# ---------------------------------------------------------------------------
# Parameter helpers
# ---------------------------------------------------------------------------


def _date(value, name, required=False):
    if value in (None, ""):
        if required:
            raise BadRequest(f"'{name}' 값이 필요합니다.", {name: "required"})
        return None
    try:
        return datetime.date.fromisoformat(str(value))
    except ValueError as error:
        raise BadRequest(f"'{name}' 는 YYYY-MM-DD 형식이어야 합니다.", {name: "invalid"}) from error


def _datetime(value, name):
    """'YYYY-MM-DD' -> date (start of day), ISO datetime -> datetime (naive = KST)."""
    if value in (None, ""):
        return None
    text = str(value)
    if len(text) == 10:
        return _date(text, name)
    try:
        parsed = datetime.datetime.fromisoformat(text)
    except ValueError as error:
        raise BadRequest(f"'{name}' 일시 형식을 확인하세요.", {name: "invalid"}) from error
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=KST)


def _int(value, name, required=False):
    if value in (None, ""):
        if required:
            raise BadRequest(f"'{name}' 값이 필요합니다.", {name: "required"})
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise BadRequest(f"'{name}' 는 정수여야 합니다.", {name: "invalid"}) from error


def _flag(value):
    return str(value).lower() in {"1", "true", "yes", "y"}


def _required(data, *names):
    missing = {name: "required" for name in names if data.get(name) in (None, "")}
    if missing:
        raise BadRequest(f"필수 항목이 없습니다: {', '.join(missing)}", missing)


def _page(request, queryset):
    limit = min(_int(request.GET.get("limit"), "limit") or 100, MAX_PAGE)
    offset = _int(request.GET.get("offset"), "offset") or 0
    return queryset.count(), queryset[offset : offset + limit]


def _get(model, pk, label):
    obj = model.objects.filter(pk=pk).first()
    if obj is None:
        raise NotFound(f"{label}을(를) 찾을 수 없습니다. (id={pk})")
    return obj


# ---------------------------------------------------------------------------
# Reference codes
# ---------------------------------------------------------------------------


@endpoint("GET")
def item_types(request):
    rows = ItemType.objects.order_by("sort_order")
    return ok({"results": [{"code": r.code, "name": r.name} for r in rows]})


@endpoint("GET")
def movement_types(request):
    rows = StockMovementType.objects.order_by("code")
    return ok(
        {"results": [{"code": r.code, "name": r.name, "direction": r.direction} for r in rows]}
    )


# ---------------------------------------------------------------------------
# Master data: staff / suppliers / items
# ---------------------------------------------------------------------------

MASTER = {
    "staff": (Staff, "staff_code", parse_staff_row, out.staff, "담당자"),
    "suppliers": (Supplier, "supplier_code", parse_supplier_row, out.supplier, "공급처"),
    "items": (Item, "item_code", parse_item_row, out.item, "품목"),
}


def _master_row(obj, serialize):
    """Current record as an input row, so PATCH can merge and re-validate the whole record."""
    row = serialize(obj)
    row.pop("id")
    if "minimum_stock" in row:
        row["minimum_stock"] = row["minimum_stock"] or "0"
    row["is_active"] = "1" if row["is_active"] else "0"
    return row


def _master_save(kind, data, obj=None):
    model, code_field, parse, serialize, label = MASTER[kind]
    if obj is not None:
        if code_field in data and str(data[code_field]).strip() != getattr(obj, code_field):
            raise BadRequest(
                "코드는 변경할 수 없습니다. 새로 등록하세요.", {code_field: "readonly"}
            )
        data = {**_master_row(obj, serialize), **data}
    if isinstance(data.get("is_active"), bool):
        data = {**data, "is_active": "1" if data["is_active"] else "0"}
    try:
        values = parse(data)
    except ValueError as error:
        raise BadRequest(str(error)) from error
    code = values.pop("code")
    try:
        with transaction.atomic():
            if obj is None:
                if model.objects.filter(**{code_field: code}).exists():
                    raise Conflict(f"이미 등록된 {label} 코드입니다: {code}")
                obj = model.objects.create(**{code_field: code}, **values)
            else:
                for name, value in values.items():
                    setattr(obj, name, value)
                obj.save()
    except IntegrityError as error:
        raise Conflict(f"{label} 저장이 거부되었습니다: {error}") from error
    obj.refresh_from_db()
    return obj


def _master_list(request, kind):
    model, code_field, _, serialize, _ = MASTER[kind]
    rows = model.objects.order_by(code_field)
    active = request.GET.get("active", "1")
    if active != "all":
        rows = rows.filter(is_active=_flag(active))
    if q := request.GET.get("q", "").strip():
        rows = rows.filter(**{f"{code_field}__icontains": q}) | rows.filter(name__icontains=q)
    if kind == "items" and (item_type := request.GET.get("item_type")):
        rows = rows.filter(item_type=item_type)
    return [serialize(obj) for obj in rows]


def _master_collection(kind):
    @endpoint("GET", "POST")
    def view(request):
        if request.method == "POST":
            return ok(MASTER[kind][3](_master_save(kind, request.data)), status=201)
        return ok({"results": _master_list(request, kind)})

    view.__name__ = f"{kind}_collection"
    return view


def _master_detail(kind):
    @endpoint("GET", "PATCH")
    def view(request, pk):
        model, _, _, serialize, label = MASTER[kind]
        obj = _get(model, pk, label)
        if request.method == "PATCH":
            obj = _master_save(kind, request.data, obj)
        return ok(serialize(obj))

    view.__name__ = f"{kind}_detail"
    return view


staff_collection = _master_collection("staff")
staff_detail = _master_detail("staff")
supplier_collection = _master_collection("suppliers")
supplier_detail = _master_detail("suppliers")
item_collection = _master_collection("items")
item_detail = _master_detail("items")


# ---------------------------------------------------------------------------
# Receipts
# ---------------------------------------------------------------------------

RECEIPT_RELATED = ("lot__item", "supplier", "staff")


def _inspection(value):
    """Visual inspection values for the document app's D03 (checked there). Object or empty."""
    if value in (None, ""):
        return None
    if not isinstance(value, dict):
        raise BadRequest("inspection은 객체여야 합니다.", {"inspection": "객체여야 합니다."})
    return value


@endpoint("GET", "POST")
def receipt_collection(request):
    if request.method == "POST":
        data = request.data
        _required(data, "item_id", "supplier_id", "staff_id", "received_date", "quantity")
        receipt = register_receipt(
            ReceiptInput(
                item_id=_int(data["item_id"], "item_id"),
                supplier_id=_int(data["supplier_id"], "supplier_id"),
                staff_id=_int(data["staff_id"], "staff_id"),
                received_date=_date(data["received_date"], "received_date"),
                quantity=data["quantity"],
                idempotency_key=str(data.get("idempotency_key") or ""),
                supplier_lot_number=data.get("supplier_lot_number"),
                manufactured_date=_date(data.get("manufactured_date"), "manufactured_date"),
                expiration_date=_date(data.get("expiration_date"), "expiration_date"),
                expiration_status=data.get("expiration_status"),
                judgment=str(data["judgment"]).upper() if data.get("judgment") else None,
                inspection=_inspection(data.get("inspection")),
            )
        )
        receipt = IncomingReceipt.objects.select_related(*RECEIPT_RELATED).get(pk=receipt.pk)
        return ok(out.receipt(receipt), status=201)

    rows = IncomingReceipt.objects.select_related(*RECEIPT_RELATED).order_by(
        "-received_date", "-pk"
    )
    if date_from := _date(request.GET.get("from"), "from"):
        rows = rows.filter(received_date__gte=date_from)
    if date_to := _date(request.GET.get("to"), "to"):
        rows = rows.filter(received_date__lte=date_to)
    if supplier_id := _int(request.GET.get("supplier_id"), "supplier_id"):
        rows = rows.filter(supplier_id=supplier_id)
    if item_id := _int(request.GET.get("item_id"), "item_id"):
        rows = rows.filter(lot__item_id=item_id)
    if status := request.GET.get("status"):
        if status not in ReceiptStatus.values:
            raise BadRequest(f"status 는 {ReceiptStatus.values} 중 하나여야 합니다.")
        rows = rows.filter(receipt_status=status)
    count, page = _page(request, rows)
    return ok({"count": count, "results": [out.receipt(r) for r in page]})


@endpoint("GET")
def receipt_detail(request, pk):
    receipt = IncomingReceipt.objects.select_related(*RECEIPT_RELATED).filter(pk=pk).first()
    if receipt is None:
        raise NotFound(f"입고 건을 찾을 수 없습니다. (id={pk})")
    return ok(out.receipt(receipt))


@endpoint("POST")
def receipt_cancel(request, pk):
    _required(request.data, "staff_id", "reason")
    cancel_receipt(
        receipt_id=pk,
        staff_id=_int(request.data["staff_id"], "staff_id"),
        reason=str(request.data["reason"]),
    )
    receipt = IncomingReceipt.objects.select_related(*RECEIPT_RELATED).get(pk=pk)
    return ok(out.receipt(receipt))


# ---------------------------------------------------------------------------
# Lots / stock / ledger
# ---------------------------------------------------------------------------


@endpoint("GET")
def lot_detail(request, pk):
    lot = Lot.objects.select_related("item").filter(pk=pk).first()
    if lot is None:
        raise NotFound(f"LOT을 찾을 수 없습니다. (id={pk})")
    quantity = Inventory.objects.filter(lot=lot).values_list("quantity_e6", flat=True).first()
    movements = (
        StockMovement.objects.filter(lot=lot)
        .select_related("lot__item", "movement_type", "staff")
        .order_by("occurred_at", "pk")
    )
    data = out.lot(lot, quantity or 0)
    data["movements"] = [out.movement(m) for m in movements]
    return ok(data)


@endpoint("POST")
def lot_judgment(request, pk):
    """Incoming inspection result for the LOT (PASS / FAIL). Normally called by the document app
    as a function; exposed here for screens and testing."""
    data = request.data
    _required(data, "result", "staff_id")
    lot = apply_incoming_judgment(
        lot_id=pk,
        result=str(data["result"]).upper(),
        staff_id=_int(data["staff_id"], "staff_id"),
        document_id=_int(data.get("document_id"), "document_id"),
        judged_at=_datetime(data.get("judged_at"), "judged_at") or None,
        reason=data.get("reason"),
    )
    lot = Lot.objects.select_related("item").get(pk=lot.pk)
    quantity = Inventory.objects.filter(lot=lot).values_list("quantity_e6", flat=True).first()
    return ok(out.lot(lot, quantity or 0))


@endpoint("GET")
def stock_lots(request):
    status = request.GET.get("status")
    if status and status not in LotStatus.values:
        raise BadRequest(f"status 는 {LotStatus.values} 중 하나여야 합니다.")
    expiration_status = (request.GET.get("expiration_status") or "").upper() or None
    if expiration_status and expiration_status not in ExpirationStatus.values:
        raise BadRequest(f"expiration_status 는 {ExpirationStatus.values} 중 하나여야 합니다.")
    rows = lot_stock(
        item_type=request.GET.get("item_type") or None,
        item_id=_int(request.GET.get("item_id"), "item_id"),
        status=status,
        include_empty=_flag(request.GET.get("include_empty", "0")),
        expiring_within_days=_int(request.GET.get("expiring_within_days"), "expiring_within_days"),
        lot_number=request.GET.get("lot_number") or None,
        manufactured_from=_date(request.GET.get("manufactured_from"), "manufactured_from"),
        manufactured_to=_date(request.GET.get("manufactured_to"), "manufactured_to"),
        expiration_status=expiration_status,
        usable_only=_flag(request.GET.get("usable_only", "0")),
    )
    return ok({"results": [out.lot_stock(row) for row in rows]})


@endpoint("GET")
def stock_items(request):
    rows = item_stock(
        item_type=request.GET.get("item_type") or None,
        item_id=_int(request.GET.get("item_id"), "item_id"),
    )
    if _flag(request.GET.get("below_minimum", "0")):
        rows = [row for row in rows if row.below_minimum]
    return ok({"results": [out.item_stock(row) for row in rows]})


def ledger_params(request):
    date_from = _date(request.GET.get("from"), "from", required=True)
    date_to = _date(request.GET.get("to"), "to", required=True)
    if date_to < date_from:
        raise BadRequest("조회 종료일이 시작일보다 빠릅니다.")
    if (date_to - date_from).days > 366:
        raise BadRequest("조회 기간은 1년 이내로 지정하세요.")
    return {
        "date_from": date_from,
        "date_to": date_to,
        "item_type": request.GET.get("item_type") or None,
        "item_id": _int(request.GET.get("item_id"), "item_id"),
        "lot_id": _int(request.GET.get("lot_id"), "lot_id"),
    }


def ledger_search(request):
    """ledger_params + LOT 번호 검색 (ledger/, ledger/export.csv)."""
    return {**ledger_params(request), "lot_number": request.GET.get("lot_number") or None}


@endpoint("GET")
def ledger(request):
    params = ledger_search(request)
    items = stock_ledger(params.pop("date_from"), params.pop("date_to"), **params)
    return ok(
        {
            "from": request.GET["from"],
            "to": request.GET["to"],
            "results": [out.ledger_item(row) for row in items],
        }
    )


@endpoint("GET")
def ledger_changes(request):
    """Movements recorded since an approval that change the ledger for the period."""
    since = _datetime(request.GET.get("since"), "since")
    if not isinstance(since, datetime.datetime):
        raise BadRequest(
            "'since' 는 승인 일시(YYYY-MM-DDTHH:MM:SS)여야 합니다.", {"since": "invalid"}
        )
    params = ledger_params(request)
    changes = stock_ledger_changes_since(
        since, params.pop("date_from"), params.pop("date_to"), **params
    )
    return ok({"changed": bool(changes), "results": [out.ledger_change(c) for c in changes]})


# ---------------------------------------------------------------------------
# Movements
# ---------------------------------------------------------------------------


def _movement_response(movement, status=201):
    movement = StockMovement.objects.select_related("lot__item", "movement_type", "staff").get(
        pk=movement.pk
    )
    data = out.movement(movement)
    data["lot_quantity"] = str(
        from_e6(
            Inventory.objects.filter(lot_id=movement.lot_id)
            .values_list("quantity_e6", flat=True)
            .first()
            or 0
        )
    )
    data["lot_status"] = movement.lot.status
    return ok(data, status=status)


@endpoint("POST")
def opening_balance(request):
    data = request.data
    _required(data, "item_id", "quantity", "staff_id", "occurred_at", "idempotency_key")
    movement = record_opening_balance(
        item_id=_int(data["item_id"], "item_id"),
        quantity=data["quantity"],
        staff_id=_int(data["staff_id"], "staff_id"),
        occurred_at=_datetime(data["occurred_at"], "occurred_at"),
        idempotency_key=str(data["idempotency_key"]),
        lot_number=data.get("lot_number"),
        manufactured_date=_date(data.get("manufactured_date"), "manufactured_date"),
        expiration_date=_date(data.get("expiration_date"), "expiration_date"),
        status=data.get("status") or LotStatus.AVAILABLE,
        reason=data.get("reason"),
        expiration_status=data.get("expiration_status"),
    )
    return _movement_response(movement)


@endpoint("POST")
def adjust(request):
    data = request.data
    _required(data, "lot_id", "direction", "quantity", "reason", "staff_id", "idempotency_key")
    movement = adjust_stock(
        lot_id=_int(data["lot_id"], "lot_id"),
        direction=str(data["direction"]).upper(),
        quantity=data["quantity"],
        reason=str(data["reason"]),
        staff_id=_int(data["staff_id"], "staff_id"),
        idempotency_key=str(data["idempotency_key"]),
        occurred_at=_datetime(data.get("occurred_at"), "occurred_at"),
    )
    return _movement_response(movement)


def _outflow_view(service):
    @endpoint("POST")
    def view(request):
        data = request.data
        _required(data, "lot_id", "reason", "staff_id", "idempotency_key")
        movement = service(
            lot_id=_int(data["lot_id"], "lot_id"),
            quantity=data.get("quantity") or None,
            reason=str(data["reason"]),
            staff_id=_int(data["staff_id"], "staff_id"),
            idempotency_key=str(data["idempotency_key"]),
            occurred_at=_datetime(data.get("occurred_at"), "occurred_at"),
        )
        return _movement_response(movement)

    view.__name__ = service.__name__
    return view


return_view = _outflow_view(return_to_supplier)
disposal_view = _outflow_view(dispose)


@endpoint("POST")
def correct(request, pk):
    data = request.data
    _required(data, "reason", "staff_id", "idempotency_key")
    movement = correct_movement(
        movement_id=pk,
        quantity=data.get("quantity") or None,
        reason=str(data["reason"]),
        staff_id=_int(data["staff_id"], "staff_id"),
        idempotency_key=str(data["idempotency_key"]),
    )
    return _movement_response(movement)


# ---------------------------------------------------------------------------
# Production (production.py)
# ---------------------------------------------------------------------------

BATCH_RELATED = ("item", "staff")


def _batch_response(batch_id, status=200):
    summary = batch_summary(batch_id)
    summary["batch"] = ProductionBatch.objects.select_related(*BATCH_RELATED).get(pk=batch_id)
    data = out.batch_detail(summary)
    data["readiness"] = material_readiness(summary["batch"])
    return ok(data, status=status)


@endpoint("GET", "POST")
def batch_collection(request):
    if request.method == "POST":
        data = request.data
        _required(data, "item_id", "staff_id")
        batch = create_batch(
            item_id=_int(data["item_id"], "item_id"),
            # 제조만 (포장배치는 MVP 범위 밖, 10/15). 생략하면 MANUFACTURE
            process_type=str(data.get("process_type") or ProcessType.MANUFACTURE).upper(),
            staff_id=_int(data["staff_id"], "staff_id"),
            planned_date=_date(data.get("planned_date"), "planned_date"),
            planned_quantity=data.get("planned_quantity"),
            manufactured_date=_date(data.get("manufactured_date"), "manufactured_date"),
            bom_id=_int(data.get("bom_id"), "bom_id"),
            notes=data.get("notes"),
        )
        return _batch_response(batch.pk, status=201)

    rows = ProductionBatch.objects.select_related(*BATCH_RELATED).order_by("-pk")
    if _flag(request.GET.get("exclude_cancelled", "0")):
        rows = rows.exclude(status=BatchStatus.CANCELLED)
    if status := request.GET.get("status"):
        if status not in BatchStatus.values:
            raise BadRequest(f"status 는 {BatchStatus.values} 중 하나여야 합니다.")
        rows = rows.filter(status=status)
    if process_type := request.GET.get("process_type"):
        if process_type not in ProcessType.values:
            raise BadRequest(f"process_type 은 {ProcessType.values} 중 하나여야 합니다.")
        rows = rows.filter(process_type=process_type)
    if item_id := _int(request.GET.get("item_id"), "item_id"):
        rows = rows.filter(item_id=item_id)
    # Period on the manufacturing date (or the planned date while not yet made).
    if date_from := _date(request.GET.get("from"), "from"):
        rows = rows.filter(
            Q(manufactured_date__gte=date_from)
            | Q(manufactured_date__isnull=True, planned_date__gte=date_from)
        )
    if date_to := _date(request.GET.get("to"), "to"):
        rows = rows.filter(
            Q(manufactured_date__lte=date_to)
            | Q(manufactured_date__isnull=True, planned_date__lte=date_to)
        )
    count, page = _page(request, rows)
    return ok({"count": count, "results": [out.batch(b) for b in page]})


@endpoint("GET")
def batch_detail(request, pk):
    return _batch_response(pk)


@endpoint("POST")
def batch_start(request, pk):
    data = request.data
    _required(data, "staff_id")
    start_batch(
        batch_id=pk,
        staff_id=_int(data["staff_id"], "staff_id"),
        started_at=_datetime(data.get("started_at"), "started_at"),
        manufactured_date=_date(data.get("manufactured_date"), "manufactured_date"),
    )
    return _batch_response(pk)


@endpoint("POST")
def batch_usage(request, pk):
    data = request.data
    if "entries" in data:
        _required(data, "staff_id", "idempotency_key")
        entries = data["entries"]
        if not isinstance(entries, list) or any(not isinstance(row, dict) for row in entries):
            raise BadRequest("투입 목록 형식이 올바르지 않습니다.")
        for row in entries:
            row["lot_id"] = _int(row.get("lot_id"), "lot_id", required=True)
            row["bom_line_id"] = _int(row.get("bom_line_id"), "bom_line_id")
        add_usages(
            batch_id=pk,
            entries=entries,
            staff_id=_int(data["staff_id"], "staff_id"),
            idempotency_key=str(data["idempotency_key"]),
        )
        return _batch_response(pk, status=201)
    _required(data, "lot_id", "quantity", "staff_id", "idempotency_key")
    add_usage(
        batch_id=pk,
        lot_id=_int(data["lot_id"], "lot_id"),
        quantity=data["quantity"],
        staff_id=_int(data["staff_id"], "staff_id"),
        idempotency_key=str(data["idempotency_key"]),
        occurred_at=_datetime(data.get("occurred_at"), "occurred_at"),
        bom_line_id=_int(data.get("bom_line_id"), "bom_line_id"),
    )
    return _batch_response(pk, status=201)


@endpoint("POST")
def batch_output(request, pk):
    data = request.data
    _required(data, "quantity", "staff_id", "idempotency_key")
    add_output(
        batch_id=pk,
        quantity=data["quantity"],
        staff_id=_int(data["staff_id"], "staff_id"),
        idempotency_key=str(data["idempotency_key"]),
        occurred_at=_datetime(data.get("occurred_at"), "occurred_at"),
        lot_number=data.get("lot_number"),
        expiration_date=_date(data.get("expiration_date"), "expiration_date"),
    )
    return _batch_response(pk, status=201)


@endpoint("POST")
def batch_complete(request, pk):
    data = request.data
    _required(data, "staff_id")
    complete_batch(
        batch_id=pk,
        staff_id=_int(data["staff_id"], "staff_id"),
        completed_at=_datetime(data.get("completed_at"), "completed_at"),
    )
    return _batch_response(pk)


@endpoint("POST")
def batch_cancel(request, pk):
    data = request.data
    _required(data, "staff_id", "reason")
    cancel_batch(batch_id=pk, staff_id=_int(data["staff_id"], "staff_id"), reason=data["reason"])
    return _batch_response(pk)


@endpoint("GET")
def fefo(request):
    """Usable LOTs to cover a quantity of an item, earliest expiration first."""
    item_id = _int(request.GET.get("item_id"), "item_id", required=True)
    quantity = request.GET.get("quantity")
    if not quantity:
        raise BadRequest("'quantity' 값이 필요합니다.", {"quantity": "required"})
    picks = fefo_candidates(
        item_id=item_id, quantity=quantity, on_date=_date(request.GET.get("on_date"), "on_date")
    )
    covered = sum(take for _, take, _ in picks)
    return ok(
        {
            "item_id": item_id,
            "quantity": quantity,
            "covered": out.qty(covered),
            "shortfall": out.qty(max(to_e6(quantity) - covered, 0)),
            "results": [out.fefo_pick(*pick) for pick in picks],
        }
    )


@endpoint("GET")
def bom_collection(request):
    """BOMs (read only — BOM data is loaded by the data team)."""
    rows = Bom.objects.order_by("item_id", "-version")
    if item_id := _int(request.GET.get("item_id"), "item_id"):
        rows = rows.filter(item_id=item_id)
    if not _flag(request.GET.get("include_inactive", "0")):
        rows = rows.filter(is_active=True)
    lines = {}
    for line in (
        BomLine.objects.filter(bom__in=rows).select_related("component_item").order_by("line_no")
    ):
        lines.setdefault(line.bom_id, []).append(line)
    return ok({"results": [out.bom(b, lines.get(b.pk, [])) for b in rows]})


# ---------------------------------------------------------------------------
# Holds (holds.py)
# ---------------------------------------------------------------------------

HOLD_RELATED = ("lot__item", "batch", "source_type", "held_by", "released_by")


def _hold_response(hold_id, status=200):
    return ok(out.hold(Hold.objects.select_related(*HOLD_RELATED).get(pk=hold_id)), status=status)


@endpoint("GET", "POST")
def hold_collection(request):
    if request.method == "POST":
        data = request.data
        _required(data, "source_type", "reason", "staff_id")
        lot_id = _int(data.get("lot_id"), "lot_id")
        batch_id = _int(data.get("batch_id"), "batch_id")
        if bool(lot_id) == bool(batch_id):
            raise BadRequest("lot_id 와 batch_id 중 하나만 보내세요.")
        common = {
            "source_type": str(data["source_type"]).upper(),
            "reason": str(data["reason"]),
            "staff_id": _int(data["staff_id"], "staff_id"),
            "source_document_id": _int(data.get("source_document_id"), "source_document_id"),
            "held_at": _datetime(data.get("held_at"), "held_at"),
        }
        hold = (
            hold_lot(lot_id=lot_id, **common) if lot_id else hold_batch(batch_id=batch_id, **common)
        )
        return _hold_response(hold.pk, status=201)

    rows = Hold.objects.select_related(*HOLD_RELATED).order_by("-pk")
    if _flag(request.GET.get("open", "0")):
        rows = rows.filter(released_at__isnull=True)
    if lot_id := _int(request.GET.get("lot_id"), "lot_id"):
        rows = rows.filter(lot_id=lot_id)
    if batch_id := _int(request.GET.get("batch_id"), "batch_id"):
        rows = rows.filter(batch_id=batch_id)
    if parent_id := _int(request.GET.get("parent_hold_id"), "parent_hold_id"):
        rows = rows.filter(parent_hold_id=parent_id)
    count, page = _page(request, rows)
    return ok({"count": count, "results": [out.hold(h) for h in page]})


@endpoint("GET")
def hold_detail(request, pk):
    _get(Hold, pk, "보류")
    return _hold_response(pk)


@endpoint("POST")
def hold_release(request, pk):
    data = request.data
    _required(data, "disposition", "reason", "staff_id")
    release_hold(
        hold_id=pk,
        disposition=str(data["disposition"]).upper(),
        reason=str(data["reason"]),
        staff_id=_int(data["staff_id"], "staff_id"),
        released_at=_datetime(data.get("released_at"), "released_at"),
    )
    return _hold_response(pk)
