"""작성 요구 조회 API (/api/v1/, s2-spec 2.2 REQ-A01·A02). 입출력만 담당한다."""

from django.views.decorators.http import require_http_methods

from apps.core.http import ApiError, error_response, json_response

from . import services


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
