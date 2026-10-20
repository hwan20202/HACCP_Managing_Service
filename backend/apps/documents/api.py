"""문서 도메인 HTTP API (/api/v1/). 입출력만 담당하고 규칙은 services에 둔다.

CSRF: 계정·세션 쿠키가 없고, 쓰기 요청은 JSON 본문과 사용자 지정 헤더(X-Staff-Id)를 요구한다.
다른 출처의 단순 요청으로는 이 조건을 만들 수 없으므로 CSRF 토큰 검사는 하지 않는다.
"""

from django.http import FileResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from apps.core import batch
from apps.core.http import (
    ApiError,
    error_response,
    json_response,
    parse_json_body,
    reject_unknown_keys,
)
from apps.core.trace import step
from apps.staff.services import actor_from_header, optional_actor_from_header

from . import errors, files, services

CREATE_KEYS = ("template_id", "subject", "work_date", "due_at", "sections")  # P14: assignee_id 없앰
PATCH_KEYS = ("expected_version", "document", "sections")
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
def roles_view(request):
    """P14 ROLE-A01 역할 보기(읽기 전용, 헤더 선택 — 있으면 me)."""
    actor = optional_actor_from_header(request.headers.get("X-Staff-Id"))
    return json_response(services.roles_summary(actor))


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
            for key in (
                "from",
                "to",
                "template_id",
                "status",
                "author_id",
                "owner_id",
                "target",
                "correcting",
            )
        }
        return json_response(services.list_documents(filters, query.get("page", "1")))

    with step("DOC-CRT-01", "API", "요청 형식 확인"):
        body = parse_json_body(request)
        reject_unknown_keys(body, CREATE_KEYS)
    actor = _actor(request, "DOC-CRT-02")
    return json_response(services.create_document(actor, body), status=201)


def _check_patch_shape(body):
    reject_unknown_keys(body, PATCH_KEYS)
    services._expected_version(body)  # DOC-VR-14: 없거나 형식이 틀리면 400 INVALID_REQUEST
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
        actor = optional_actor_from_header(request.headers.get("X-Staff-Id"))
        document = services.get_document(document_id)
        return json_response({**document, **services.document_roles(document, actor)})

    if request.method == "PATCH":
        with step("DOC-UPD-01", "API", "요청 형식 확인"):
            body = parse_json_body(request)
            _check_patch_shape(body)
        actor = _actor(request, "DOC-UPD-02")
        return json_response(services.update_document(actor, document_id, body))

    actor = _actor(request, "DOC-DEL-01")
    services.delete_document(actor, document_id)
    return HttpResponse(status=204)


# ---------------------------------------------------------------- P4: 작성완료·재개, 개선조치

DEVIATION_PATCH_KEYS = ("expected_version", *services.DEVIATION_FIELDS)


def _version_body(request, step_id):
    """{expected_version}만 받는 요청. 반환: (actor, expected_version)."""
    with step(step_id, "API", "요청 형식·사용자 확인"):
        body = parse_json_body(request)
        reject_unknown_keys(body, ("expected_version",))
        expected = services._expected_version(body)
        actor = actor_from_header(request.headers.get("X-Staff-Id"))
    return actor, expected


@csrf_exempt
@require_http_methods(["POST"])
@_api
def document_complete(request, document_id):
    """DOC-A09 작성완료."""
    with step("DOC-CMP-01", "API", "요청 형식·사용자 확인"):
        body = parse_json_body(request)
        reject_unknown_keys(body, ("expected_version", "note"))  # note: D-080 판정 변경 사유
        expected = services._expected_version(body)
        actor = actor_from_header(request.headers.get("X-Staff-Id"))
    return json_response(services.complete_document(actor, document_id, expected, body.get("note")))


@csrf_exempt
@require_http_methods(["POST"])
@_api
def document_reopen(request, document_id):
    """DOC-A10 작성 재개."""
    actor, expected = _version_body(request, "DOC-ROP-01")
    return json_response(services.reopen_document(actor, document_id, expected))


@csrf_exempt
@require_http_methods(["POST"])
@_api
def document_correction(request, document_id):
    """DOC-A18 정정 시작 {expected_version, reason}. 판정 순서: 형식 → 사용자 → 사유 → 404 → 409."""
    with step("DOC-COR-01", "API", "요청 형식·사용자 확인"):
        body = parse_json_body(request)
        reject_unknown_keys(body, ("expected_version", "reason"))
        expected = services._expected_version(body)
        actor = actor_from_header(request.headers.get("X-Staff-Id"))
    return json_response(
        services.start_correction(actor, document_id, expected, body.get("reason"))
    )


