"""EFF 흐름의 정상 경로 단계 ID(p6a-s2-flows 3장 EFF-JDG). DOC-SIG-01 안에서 실행된다."""

FLOWS = {
    "EFF-JDG": ["EFF-JDG-01", "EFF-JDG-02", "EFF-JDG-03", "EFF-JDG-04"],
}


def matches(flow_id, step_ids):
    return [s for s in step_ids if s.startswith("EFF-")] == FLOWS[flow_id]
