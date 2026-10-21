"""결재 도메인 HTTP API (/api/v1/) — 읽기 전용. 쓰기(상신·승인·반려)는 P3 WF가 연다."""

from django.views.decorators.http import require_http_methods

from apps.core.http import ApiError, error_response, json_response
from apps.core.trace import step
from apps.staff.services import actor_from_header, optional_actor_from_header

from . import services


def _api(view):
    def wrapper(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except ApiError as error:
            return error_response(error)

    wrapper.__name__ = view.__name__
    return wrapper


@require_http_methods(["GET"])
@_api
def approval_inbox(request):
    with step("APR-INB-00", "API", "현재 사용자 확인"):
        actor = actor_from_header(request.headers.get("X-Staff-Id"))
    query = request.GET
    filters = {key: query.get(key) for key in ("from", "to", "template_id")}
    return json_response(
        services.list_inbox(actor, query.get("box", "pending"), filters, query.get("page", "1"))
    )


@require_http_methods(["GET"])
@_api
def request_detail(request, request_id):
    actor = optional_actor_from_header(request.headers.get("X-Staff-Id"))  # P14 can_cancel
    return json_response(services.get_request(request_id, actor))


@require_http_methods(["GET"])
@_api
def document_requests(request, document_id):
    actor = optional_actor_from_header(request.headers.get("X-Staff-Id"))  # P14 can_cancel
    return json_response(services.list_requests(document_id, actor))
