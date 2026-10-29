"""설계 흐름의 정상 경로 단계 ID(P16 묶음 ① — p16-s2-spec 3.2 F10·F11·F20).

코드를 바꾸면 함께 바꾼다.
"""

FLOWS = {
    "ADM-CCP-LST": ["ADM-CCP-LST-01", "ADM-CCP-LST-02"],
    "ADM-CCP-SAV": ["ADM-CCP-SAV-01", "ADM-CCP-SAV-02", "ADM-CCP-SAV-03", "ADM-CCP-SAV-04"],
    "ADM-HIS": ["ADM-HIS-01"],
}
API_WRITES = ("ADM-CCP-SAV",)
# 같은 값 저장(changed false)은 저장·이력 단계 없이 끝남 — 콘솔이 누락으로 세지 않음
OPTIONAL = {"ADM-CCP-SAV": ["ADM-CCP-SAV-03", "ADM-CCP-SAV-04"]}


def _service_step(step_id):
    """비교 대상: 실패 갈래(끝 `a`)와 API 입력 단계(`-00`·`-00b`)는 뺀다(P15와 같은 규칙)."""
    return not step_id.endswith("a") and not step_id.endswith(("-00", "-00b"))


def matches(flow_id, step_ids):
    return [s for s in step_ids if _service_step(s)] == FLOWS[flow_id]


# 개발 콘솔: API 호출 전체 trace 비교 — 쓰기는 API 입력 단계(-00) 먼저
# (`-00b`는 콘솔이 실패 갈래 규칙으로 뺌 — production_log/flows.py와 같음)
CONSOLE = {k: ([f"{k}-00"] if k in API_WRITES else []) + v for k, v in FLOWS.items()}