@csrf_exempt
@require_http_methods(["POST"])
@_api
def document_correction_cancel(request, document_id):
    """DOC-A19 정정 취소 {expected_version} (D-075)."""
    actor, expected = _version_body(request, "DOC-CCN-01")
    return json_response(services.cancel_correction(actor, document_id, expected))


@csrf_exempt
@require_http_methods(["POST"])
@_api
def deviation_collection(request, document_id):
    """DOC-A15 개선조치 쓰기."""
    with step("DOC-DVC-00", "API", "요청 형식·사용자 확인"):
        body = parse_json_body(request)
        reject_unknown_keys(body, services.DEVIATION_FIELDS)
        actor = actor_from_header(request.headers.get("X-Staff-Id"))
    return json_response(services.create_deviation(actor, document_id, body), status=201)


@csrf_exempt
@require_http_methods(["PATCH", "DELETE"])
@_api
def deviation_item(request, deviation_id):
    """DOC-A16 개선조치 수정 / DOC-A17 삭제."""
    if request.method == "PATCH":
        with step("DOC-DVU-00", "API", "요청 형식·사용자 확인"):
            body = parse_json_body(request)
            reject_unknown_keys(body, DEVIATION_PATCH_KEYS)
            expected = services._expected_version(body)
            actor = actor_from_header(request.headers.get("X-Staff-Id"))
        patch = {k: v for k, v in body.items() if k != "expected_version"}
        return json_response(services.update_deviation(actor, deviation_id, expected, patch))

    with step("DOC-DVD-01", "API", "요청 형식·사용자 확인"):
        raw = request.GET.get("expected_version") or ""
        expected = int(raw) if raw.isascii() and raw.isdigit() else 0
        if expected < 1:
            raise ApiError(
                "expected_version(1 이상 정수)이 필요합니다.",
                [{"path": "expected_version", "code": "required", "message": "필수입니다."}],
            )
        actor = actor_from_header(request.headers.get("X-Staff-Id"))
    services.delete_deviation(actor, deviation_id, expected)
    return HttpResponse(status=204)


# ---------------------------------------------------------------- P7: 점검자 일괄 지정·문서 요약


@csrf_exempt
@require_http_methods(["POST"])
@_api
def batch_inspector(request):
    """DOC-A20 점검자 일괄 지정 {items: [{document_id, expected_version}], inspector_id}."""
    with step("DOC-BIN-01", "API", "요청 형식·사용자 확인"):
        body = parse_json_body(request)
        reject_unknown_keys(body, ("items", "inspector_id"))
        batch.version_items(body.get("items"), "items")
        if "inspector_id" not in body:
            raise ApiError(
                "inspector_id가 필요합니다.",
                [{"path": "inspector_id", "code": "required", "message": "필수 값입니다."}],
            )
        actor = actor_from_header(request.headers.get("X-Staff-Id"))
    return json_response(services.batch_set_inspector(actor, body["items"], body["inspector_id"]))


@require_http_methods(["GET"])
@_api
def document_brief(request):
    """DOC-A21 문서 요약 여러 건 ?ids=58,67,73 (1~50개)."""
    raw = request.GET.get("ids") or ""
    parts = [p.strip() for p in raw.split(",")] if raw.strip() else []
    if not parts:
        raise errors.InvalidFilter(
            details=[{"path": "ids", "code": "required", "message": "문서 id를 지정하세요."}]
        )
    if any(not (p.isascii() and p.isdigit()) or int(p) < 1 for p in parts):
        raise errors.InvalidFilter(
            details=[{"path": "ids", "code": "invalid", "message": "쉼표로 구분한 양의 정수"}]
        )
    if len(parts) > services.BRIEF_MAX:
        raise errors.InvalidFilter(
            details=[{"path": "ids", "code": "max", "message": f"최대 {services.BRIEF_MAX}개"}]
        )
    return json_response(services.brief_documents([int(p) for p in parts]))


# ---------------------------------------------------------------- P8: 작성 안 함·되돌리기·최근 값


@csrf_exempt
@require_http_methods(["POST"])
@_api
def batch_skip(request):
    """DOC-A24 작성 안 함 {items: [{document_id, expected_version}] (1~50), reason} (F27)."""
    with step("DOC-SKP-01", "API", "요청 형식·사용자 확인"):
        body = parse_json_body(request)
        reject_unknown_keys(body, ("items", "reason"))
        actor = actor_from_header(request.headers.get("X-Staff-Id"))
    return json_response(services.skip_documents(actor, body.get("items"), body.get("reason")))


