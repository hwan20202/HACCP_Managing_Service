"""작성 요구 테스트용 개발 API (/api/dev/req/, s2-spec 2.2 REQ-D01~D07).

개발 콘솔이 켜진 설정에서만 URL이 등록된다(devtools/urls.py).
수불·생산이 할 일(입고 등록·생산 시작 + 작성 요구 호출)을 한 트랜잭션으로 흉내 낸다(C2, D-128).
- 입고 LOT은 수불 입고 서비스(register_receipt)로 만든다 — LOT 번호·구분·단위·원산지는
  수불(품목) 값. LOT 문서(F01)는 수불 입고 훅이 같은 트랜잭션에서 만든다
- 생산 배치는 개발 전용 INSERT(inventory_dev.make_batch — 개발 품목이 완제품이라
  수불 생산 서비스 밖)
- 다시 호출(D06·D07)은 수불 행 자기 쓰기(UPDATE)를 먼저 한다(REQ-S2-Q13). 트랜잭션은 수불 설정대로
  IMMEDIATE로 시작한다(쓰기 잠금 먼저).
- fail_after면 작성 요구 다음에 일부러 실패시켜 LOT·문서가 모두 롤백되는지 보여 준다(REQ-S1-Q2).
"""

import datetime

from django.db import transaction
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from apps.core.http import (
    ApiError,
    error_response,
    json_response,
    parse_json_body,
    reject_unknown_keys,
)
from apps.core.trace import step
from apps.doc_requirements import errors as req_errors
from apps.doc_requirements import services as req
from apps.doc_requirements import sources
from apps.staff.services import actor_from_header

from . import inventory_dev

PROCESS_TYPES = ("MANUFACTURE", "PACKAGING")
LOT_KEYS = (
    "item_id",
    "supplier_name",
    "received_date",
    "quantity",
    "expiration_date",
    "expiration_status",  # 수불 0007: 소비기한 유무 KNOWN·NONE. 원료는 날짜 또는 이 값을 직접 선택
    "fail_after",
    "inspection",  # P6 D-080: 입고 화면에서 육안검사까지(형식 검사는 REQ-LOT-00b)
)
BATCH_KEYS = ("item_id", "process_type", "manufactured_date", "quantity_kg", "fail_after")


