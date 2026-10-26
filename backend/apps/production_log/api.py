"""생산 기준정보 HTTP API (/api/v1/) — PLG-A06 공정 · A07 템플릿 · A08 변경 이력. 입출력만.

읽기는 헤더 없이, 쓰기는 X-Staff-Id(누구나 — PLG-R12)와 expected_version(낙관적 잠금).
CSRF: 문서 API와 같은 이유로 토큰 검사를 하지 않는다(apps/documents/api.py 머리말).
"""

from django.db import transaction
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from apps.core.http import ApiError, error_response, json_response, parse_json_body
from apps.core.trace import step
from apps.staff.services import actor_from_header

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


def _actor(request, step_id):
    with step(step_id, "API", "현재 사용자 확인"):
        return actor_from_header(request.headers.get("X-Staff-Id"))


def _version_from(body):
    value = body.pop("expected_version", None)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ApiError(
            "expected_version(1 이상 정수)이 필요합니다.",
            [{"path": "expected_version", "code": "required", "message": "필수입니다."}],
        )
    return value


def _version_from_query(request):
    raw = request.GET.get("expected_version") or ""
    value = int(raw) if raw.isascii() and raw.isdigit() else 0
    if value < 1:
        raise ApiError(
            "expected_version(1 이상 정수)이 필요합니다.",
            [{"path": "expected_version", "code": "required", "message": "필수입니다."}],
        )
    return value


def _write(fn, *args):
    with transaction.atomic():
        return fn(*args)


# ---------------------------------------------------------------- A06 공정


@csrf_exempt
@require_http_methods(["GET", "POST"])
@_api
def processes(request):
    """GET 목록(q·kind·status) / POST 일반 공정 추가."""
    if request.method == "GET":
        q = request.GET
        return json_response(
            services.list_processes(q.get("q", ""), q.get("kind", "all"), q.get("status", "active"))
        )
    with step("PRC-NEW-00", "API", "요청 형식 확인"):
        body = parse_json_body(request)
    actor = _actor(request, "PRC-NEW-00b")
    return json_response(_write(services.create_process, actor, body), status=201)


@csrf_exempt
@require_http_methods(["GET", "PATCH", "DELETE"])
@_api
def process_item(request, process_id):
    if request.method == "GET":
        return json_response(services.get_process(process_id))
    if request.method == "PATCH":
        with step("PRC-UPD-00", "API", "요청 형식 확인"):
            body = parse_json_body(request)
            version = _version_from(body)
        actor = _actor(request, "PRC-UPD-00b")
        return json_response(_write(services.update_process, actor, process_id, body, version))
    with step("PRC-DEL-00", "API", "요청 형식 확인"):
        version = _version_from_query(request)
    actor = _actor(request, "PRC-DEL-00b")
    _write(services.delete_process, actor, process_id, version)
    return HttpResponse(status=204)


@csrf_exempt
@require_http_methods(["POST"])
@_api
def process_active(request, process_id):
    """{active, expected_version} 사용 중지·다시 사용."""
    with step("PRC-ACT-00", "API", "요청 형식 확인"):
        body = parse_json_body(request)
        version = _version_from(body)
    actor = _actor(request, "PRC-ACT-00b")
    return json_response(
        _write(services.set_process_active, actor, process_id, body.get("active"), version)
    )


# ---------------------------------------------------------------- A07 공정 템플릿


@csrf_exempt
@require_http_methods(["GET", "POST"])
@_api
def templates(request):
    if request.method == "GET":
        q = request.GET
        return json_response(services.list_templates(q.get("q", ""), q.get("status", "active")))
    with step("TPL-NEW-00", "API", "요청 형식 확인"):
        body = parse_json_body(request)
    actor = _actor(request, "TPL-NEW-00b")
    return json_response(_write(services.create_template, actor, body), status=201)


@csrf_exempt
@require_http_methods(["GET", "PATCH", "DELETE"])
@_api
def template_item(request, template_id):
    if request.method == "GET":
        return json_response(services.get_template(template_id))
    if request.method == "PATCH":
        with step("TPL-UPD-00", "API", "요청 형식 확인"):
            body = parse_json_body(request)
            version = _version_from(body)
        actor = _actor(request, "TPL-UPD-00b")
        return json_response(_write(services.update_template, actor, template_id, body, version))
    with step("TPL-DEL-00", "API", "요청 형식 확인"):
        version = _version_from_query(request)
    actor = _actor(request, "TPL-DEL-00b")
    _write(services.delete_template, actor, template_id, version)
    return HttpResponse(status=204)


@csrf_exempt
@require_http_methods(["POST"])
@_api
def template_copy(request, template_id):
    actor = _actor(request, "TPL-CPY-00b")
    return json_response(_write(services.copy_template, actor, template_id), status=201)


@csrf_exempt
@require_http_methods(["POST"])
@_api
def template_active(request, template_id):
    with step("TPL-ACT-00", "API", "요청 형식 확인"):
        body = parse_json_body(request)
        version = _version_from(body)
    actor = _actor(request, "TPL-ACT-00b")
    return json_response(
        _write(services.set_template_active, actor, template_id, body.get("active"), version)
    )


# ---------------------------------------------------------------- A08 변경 이력


@require_http_methods(["GET"])
@_api
def master_history(request):
    """?target=process|template&id=n"""
    raw = request.GET.get("id") or ""
    target_id = int(raw) if raw.isascii() and raw.isdigit() else 0
    return json_response(services.history(request.GET.get("target", ""), target_id))
