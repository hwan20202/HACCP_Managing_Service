"""개발 설정 전용: /api/v1/ 요청마다 처리 단계와 SQL을 기록한다.

- 응답 헤더 X-Trace-Id 로 trace를 식별하고, /api/dev/traces/<id> 로 다시 읽을 수 있다.
- JSON 객체 응답에는 "trace" 키도 붙인다(204처럼 본문이 없는 응답은 헤더만).
- 운영 설정에는 이 미들웨어가 등록되지 않는다(config/settings).
- P5: 작성 요구 개발 API(/api/dev/req/)도 기록한다(REQ-SC-04 "개발 콘솔에서 보기").
"""

import json
from collections import OrderedDict

from django.db import connection

from apps.core import trace as tracing

BUFFER_SIZE = 200
_buffer = OrderedDict()


def remember(trace_dict):
    _buffer[trace_dict["trace_id"]] = trace_dict
    while len(_buffer) > BUFFER_SIZE:
        _buffer.popitem(last=False)


def recall(trace_id):
    return _buffer.get(trace_id)


class TraceMiddleware:
    prefixes = ("/api/v1/", "/api/dev/req/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.path.startswith(self.prefixes):
            return self.get_response(request)
        current, token = tracing.start(request.method, request.get_full_path())
        try:
            with connection.execute_wrapper(tracing.SqlRecorder(current)):
                response = self.get_response(request)
        finally:
            tracing.stop(token)
        current.status = response.status_code
        data = current.as_dict()
        remember(data)
        response["X-Trace-Id"] = current.trace_id
        response["Access-Control-Expose-Headers"] = "X-Trace-Id"
        if response.get("Content-Type", "").startswith("application/json") and response.content:
            try:
                body = json.loads(response.content)
            except ValueError:
                body = None
            if isinstance(body, dict):
                body["trace"] = data
                response.content = json.dumps(body, ensure_ascii=False).encode("utf-8")
                response["Content-Length"] = str(len(response.content))
        return response
