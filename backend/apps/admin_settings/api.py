"""관리 설정 HTTP API (/api/v1/admin/…) — 묶음 ① A01·A02·A11. 입출력만(p16-s2-spec 4장).

- 읽기는 헤더 없이, 쓰기는 X-Staff-Id(누구나 — R27)와 expected_version(낙관적 잠금 — R10).
- CSRF: 문서 API와 달리 **검사를 끄지 않는다**(R71).
  화면은 `csrftoken` 쿠키(첫 화면 `home`이 발급) 값을 `X-CSRFToken`에 실어 보낸다.
"""

from django.db import transaction
from django.views.decorators.http import require_http_methods

from apps.core.http import ApiError, error_response, json_response, parse_json_body
from apps.core.trace import step
from apps.staff.services import actor_from_header

from . import errors, services
from .errors import detail


def _api(view):
    def wrapper(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except ApiError as error:
            return error_response(error)

    wrapper.__name__ = view.__name__
    wrapper.__doc__ = view.__doc__
    return wrapper


def _flag(request, name):
    raw = request.GET.get(name, "0")
    if raw not in ("0", "1"):
        raise errors.ValidationFailed(details=[detail(name, "invalid", "0 또는 1")])
    return raw == "1"


def _int(request, name, default=None):
    raw = request.GET.get(name)
    if raw in (None, ""):
        return default
    if not (raw.isascii() and raw.isdigit()):
        raise errors.ValidationFailed(details=[detail(name, "invalid", "0 이상 정수")])
    return int(raw)


@require_http_methods(["GET"])
@_api
def item_ccp_list(request):
    """A01: 반제품 품목별 CCP 목록."""
    return json_response(
        services.list_item_ccp(
            request.GET.get("q", ""),
            _flag(request, "include_inactive"),
            _flag(request, "only_own"),
        )
    )


@require_http_methods(["PUT"])
@_api
def item_ccp_item(request, item_id):
    """A02: 품목 CCP 저장 {mode, processes, reason?, expected_version}."""
    with step("ADM-CCP-S00", "API", "요청 형식 확인"):
        body = parse_json_body(request)
    with step("ADM-CCP-S00b", "API", "현재 사용자 확인"):
        actor = actor_from_header(request.headers.get("X-Staff-Id"))
    with transaction.atomic():
        return json_response(services.save_item_ccp(actor, item_id, body))


@require_http_methods(["GET"])
@_api
def history(request):
    """A11: 변경 이력 ?target=item_ccp&target_id=&limit=."""
    return json_response(
        services.history(
            request.GET.get("target", ""),
            _int(request, "target_id"),
            _int(request, "limit", services.HISTORY_MAX),
        )
    )