def _api(view):
    def wrapper(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except ApiError as error:
            return error_response(error)

    wrapper.__name__ = view.__name__
    return wrapper


def _err(path, code, message):
    return {"path": path, "code": code, "message": message}


def _date(body, key, problems, required=True):
    value = body.get(key)
    if value is None and not required:
        return None
    try:
        if not isinstance(value, str) or len(value) != 10:
            raise ValueError
        return datetime.date.fromisoformat(value)
    except ValueError:
        problems.append(_err(key, "invalid", "YYYY-MM-DD 날짜입니다."))
        return None


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _item(body, problems):
    item_id = body.get("item_id")
    if not isinstance(item_id, int) or isinstance(item_id, bool):
        problems.append(_err("item_id", "invalid", "품목 id(정수)입니다."))
        return None
    if not inventory_dev.item_exists(item_id):
        problems.append(_err("item_id", "not_found", "없는 품목입니다."))
    return item_id


def _fail_after(body, problems):
    value = body.get("fail_after", False)
    if not isinstance(value, bool):
        problems.append(_err("fail_after", "invalid", "true 또는 false입니다."))
    return value is True


def _raise_if(problems):
    if problems:
        raise req_errors.ValidationFailed(details=problems)


def _clean_lot(body):
    """VR-05(입고): 품목(원료·포장재), 매입처 1~50자, 날짜, 수량 > 0.

    구분·단위·원산지는 품목 값이라 받지 않는다(C2)."""
    reject_unknown_keys(body, LOT_KEYS)
    problems = []
    data = {"item_id": _item(body, problems)}
    if data["item_id"] and not problems and not inventory_dev.is_receivable(data["item_id"]):
        problems.append(_err("item_id", "invalid", "입고 품목(원료·포장재)이 아닙니다."))
    supplier = body.get("supplier_name")
    supplier = supplier.strip() if isinstance(supplier, str) else ""
    if not 1 <= len(supplier) <= 50:
        problems.append(_err("supplier_name", "invalid", "1~50자입니다."))
    data["received_date"] = _date(body, "received_date", problems)
    data["expiration_date"] = _date(body, "expiration_date", problems, required=False)
    status = body.get("expiration_status")
    if status not in (None, "KNOWN", "NONE", "UNKNOWN"):
        problems.append(_err("expiration_status", "invalid", "KNOWN·NONE·UNKNOWN 중 하나입니다."))
    data["expiration_status"] = status
    if not _number(body.get("quantity")) or body["quantity"] <= 0:
        problems.append(_err("quantity", "invalid", "0보다 큰 수입니다."))
    data["fail_after"] = _fail_after(body, problems)
    _raise_if(problems)
    data.update(
        inspection=body.get("inspection"), supplier_name=supplier, quantity=body["quantity"]
    )
    return data


def _clean_batch(body):
    """VR-05(배치): 품목, 공정 유형, 생산일, 생산량 ≥ 0."""
    reject_unknown_keys(body, BATCH_KEYS)
    problems = []
    data = {"item_id": _item(body, problems)}
    if body.get("process_type") not in PROCESS_TYPES:
        problems.append(_err("process_type", "invalid", "MANUFACTURE 또는 PACKAGING입니다."))
    data["manufactured_date"] = _date(body, "manufactured_date", problems)
    if not _number(body.get("quantity_kg")) or body["quantity_kg"] < 0:
        problems.append(_err("quantity_kg", "invalid", "0 이상 수입니다."))
    data["fail_after"] = _fail_after(body, problems)
    _raise_if(problems)
    data.update(process_type=body["process_type"], quantity_kg=body["quantity_kg"])
    return data


def _actor(request):
    return actor_from_header(request.headers.get("X-Staff-Id"))


def _query_date(request):
    raw = request.GET.get("date")
    if not raw:
        return None
    problems = []
    day = _date({"date": raw}, "date", problems)
    _raise_if(problems)
    return day.isoformat()


# ---------------------------------------------------------------- D01~D03 목록


def _doc_summary(documents, *keys):
    return [{k: d[k] for k in ("document_id", "type_code", "status", *keys)} for d in documents]


@require_http_methods(["GET"])
@_api
def lot_list(request):
    """REQ-D01: 개발 입고 LOT 목록 + 연결 문서 요약(F03)."""
    items = []
    for lot in sources.lots_received_on(_query_date(request)):
        # D-178: 취소 LOT은 F03이 LOT_NOT_FOUND — 목록에 남기고(receipt_status) 문서는 없음
        if lot.get("receipt_status") == "CANCELLED":
            items.append({**lot, "documents": []})
            continue
        found = req.docs_for_lot(lot["lot_id"])
        items.append({**lot, "documents": _doc_summary(found["documents"])})
    return json_response({"items": items})


@require_http_methods(["GET"])
@_api
def batch_list(request):
    """REQ-D02: 개발 생산 배치 목록 + 연결 문서 요약(F04)."""
    items = []
    for batch in sources.batches_made_on(_query_date(request)):
        found = req.docs_for_batch(batch["production_batch_id"])
        items.append({**batch, "documents": _doc_summary(found["documents"], "process_code")})
    return json_response({"items": items})


@require_http_methods(["GET"])
@_api
def item_list(request):
    """REQ-D03: 개발 품목 목록(모달용) — 수불 품목(구분·기준 단위·입고 가능 여부 포함)."""
    return json_response({"items": inventory_dev.item_choices()})


# ---------------------------------------------------------------- D04·D05 생성 + 작성 요구


def _finish(fail_after, payload, status):
    if fail_after:
        with step("REQ-DEV-03", "API", "실패 흉내(롤백 확인)"):
            raise req_errors.SimulatedFailure()
    with step("REQ-DEV-04", "API", "결과"):
        return json_response(payload() if callable(payload) else payload, status=status)


@csrf_exempt
@require_http_methods(["GET", "POST"])
@_api
def lot_collection(request):
    if request.method == "GET":
        return lot_list(request)
    with step("REQ-DEV-01", "API", "요청 형식·사용자 확인"):
        actor = _actor(request)
        data = _clean_lot(parse_json_body(request))
    day = data["received_date"]
    with transaction.atomic():
        # 수불 입고 화면과 같음: 입고 훅이 F01(require_for_lot)을 부르고, inspection이 있으면
        # 새 D03에 채운 뒤 수불이 그 최종판정을 입고 판정으로 반영한다(D-080, 수불 document_bridge)
        with step("REQ-DEV-02", "API", "수불 입고 등록(register_receipt → 입고 훅 F01·판정)"):
            lot_id, result = inventory_dev.receive_lot(
                item_id=data["item_id"],
                supplier_name=data["supplier_name"],
                received_date=day,
                quantity=data["quantity"],
                staff_id=actor,
                expiration_date=data["expiration_date"],
                expiration_status=data["expiration_status"],
                inspection=data["inspection"],
            )
        return _finish(
            data["fail_after"], lambda: {"lot": sources.incoming_lot(lot_id), "result": result}, 201
        )


@csrf_exempt
@require_http_methods(["GET", "POST"])
@_api
def batch_collection(request):
    if request.method == "GET":
        return batch_list(request)
    with step("REQ-DEV-01", "API", "요청 형식·사용자 확인"):
        actor = _actor(request)
        data = _clean_batch(parse_json_body(request))
    day = data["manufactured_date"]
    with transaction.atomic():
        with step("REQ-DEV-02", "API", "개발 배치 INSERT(수불 생산 서비스 전 — 개발 전용)"):
            batch_id = inventory_dev.make_batch(
                item_id=data["item_id"],
                process_type=data["process_type"],
                manufactured_date=day,
                quantity_kg=data["quantity_kg"],
                staff_id=actor,
            )
        result = req.require_for_batch(actor, batch_id)
        return _finish(
            data["fail_after"], lambda: {"batch": sources.batch(batch_id), "result": result}, 201
        )


# ---------------------------------------------------------------- D06·D07 다시 호출


def _empty_body(request):
    if request.body:
        reject_unknown_keys(parse_json_body(request), ())


@csrf_exempt
@require_http_methods(["POST"])
@_api
def lot_require(request, lot_id):
    """REQ-D06: 같은 LOT로 F01 다시 호출. 자기 쓰기(수불 LOT UPDATE) 먼저."""
    with step("REQ-DEV-01", "API", "요청 형식·사용자 확인"):
        actor = _actor(request)
        _empty_body(request)
    with transaction.atomic():
        with step("REQ-DEV-RE1", "API", "LOT UPDATE(자기 쓰기 먼저)") as s:
            touched = inventory_dev.touch_lot(lot_id)
            s.note(f"영향 행 {touched}")
            if touched == 0:
                raise req_errors.LotNotFound()
        result = req.require_for_lot(actor, lot_id)
        return _finish(False, result, 200)


@csrf_exempt
@require_http_methods(["POST"])
@_api
def batch_require(request, batch_id):
    """REQ-D07: 같은 배치로 F02 다시 호출."""
    with step("REQ-DEV-01", "API", "요청 형식·사용자 확인"):
        actor = _actor(request)
        _empty_body(request)
    with transaction.atomic():
        with step("REQ-DEV-RE1", "API", "배치 UPDATE(자기 쓰기 먼저)") as s:
            touched = inventory_dev.touch_batch(batch_id)
            s.note(f"영향 행 {touched}")
            if touched == 0:
                raise req_errors.BatchNotFound()
        result = req.require_for_batch(actor, batch_id)
        return _finish(False, result, 200)
