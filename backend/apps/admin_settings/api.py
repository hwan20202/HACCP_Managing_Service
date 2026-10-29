"""관리 설정 HTTP API (/api/v1/admin/…) — 묶음 ① A01·A02·A11, 묶음 ② A03~A06·A08~A10,
묶음 ③ A07.

입출력만(p16-s2-spec 4장).
- 읽기는 헤더 없이, 쓰기는 X-Staff-Id(누구나 — R27)와 expected_version(낙관적 잠금 — R10).
- 예외: 직원 등록(A05)·다시 활성(A08)은 현재 사용자가 없거나 활성이 아니면 처음 설정으로 본다
  — 서비스가 같은 트랜잭션에서 활성 직원 0명인지 확인(R62).
- CSRF: 문서 API와 달리 **검사를 끄지 않는다**(R71).
  화면은 `csrftoken` 쿠키(첫 화면 `home`이 발급) 값을 `X-CSRFToken`에 실어 보낸다.
"""

from django.db import transaction
from django.views.decorators.http import require_http_methods

from apps.core.http import ApiError, error_response, json_response, parse_json_body
from apps.core.trace import step
from apps.staff.services import InvalidStaff, StaffHeaderMissing, actor_from_header

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
    with step("ADM-CCP-SAV-00", "API", "요청 형식 확인"):
        body = parse_json_body(request)
    with step("ADM-CCP-SAV-00b", "API", "현재 사용자 확인"):
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


def _actor_or_setup(request):
    """현재 사용자 id, 없거나 활성이 아니면 None(처음 설정 후보 — 서비스가 R62 판정)."""
    try:
        return actor_from_header(request.headers.get("X-Staff-Id"))
    except StaffHeaderMissing, InvalidStaff:
        return None


# ---------------------------------------------------------------- 직원 (묶음 ②)


@require_http_methods(["GET", "POST"])
@_api
def staff_collection(request):
    """A03 GET ?q=&state= · A05 POST {name, staff_code}."""
    if request.method == "GET":
        return json_response(
            services.staff_list(request.GET.get("q", ""), request.GET.get("state", "all"))
        )
    with step("ADM-STF-NEW-00", "API", "요청 형식 확인"):
        body = parse_json_body(request)
    with step("ADM-STF-NEW-00b", "API", "현재 사용자 확인(없으면 처음 설정)"):
        actor = _actor_or_setup(request)
    with transaction.atomic():
        return json_response(services.create_staff(actor, body), status=201)


@require_http_methods(["GET"])
@_api
def staff_next_code(request):
    """A04: 코드 제안."""
    return json_response(services.suggest_staff_code())


@require_http_methods(["PATCH"])
@_api
def staff_item(request, staff_id):
    """A06: {name}."""
    with step("ADM-STF-REN-00", "API", "요청 형식 확인"):
        body = parse_json_body(request)
    with step("ADM-STF-REN-00b", "API", "현재 사용자 확인"):
        actor = actor_from_header(request.headers.get("X-Staff-Id"))
    with transaction.atomic():
        return json_response(services.rename_staff(actor, staff_id, body))


@require_http_methods(["GET"])
@_api
def staff_impact(request, staff_id):
    """A07: 비활성 영향(읽기 — 헤더 없이도. 헤더가 있으면 is_current_user)."""
    raw = request.headers.get("X-Staff-Id", "")
    current = int(raw) if raw.isascii() and raw.isdigit() else None
    return json_response(services.staff_impact(staff_id, current))


@require_http_methods(["POST"])
@_api
def staff_active(request, staff_id):
    """A08: {active, confirm_impact?}."""
    with step("ADM-STF-ACT-00", "API", "요청 형식 확인"):
        body = parse_json_body(request)
    with step("ADM-STF-ACT-00b", "API", "현재 사용자 확인(없으면 처음 설정 — 다시 활성만)"):
        actor = _actor_or_setup(request)
    with transaction.atomic():
        return json_response(services.set_staff_active(actor, staff_id, body))


# ---------------------------------------------------------------- 문서 권한 (묶음 ②)


@require_http_methods(["GET", "PUT"])
@_api
def roles_view(request):
    """A09 GET · A10 PUT {expected_version, leaders, forms{type:{owners, writers}}}."""
    if request.method == "GET":
        return json_response(services.roles_for_edit())
    with step("ADM-ROL-SAV-00", "API", "요청 형식 확인"):
        body = parse_json_body(request)
    with step("ADM-ROL-SAV-00b", "API", "현재 사용자 확인"):
        actor = actor_from_header(request.headers.get("X-Staff-Id"))
    with transaction.atomic():
        return json_response(services.save_roles(actor, body))
