"""Small helpers shared by the JSON APIs under /api/v1/."""

import json

from django.http import JsonResponse


class ApiError(Exception):
    """An error that maps directly to the common error response."""

    status = 400
    code = "INVALID_REQUEST"
    message = "요청 형식이 올바르지 않습니다."

    def __init__(self, message=None, details=None, *, code=None, status=None):
        super().__init__(message or self.message)
        self.message = message or self.message
        self.details = details or []
        if code:
            self.code = code
        if status:
            self.status = status


def error_response(error):
    body = {"code": error.code, "message": error.message, "details": error.details}
    return JsonResponse(body, status=error.status, json_dumps_params={"ensure_ascii": False})


def json_response(data, status=200):
    return JsonResponse(data, status=status, safe=False, json_dumps_params={"ensure_ascii": False})


def parse_json_body(request):
    content_type = request.content_type or ""
    if content_type != "application/json":
        raise ApiError("본문은 application/json 이어야 합니다.")
    try:
        body = json.loads(request.body.decode("utf-8") or "null")
    except (UnicodeDecodeError, ValueError) as error:
        raise ApiError("본문이 올바른 JSON이 아닙니다.") from error
    if not isinstance(body, dict):
        raise ApiError("본문은 JSON 객체여야 합니다.")
    return body


def reject_unknown_keys(body, allowed, path=""):
    unknown = sorted(set(body) - set(allowed))
    if unknown:
        raise ApiError(
            "허용되지 않은 키가 있습니다.",
            [
                {
                    "path": f"{path}{key}",
                    "code": "unknown_key",
                    "message": "허용되지 않은 키입니다.",
                }
                for key in unknown
            ],
        )
