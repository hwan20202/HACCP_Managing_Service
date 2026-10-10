"""설계 흐름(dev-notes/approval/s2-flows.md)의 정상 경로 단계 ID. 도식을 바꾸면 함께 바꾼다."""

FLOWS = {
    "APR-VAL": ["APR-VAL-01", "APR-VAL-02", "APR-VAL-03"],
    "APR-OPN": [f"APR-OPN-0{n}" for n in range(0, 6)],
    "APR-DEC": [f"APR-DEC-0{n}" for n in range(0, 6)],
    "APR-GET": ["APR-GET-01", "APR-GET-02", "APR-GET-03"],
    "APR-HIS": ["APR-HIS-01", "APR-HIS-02", "APR-HIS-03"],
    "APR-INB": [f"APR-INB-0{n}" for n in range(0, 6)],
}


def matches(flow_id, step_ids):
    return [s for s in step_ids if not s.endswith("a")] == FLOWS[flow_id]
