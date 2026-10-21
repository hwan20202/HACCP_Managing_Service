"""설계 흐름(dev-notes/approval/s2-flows.md)의 정상 경로 단계 ID. 도식을 바꾸면 함께 바꾼다."""

FLOWS = {
    "APR-VAL": ["APR-VAL-01", "APR-VAL-02", "APR-VAL-03"],
    "APR-OPN": [f"APR-OPN-0{n}" for n in range(0, 5)]
    + ["APR-OPN-04b", "APR-OPN-05"],  # P14 04b 후보
    "APR-DEC": [f"APR-DEC-0{n}" for n in range(0, 6)],
    "APR-GET": ["APR-GET-01", "APR-GET-02", "APR-GET-03", "APR-GET-04"],  # P6: 03 다음 승인 회차
    "APR-HIS": ["APR-HIS-01", "APR-HIS-02", "APR-HIS-03"],
    "APR-INB": [f"APR-INB-0{n}" for n in range(0, 6)],
    # P5 A8 (doc-requirements/s2-spec.md 4.2): REQ docs_for_lot의 REQ-FND-03 안에서 실행
    "APR-LAT": ["APR-LAT-01"],
    # P7 (document-workflow/p7-s2-flows.md 11장): A9 칸 출처, A10 문서별 진행·최근 결재선
    "APR-SRF": ["APR-SRF-01"],
    "APR-PRG": ["APR-PRG-01"],  # P14: 02(최근 결재선) 없앰
}


def matches(flow_id, step_ids):
    return [s for s in step_ids if not s.endswith("a")] == FLOWS[flow_id]
