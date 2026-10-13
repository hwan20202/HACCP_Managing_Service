"""작성 요구 조회 API (/api/v1/, s2-spec 2.2 REQ-A01·A02). 입출력만 담당한다."""

from django.utils.dateparse import parse_date
from django.views.decorators.http import require_http_methods

from apps.core.http import ApiError, error_response, json_response
from apps.core.trace import step
from apps.staff.services import actor_from_header

from . import errors, services


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
    """REQ-A03: 입고일 묶음 조회 ?received_date=YYYY-MM-DD (X-Staff-Id 필수)."""
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
        actor = actor_from_header(request.headers.get("X-Staff-Id"))
    return json_response(services.incoming_bundle(actor, day))
