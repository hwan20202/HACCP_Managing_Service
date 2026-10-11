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
    "DOC-UPD": [
        "DOC-UPD-01",
        "DOC-UPD-02",
        "DOC-UPD-03",
        "DOC-UPD-04",
        "DOC-UPD-05",
        "DOC-UPD-05b",  # P4: computed 재계산
        "DOC-UPD-06",
        "DOC-UPD-07",
        "DOC-UPD-08",
        "DOC-UPD-09",
        "DOC-UPD-10",
    ],
    "DOC-DEL": ["DOC-DEL-01", "DOC-DEL-02", "DOC-DEL-03"],
    "DOC-LCK": ["DOC-LCK-00", "DOC-LCK-01", "DOC-LCK-02"],
    "DOC-APV": ["DOC-APV-01", "DOC-APV-02"],
    "DOC-RJT": ["DOC-RJT-01", "DOC-RJT-02"],
    # P4 (dev-notes/document/p4-s2-flows.md)
    "DOC-CMP": ["DOC-CMP-01", "DOC-CMP-02", "DOC-CMP-03", "DOC-CMP-04"],
    "DOC-ROP": ["DOC-ROP-01", "DOC-ROP-02", "DOC-ROP-03"],
    "DOC-DVC": ["DOC-DVC-00", "DOC-DVC-01", "DOC-DVC-02", "DOC-DVC-03", "DOC-DVC-04"],
    "DOC-DVU": ["DOC-DVU-00", "DOC-DVU-01", "DOC-DVU-02", "DOC-DVU-03", "DOC-DVU-04"],
    "DOC-DVD": ["DOC-DVD-01", "DOC-DVD-02"],
    # 작성 요구(REQ) 전용 내부 함수: API 단계 없음. 01a(이미 있음/이미 연결됨)는 분기라 제외
    "DOC-GOC": [f"DOC-GOC-0{n}" for n in range(0, 6)],
    "DOC-ARR": [f"DOC-ARR-0{n}" for n in range(0, 7)],
    "DOC-FND": ["DOC-FND-01"],
}


def matches(flow_id, step_ids):
    """정상 경로 단계가 빠짐없이 순서대로 실행됐는지 본다."""
    return [s for s in step_ids if not s.endswith("a")] == FLOWS[flow_id]
