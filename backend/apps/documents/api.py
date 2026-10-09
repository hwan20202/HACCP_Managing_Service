"""문서 도메인 HTTP API (/api/v1/). 입출력만 담당하고 규칙은 services에 둔다.

CSRF: 계정·세션 쿠키가 없고, 쓰기 요청은 JSON 본문과 사용자 지정 헤더(X-Staff-Id)를 요구한다.
다른 출처의 단순 요청으로는 이 조건을 만들 수 없으므로 CSRF 토큰 검사는 하지 않는다.
"""

from django.http import HttpResponse
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
from apps.staff.services import actor_from_header

from . import errors, services

CREATE_KEYS = ("template_id", "subject", "work_date", "assignee_id", "due_at", "sections")
PATCH_KEYS = ("document", "sections")
PATCH_SECTION_KEYS = ("add", "update", "delete")


def _api(view):
    """도메인/API 예외를 공통 오류 응답으로 바꾼다."""

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


@require_http_methods(["GET"])
@_api
def staff_list(request):
    return json_response({"items": services.list_staff()})


@require_http_methods(["GET"])
@_api
def template_list(request):
    return json_response({"items": services.list_templates()})


@require_http_methods(["GET"])
@_api
def template_detail(request, template_id):
    return json_response(services.get_template(template_id))


@csrf_exempt
@require_http_methods(["GET", "POST"])
@_api
def document_collection(request):
    if request.method == "GET":
        query = request.GET
        filters = {
            key: query.get(key)
            for key in ("from", "to", "template_id", "status", "author_id", "assignee_id")
        }
        return json_response(services.list_documents(filters, query.get("page", "1")))

    with step("DOC-CRT-01", "API", "요청 형식 확인"):
        body = parse_json_body(request)
        reject_unknown_keys(body, CREATE_KEYS)
    actor = _actor(request, "DOC-CRT-02")
    return json_response(services.create_document(actor, body), status=201)


def _check_patch_shape(body):
    reject_unknown_keys(body, PATCH_KEYS)
    document = body.get("document", {})
    sections = body.get("sections", {})
    if not isinstance(document, dict) or not isinstance(sections, dict):
        raise ApiError("document, sections는 객체여야 합니다.")
    reject_unknown_keys(document, services.EDITABLE_FIELDS, "document.")
    reject_unknown_keys(sections, PATCH_SECTION_KEYS, "sections.")
    for key in PATCH_SECTION_KEYS:
        if not isinstance(sections.get(key, []), list):
            raise ApiError(f"sections.{key}는 목록이어야 합니다.")
    for item in sections.get("update", []):
        if not isinstance(item, dict) or not isinstance(item.get("section_id"), int):
            raise ApiError("sections.update 항목에는 section_id(정수)와 values가 필요합니다.")
    for item in sections.get("add", []):
        if not isinstance(item, dict):
            raise ApiError("sections.add 항목은 객체여야 합니다.")
    for item in sections.get("delete", []):
        if not isinstance(item, int) or isinstance(item, bool):
            raise ApiError("sections.delete 항목은 section_id(정수)여야 합니다.")
    if not document and not any(sections.get(key) for key in PATCH_SECTION_KEYS):
        raise errors.NoChanges()


@csrf_exempt
@require_http_methods(["GET", "PATCH", "DELETE"])
@_api
def document_item(request, document_id):
    if request.method == "GET":
        return json_response(services.get_document(document_id))

    if request.method == "PATCH":
        with step("DOC-UPD-01", "API", "요청 형식 확인"):
            body = parse_json_body(request)
            _check_patch_shape(body)
        actor = _actor(request, "DOC-UPD-02")
        return json_response(services.update_document(actor, document_id, body))

    actor = _actor(request, "DOC-DEL-01")
    services.delete_document(actor, document_id)
    return HttpResponse(status=204)
