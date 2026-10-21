"""작성 요구 조회 API (/api/v1/, s2-spec 2.2 REQ-A01·A02). 입출력만 담당한다."""

from django.utils.dateparse import parse_date
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
from apps.staff.services import actor_from_header, optional_actor_from_header

from . import ccp, errors, periodic, services, todo


def _api(view):
    def wrapper(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except ApiError as error:
            return error_response(error)

    wrapper.__name__ = view.__name__
    wrapper.__doc__ = view.__doc__
    return wrapper


@require_http_methods(["GET"])
@_api
def lot_documents(request, lot_id):
    """REQ-A01: LOT별 연결 문서(F03)."""
    return json_response(services.docs_for_lot(lot_id))


@require_http_methods(["GET"])
@_api
def batch_documents(request, batch_id):
    """REQ-A02: 배치별 연결 문서(F04)."""
    return json_response(services.docs_for_batch(batch_id))


@require_http_methods(["GET"])
@_api
def incoming_inspections(request):
    """REQ-A03: 입고일 묶음 조회 ?received_date=YYYY-MM-DD (X-Staff-Id 선택 — r14 D-202 Q7 b)."""
    with step("REQ-BDL-01", "API", "날짜 형식·현재 사용자"):
        raw = request.GET.get("received_date") or ""
        try:
            day = parse_date(raw) if len(raw) == 10 else None
            if day is None:
                raise ValueError(raw)
            day = day.isoformat()
        except ValueError:
            raise errors.ValidationFailed(
                details=[
                    {
                        "path": "received_date",
                        "code": "invalid",
                        "message": "YYYY-MM-DD 형식이어야 합니다.",
                    }
                ]
            ) from None
        actor = optional_actor_from_header(request.headers.get("X-Staff-Id"))
    return json_response(services.incoming_bundle(actor, day))


@require_http_methods(["GET"])
@_api
def periodic_bundles(request):
    """REQ-A04: 주 묶음 조회 ?type_code=D10&week_start=YYYY-MM-DD(월) (X-Staff-Id 선택, r14)."""
    with step("REQ-PWB-01", "API", "형식·현재 사용자"):
        raw = request.GET.get("week_start") or ""
        try:
            day = parse_date(raw) if len(raw) == 10 else None
        except ValueError:
            day = None
        if day is None:
            raise errors.ValidationFailed(
                details=[
                    {
                        "path": "week_start",
                        "code": "invalid",
                        "message": "YYYY-MM-DD 형식이어야 합니다.",
                    }
                ]
            )
        actor = optional_actor_from_header(request.headers.get("X-Staff-Id"))
    return json_response(services.periodic_bundle(actor, request.GET.get("type_code") or "", day))


# ---------------------------------------------------------------- P9 주기형 (p9-s2-spec 4.1)


@csrf_exempt
@require_http_methods(["POST"])
@_api
def periodic_runs(request):
    """REQ-A05: 기간의 주기 문서 만들기 {date_from, date_to, type_codes?} (X-Staff-Id 필수).

    실패 줄이 있어도 200(줄 result = failed). 입력·사용자·규칙 오류는 아무것도 만들지 않는다."""
    with step("REQ-PRN-01", "API", "본문 형식·현재 사용자"):
        actor = actor_from_header(request.headers.get("X-Staff-Id"))
        body = parse_json_body(request)
        reject_unknown_keys(body, ("date_from", "date_to", "type_codes"))
    return json_response(
        periodic.run_periodic(
            actor, body.get("date_from"), body.get("date_to"), body.get("type_codes")
        )
    )


@csrf_exempt
@require_http_methods(["POST"])
@_api
def periodic_documents(request):
    """REQ-A06: 그날 주기 문서 찾거나 만들기 {type_code, date} (X-Staff-Id 필수, 미래·주말 허용)."""
    with step("REQ-POD-01", "API", "본문 형식·현재 사용자"):
        actor = actor_from_header(request.headers.get("X-Staff-Id"))
        body = parse_json_body(request)
        reject_unknown_keys(body, ("type_code", "date"))
    return json_response(
        periodic.open_periodic_document(actor, body.get("type_code"), body.get("date"))
    )


@require_http_methods(["GET"])
@_api
def periodic_rules(request):
    """REQ-A07: 주기 규칙 목록(F09)."""
    return json_response(periodic.periodic_rules())


# -------------------------------------------------------- P10 작성 필요 목록 (p10-s2-spec 2.1)


@require_http_methods(["GET"])
@_api
def todo_list(request):
    """REQ-A08: 작성 필요 목록 ?date=YYYY-MM-DD&mine=1 (X-Staff-Id 필수, date 없으면 오늘)."""
    with step("REQ-TDO-01", "API", "현재 사용자"):
        actor = actor_from_header(request.headers.get("X-Staff-Id"))
    return json_response(todo.todo_list(actor, request.GET.get("date"), request.GET.get("mine")))


# -------------------------------------------------------- P11 CCP 현황 (p11-s2-spec 2.1)


@require_http_methods(["GET"])
@_api
def ccp_dashboard(request):
    """REQ-A09: CCP 현황 ?date=YYYY-MM-DD (X-Staff-Id 선택 — 보내면 확인만, B2)."""
    with step("REQ-CCP-01", "API", "현재 사용자(선택)"):
        actor = optional_actor_from_header(request.headers.get("X-Staff-Id"))
    return json_response(ccp.ccp_dashboard(actor, request.GET.get("date")))