@csrf_exempt
@require_http_methods(["POST"])
@_api
def document_unskip(request, document_id):
    """DOC-A25 되돌리기 {expected_version} (F28)."""
    actor, expected = _version_body(request, "DOC-USK-01")
    return json_response(services.unskip_document(actor, document_id, expected))


@require_http_methods(["GET"])
@_api
def recent_values(request):
    """DOC-A26 최근 값 ?type_code=D12&field=process_name[&section=] (F29). 헤더 불필요."""
    reject_unknown_keys(request.GET, ("type_code", "field", "section"))
    return json_response(
        services.recent_values(
            request.GET.get("type_code"),
            request.GET.get("section") or None,
            request.GET.get("field"),
        )
    )


# ---------------------------------------------------------------- 스프린트 3: 파일 (DOC-A11~A14)


def _positive_int(raw, path):
    raw = str(raw or "").strip()
    value = int(raw) if raw.isascii() and raw.isdigit() else 0
    if value < 1:
        raise ApiError(
            f"{path}(1 이상 정수)이 필요합니다.",
            [{"path": path, "code": "required", "message": "1 이상의 정수여야 합니다."}],
        )
    return value


def _multipart_upload(request):
    """multipart: file 1개 + expected_version. 반환: (upload, expected_version)."""
    reject_unknown_keys(request.POST, ("expected_version",))
    reject_unknown_keys(request.FILES, ("file",))
    uploads = request.FILES.getlist("file")
    if len(uploads) != 1:
        raise ApiError(
            "파일은 한 요청에 1개씩 올립니다.",
            [{"path": "file", "code": "required", "message": "file 1개가 필요합니다."}],
        )
    return uploads[0], _positive_int(request.POST.get("expected_version"), "expected_version")


@csrf_exempt
@require_http_methods(["POST"])
@_api
def document_files(request, document_id):
    """DOC-A11 파일 올리기(multipart, F14) 또는 기존 파일 연결(F15).

    연결은 JSON {expected_version, link_file_id}.

    CSRF: 다른 출처의 multipart 단순 요청도 X-Staff-Id 헤더는 붙일 수 없어(사전 요청 필요) 거부된다.
    """
    if (request.content_type or "").startswith("multipart/form-data"):
        with step("DOC-FUP-01", "API", "요청 형식·사용자 확인"):
            upload, expected = _multipart_upload(request)
            actor = actor_from_header(request.headers.get("X-Staff-Id"))
        return json_response(files.attach_file(actor, document_id, expected, upload), status=201)

    with step("DOC-FLK-01", "API", "요청 형식·사용자 확인"):
        body = parse_json_body(request)
        reject_unknown_keys(body, ("expected_version", "link_file_id"))
        expected = services._expected_version(body)
        file_id = body.get("link_file_id")
        if isinstance(file_id, bool) or not isinstance(file_id, int) or file_id < 1:
            raise ApiError(
                "link_file_id(1 이상 정수)이 필요합니다.",
                [{"path": "link_file_id", "code": "required", "message": "필수입니다."}],
            )
        actor = actor_from_header(request.headers.get("X-Staff-Id"))
    return json_response(files.link_file(actor, document_id, expected, file_id), status=201)


@csrf_exempt
@require_http_methods(["DELETE"])
@_api
def document_file_item(request, document_id, file_id):
    """DOC-A12 파일 연결 끊기 ?expected_version=n (F16)."""
    with step("DOC-FDT-01", "API", "요청 형식·사용자 확인"):
        expected = _positive_int(request.GET.get("expected_version"), "expected_version")
        actor = actor_from_header(request.headers.get("X-Staff-Id"))
    return json_response(files.detach_file(actor, document_id, expected, file_id))


@require_http_methods(["GET"])
@_api
def file_collection(request):
    """DOC-A14 이전 파일 검색 (F18). 읽기라 X-Staff-Id 불필요."""
    keys = ("type_code", "item", "supplier", "days", "page")
    reject_unknown_keys(request.GET, keys)
    return json_response(files.search_files({k: request.GET.get(k) for k in keys}))


@require_http_methods(["GET"])
@_api
def file_item(request, file_id):
    """DOC-A13 파일 보기 (F17). 내용을 inline으로 보낸다. 읽기라 X-Staff-Id 불필요."""
    path, name, mime = files.open_file(file_id)
    response = FileResponse(open(path, "rb"), content_type=mime, filename=name)
    response["Cache-Control"] = "private, no-store"
    return response
