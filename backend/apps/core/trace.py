"""Development-only processing trace.

Domain code marks its processing steps with ``step(...)``. Unless a trace was started for the
current request (only the devtools middleware does that, and only in development), every call
is a cheap no-op. Step IDs must match the flow diagrams in the design notes so the developer
console can compare the designed flow with what actually ran.
"""

import contextvars
import time
import uuid
from contextlib import contextmanager

_current = contextvars.ContextVar("haccp_trace", default=None)


class Step:
    __slots__ = ("step_id", "layer", "name", "result", "detail", "sql")

    def __init__(self, step_id, layer, name):
        self.step_id = step_id
        self.layer = layer
        self.name = name
        self.result = "pass"
        self.detail = ""
        self.sql = []

    def fail(self, detail):
        self.result = "fail"
        self.detail = str(detail)

    def skip(self, detail=""):
        self.result = "skip"
        self.detail = str(detail)

    def note(self, detail):
        """결과는 바꾸지 않고 설명만 남긴다(예: 조건부 UPDATE 영향 행 수)."""
        self.detail = str(detail)

    def as_dict(self):
        return {
            "step_id": self.step_id,
            "layer": self.layer,
            "name": self.name,
            "result": self.result,
            "detail": self.detail,
            "sql": self.sql,
        }


class _NullStep:
    def fail(self, detail):
        pass

    def skip(self, detail=""):
        pass

    def note(self, detail):
        pass


_NULL_STEP = _NullStep()


class Trace:
    def __init__(self, method="", path=""):
        self.trace_id = uuid.uuid4().hex[:12]
        self.method = method
        self.path = path
        self.status = None
        self.steps = []
        self.unassigned_sql = []
        self._open = []

    def record_sql(self, sql, params, elapsed_ms):
        entry = {"sql": sql, "params": _jsonable(params), "ms": round(elapsed_ms, 2)}
        (self._open[-1].sql if self._open else self.unassigned_sql).append(entry)

    def as_dict(self):
        return {
            "trace_id": self.trace_id,
            "method": self.method,
            "path": self.path,
            "status": self.status,
            "steps": [step.as_dict() for step in self.steps],
            "unassigned_sql": self.unassigned_sql,
        }


def _jsonable(params):
    if params is None:
        return None
    if isinstance(params, dict):
        return {key: _jsonable(value) for key, value in params.items()}
    if isinstance(params, (list, tuple)):
        return [_jsonable(value) for value in params]
    if isinstance(params, (str, int, float, bool)) or params is None:
        return params
    return str(params)


def current():
    return _current.get()


def start(method="", path=""):
    trace = Trace(method, path)
    token = _current.set(trace)
    return trace, token


def stop(token):
    _current.reset(token)


@contextmanager
def step(step_id, layer, name):
    trace = _current.get()
    if trace is None:
        yield _NULL_STEP
        return
    item = Step(step_id, layer, name)
    trace.steps.append(item)
    trace._open.append(item)
    try:
        yield item
    except Exception as error:
        if item.result == "pass":
            item.fail(getattr(error, "code", type(error).__name__))
        raise
    finally:
        trace._open.pop()


class SqlRecorder:
    """``connection.execute_wrapper`` callback that files SQL under the open step."""

    def __init__(self, trace):
        self.trace = trace

    def __call__(self, execute, sql, params, many, context):
        started = time.perf_counter()
        try:
            return execute(sql, params, many, context)
        finally:
            self.trace.record_sql(sql, params, (time.perf_counter() - started) * 1000)
