"""설계 흐름(dev-notes/doc-requirements/s2-flows.md 9장)의 정상 경로 단계 ID.

REQ 흐름은 DOC 단계(GOC·ARR·FND)를 안에 품고, 번호(#n)·공정 반복이 있다. 그래서 비교는
"이 흐름의 단계만 골라, 연속 반복을 하나로 줄인 순서가 같은지"로 본다(matches). 건너뛴 단계는
skip 결과로 trace에 남긴다(예: 이미 있는 D03 행이면 REQ-LOT-05 skip).
"""

LOT = [f"REQ-LOT-0{n}" for n in range(0, 7)]
BAT = [f"REQ-BAT-0{n}" for n in range(0, 5)]

FLOWS = {
    "REQ-LOT": LOT,
    "REQ-BAT": BAT,
    "REQ-FND": [f"REQ-FND-0{n}" for n in range(1, 5)],
    "REQ-FND-B": ["REQ-FND-B01", "REQ-FND-B02"],
    "REQ-DEV-LOT": ["REQ-DEV-01", "REQ-DEV-02", *LOT, "REQ-DEV-04"],
    "REQ-DEV-BAT": ["REQ-DEV-01", "REQ-DEV-02", *BAT, "REQ-DEV-04"],
    "REQ-DEV-RE-LOT": ["REQ-DEV-01", "REQ-DEV-RE1", *LOT, "REQ-DEV-04"],
    "REQ-DEV-RE-BAT": ["REQ-DEV-01", "REQ-DEV-RE1", *BAT, "REQ-DEV-04"],
}


def matches(flow_id, step_ids):
    expected = FLOWS[flow_id]
    wanted = set(expected)
    run = []
    for step_id in step_ids:
        if step_id in wanted and (not run or run[-1] != step_id):
            run.append(step_id)
    return run == expected
