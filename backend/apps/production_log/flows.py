"""설계 흐름(p15-s2-flows.md 3.10·3.11)의 정상 경로 단계 ID. 도식을 바꾸면 함께 바꾼다."""

FLOWS = {
    "PRC-NEW": ["PRC-NEW-01", "PRC-NEW-02", "PRC-NEW-03"],
    "PRC-UPD": ["PRC-UPD-01", "PRC-UPD-02", "PRC-UPD-03", "PRC-UPD-04"],
    "PRC-ACT": ["PRC-ACT-01"],
    "PRC-DEL": ["PRC-DEL-01", "PRC-DEL-02"],
    "PRC-LST": ["PRC-LST-01"],
    "TPL-NEW": ["TPL-NEW-01", "TPL-NEW-02", "TPL-NEW-03"],
    "TPL-UPD": ["TPL-UPD-01", "TPL-UPD-02", "TPL-UPD-03", "TPL-UPD-04"],
    "TPL-CPY": ["TPL-CPY-01", "TPL-CPY-02"],
    "TPL-ACT": ["TPL-ACT-01"],
    "TPL-DEL": ["TPL-DEL-01", "TPL-DEL-02"],
    "TPL-LST": ["TPL-LST-01"],
    "TPL-GET": ["TPL-GET-01"],
    "MST-HIS": ["MST-HIS-01"],
}


def _service_step(step_id):
    """비교 대상: 실패 갈래(끝 `a`)와 API 입력 단계(`-00`·`-00b`)는 뺀다(S4a 리뷰 C2)."""
    return not step_id.endswith("a") and not step_id.endswith(("-00", "-00b"))


def matches(flow_id, step_ids):
    return [s for s in step_ids if _service_step(s)] == FLOWS[flow_id]
