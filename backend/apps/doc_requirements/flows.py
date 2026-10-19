"""설계 흐름(dev-notes/doc-requirements/s2-flows.md 9장)의 정상 경로 단계 ID.

REQ 흐름은 DOC 단계(GOC·ARR·FND)를 안에 품고, 번호(#n)·공정 반복이 있다. 그래서 비교는
"이 흐름의 단계만 골라, 연속 반복을 하나로 줄인 순서가 같은지"로 본다(matches). 건너뛴 단계는
skip 결과로 trace에 남긴다. P6a(D-088): D03도 LOT마다 문서라 REQ-LOT-05(번호 반복)는 없다.
"""

LOT = [f"REQ-LOT-0{n}" for n in (0, 1, 2, 3, 4, 6)]
BAT = [f"REQ-BAT-0{n}" for n in range(0, 5)]

FLOWS = {
    "REQ-LOT": LOT,
    "REQ-BAT": BAT,
    "REQ-FND": [f"REQ-FND-0{n}" for n in range(1, 5)],
    "REQ-FND-B": ["REQ-FND-B01", "REQ-FND-B02"],
    "REQ-DEV-LOT": ["REQ-DEV-01", "REQ-DEV-02", *LOT, "REQ-DEV-04"],
    "REQ-DEV-BAT": ["REQ-DEV-01", "REQ-DEV-02", *BAT, "REQ-DEV-04"],
    "REQ-DEV-RE-LOT": ["REQ-DEV-01", "REQ-DEV-RE1", *LOT, "REQ-DEV-04"],
    # P6 D-080: inspection이 있으면 00b(형식 검사), 개발 API는 수불 대신 판정 반영(REQ-DEV-02b)
    "REQ-LOT-INSP": ["REQ-LOT-00", "REQ-LOT-00b", *LOT[1:]],
    "REQ-DEV-LOT-INSP": [
        "REQ-DEV-01",
        "REQ-DEV-02",
        "REQ-LOT-00",
        "REQ-LOT-00b",
        *LOT[1:],
        "REQ-DEV-02b",
        "REQ-DEV-04",
    ],
    "REQ-DEV-RE-BAT": ["REQ-DEV-01", "REQ-DEV-RE1", *BAT, "REQ-DEV-04"],
    # P7 입고일 묶음 조회(document-workflow/p7-s2-flows.md 7장) — 안에 DOC·APR 단계
    "REQ-BDL": [f"REQ-BDL-0{n}" for n in range(1, 8)],
    # P8 주 묶음 조회(document/p8-s2-spec.md 4.2 REQ-F06)
    "REQ-PWB": [f"REQ-PWB-0{n}" for n in range(1, 7)],
    # P9 주기형 작성 요구(doc-requirements/p9-s2-spec.md 6장)
    # 05는 만들 줄마다 반복(하나로 줄여 비교), 만들 줄이 없으면 PRN-NONE
    "REQ-PRN": [f"REQ-PRN-0{n}" for n in range(1, 7)],
    "REQ-PRN-NONE": ["REQ-PRN-01", "REQ-PRN-02", "REQ-PRN-03", "REQ-PRN-04", "REQ-PRN-06"],
    "REQ-POD": [f"REQ-POD-0{n}" for n in range(1, 5)],
    "REQ-PRL": ["REQ-PRL-01", "REQ-PRL-02"],
    # P10 작성 필요 목록(document-workflow/p10-s2-spec.md 5장) — 04 안에 DOC N7(DOC-RQD)
    "REQ-TDO": [f"REQ-TDO-0{n}" for n in range(1, 7)],
    # P11 CCP 현황(dashboard/p11-s2-spec.md 5장) — 04 안에 DOC N8(DOC-MSM)
    "REQ-CCP": [f"REQ-CCP-0{n}" for n in range(1, 6)],
}


def matches(flow_id, step_ids):
    expected = FLOWS[flow_id]
    wanted = set(expected)
    run = []
    for step_id in step_ids:
        if step_id in wanted and (not run or run[-1] != step_id):
            run.append(step_id)
    return run == expected
