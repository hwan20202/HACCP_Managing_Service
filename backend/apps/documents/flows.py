"""설계 흐름(dev-notes/document/s2-flows.md)의 정상 경로 단계 ID.

개발 콘솔은 실제 trace와 이 목록을 비교해 일치 여부를 보여주고, 테스트(DOC-TC-091)도
이 목록으로 순서를 확인한다. 도식을 바꾸면 이 목록도 함께 바꾼다.
"""

FLOWS = {
    "DOC-STF": ["DOC-STF-01"],
    "DOC-TPL-LIST": ["DOC-TPL-01"],
    "DOC-TPL-GET": ["DOC-TPL-02"],
    "DOC-LST": ["DOC-LST-01", "DOC-LST-02", "DOC-LST-03", "DOC-LST-04"],
    "DOC-GET": ["DOC-GET-01", "DOC-GET-02", "DOC-GET-03"],
    "DOC-CRT": [f"DOC-CRT-0{n}" for n in range(1, 10)],
    "DOC-UPD": [f"DOC-UPD-{n:02d}" for n in range(1, 11)],
    "DOC-DEL": ["DOC-DEL-01", "DOC-DEL-02", "DOC-DEL-03"],
    "DOC-LCK": ["DOC-LCK-00", "DOC-LCK-01", "DOC-LCK-02"],
    "DOC-APV": ["DOC-APV-01", "DOC-APV-02"],
    "DOC-RJT": ["DOC-RJT-01", "DOC-RJT-02"],
}


def matches(flow_id, step_ids):
    """정상 경로 단계가 빠짐없이 순서대로 실행됐는지 본다."""
    return [s for s in step_ids if not s.endswith("a")] == FLOWS[flow_id]
