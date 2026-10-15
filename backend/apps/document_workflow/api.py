"""문서 워크플로우 HTTP API (/api/v1/) — 상신, 승인·반려. 입출력만 담당한다(WF-NFR-03).

CSRF: 문서 API와 같은 이유로 토큰 검사를 하지 않는다(apps/documents/api.py 머리말).
"""

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
from apps.staff.services import actor_from_header

from . import services

SUBMIT_KEYS = ("expected_version", "slots")
DECISION_KEYS = ("result", "comment")


def _api(view):
    def wrapper(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except ApiError as error:
            return error_response(error)

    wrapper.__name__ = view.__name__
    wrapper.__doc__ = view.__doc__
    return wrapper


def _required(body, key):
    if key not in body:
        raise ApiError(
            "필수 값이 없습니다.",
            [{"path": key, "code": "required", "message": "필수 값입니다."}],
        )


def _actor(request, step_id):
    with step(step_id, "API", "현재 사용자 확인"):
        return actor_from_header(request.headers.get("X-Staff-Id"))


@csrf_exempt
@require_http_methods(["POST"])
@_api
def submit(request, document_id):
    """WF-A01 상신·재상신."""
    with step("WF-SUB-01", "API", "입력 형식 확인"):
        body = parse_json_body(request)
        reject_unknown_keys(body, SUBMIT_KEYS)
        _required(body, "expected_version")
        _required(body, "slots")
        version = body["expected_version"]
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise ApiError(
                "expected_version은 1 이상의 정수여야 합니다.",
                [{"path": "expected_version", "code": "invalid", "message": "1 이상의 정수"}],
            )
    actor = _actor(request, "WF-SUB-02")
    result = services.submit(actor, document_id, version, body["slots"])
    return json_response(result, status=201)


@csrf_exempt
@require_http_methods(["POST"])
@_api
def decision(request, approval_id):
    """WF-A02 승인·반려."""
    with step("WF-DEC-01", "API", "입력 형식 확인"):
        body = parse_json_body(request)
        reject_unknown_keys(body, DECISION_KEYS)
        _required(body, "result")
    actor = _actor(request, "WF-DEC-02")
    return json_response(services.decide(actor, approval_id, body["result"], body.get("comment")))


# ---------------------------------------------------------------- P7 일괄 (p7-s2-spec 3.1)

BATCH_DECISION_KEYS = ("approval_ids", "comment")
BATCH_SUBMIT_KEYS = ("items", "slots")


@csrf_exempt
@require_http_methods(["POST"])
@_api
def batch_decision(request):
    """WF-A03 일괄 승인 {approval_ids, comment?} — 반려 없음(result 키 없음, S1 Q2)."""
    with step("WF-BAP-01", "API", "입력 형식 확인"):
        body = parse_json_body(request)
        reject_unknown_keys(body, BATCH_DECISION_KEYS)
        _required(body, "approval_ids")
        batch.id_list(body["approval_ids"], "approval_ids")
    actor = _actor(request, "WF-BAP-02")
    return json_response(services.batch_approve(actor, body["approval_ids"], body.get("comment")))


@csrf_exempt
@require_http_methods(["POST"])
@_api
def batch_submit(request):
    """WF-A04 일괄 상신 {items: [{document_id, expected_version}], slots}."""
    with step("WF-BSB-01", "API", "입력 형식 확인"):
        body = parse_json_body(request)
        reject_unknown_keys(body, BATCH_SUBMIT_KEYS)
        _required(body, "items")
        _required(body, "slots")
        batch.version_items(body["items"], "items")
    actor = _actor(request, "WF-BSB-02")
    return json_response(services.batch_submit(actor, body["items"], body["slots"]))


@require_http_methods(["GET"])
@_api
def batch_config(request):
    """WF-A05 일괄 설정 조회."""
    return json_response(services.batch_config())


# ---------------------------------------------------------------- P10 상신 취소 (p10-s2-spec 3.1)


@csrf_exempt
@require_http_methods(["POST"])
@_api
def cancel_submission(request, request_id):
    """WF-F05 상신 취소 — 본문 없음(보내면 빈 객체만 허용, 사유 받지 않음)."""
    actor = _actor(request, "WF-CAN-01")
    if request.body.strip():
        reject_unknown_keys(parse_json_body(request), ())
    return json_response(services.cancel_submission(actor, request_id))
