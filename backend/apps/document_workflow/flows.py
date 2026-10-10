"""설계 흐름(dev-notes/document-workflow/s2-flows.md 7장)의 정상 경로 단계 ID.

WF 단계 안에 도메인 단계가 이어서 기록된다. 도식을 바꾸면 이 목록도 함께 바꾼다.
"""

_SUB = (
    ["WF-SUB-01", "WF-SUB-02", "WF-SUB-03", "APR-VAL-01", "APR-VAL-02", "APR-VAL-03"]
    + ["WF-SUB-04", "WF-SUB-05", "DOC-LCK-00", "DOC-LCK-01", "DOC-LCK-02"]
    + ["WF-SUB-06", "DOC-GET-01", "DOC-GET-02", "DOC-GET-03"]
    + ["WF-SUB-07", *[f"APR-OPN-0{n}" for n in range(0, 6)], "WF-SUB-08"]
)
_DEC_HEAD = ["WF-DEC-01", "WF-DEC-02", "WF-DEC-03", "WF-DEC-04"] + [
    f"APR-DEC-0{n}" for n in range(0, 6)
]

FLOWS = {
    "WF-SUB": _SUB,
    "WF-DEC-PROGRESS": [*_DEC_HEAD, "WF-DEC-05", "WF-DEC-06"],
    "WF-DEC-APPROVED": [*_DEC_HEAD, "WF-DEC-05", "DOC-APV-01", "DOC-APV-02", "WF-DEC-06"],
    "WF-DEC-REJECTED": [*_DEC_HEAD, "WF-DEC-05", "DOC-RJT-01", "DOC-RJT-02", "WF-DEC-06"],
}


def matches(flow_id, step_ids):
    """정상 경로 단계가 빠짐없이 순서대로 실행됐는지 본다(실패 분기 a 단계는 제외)."""
    return [s for s in step_ids if not s.endswith("a")] == FLOWS[flow_id]
