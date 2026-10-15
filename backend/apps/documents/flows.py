"""설계 흐름(dev-notes/document/s2-flows.md)의 정상 경로 단계 ID.

개발 콘솔은 실제 trace와 이 목록을 비교해 일치 여부를 보여주고, 테스트(DOC-TC-091)도
이 목록으로 순서를 확인한다. 도식을 바꾸면 이 목록도 함께 바꾼다.
"""

FLOWS = {
    "DOC-STF": ["DOC-STF-01"],
    "DOC-TPL-LIST": ["DOC-TPL-01"],
    "DOC-TPL-GET": ["DOC-TPL-02"],
    # P7: 02·03 UNION, 04 문서 줄 값, 05 묶음 집계, 06 묶음 전체 건수, 07 조립(p7-s2-flows 6장)
    "DOC-LST": [f"DOC-LST-0{n}" for n in range(1, 8)],
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
    # 01b: 연결 파일 보존 표시(스프린트 3)
    "DOC-LCK": ["DOC-LCK-00", "DOC-LCK-01", "DOC-LCK-01b", "DOC-LCK-02"],
    # P6: 생명주기 함수는 상태 변경 뒤 DOC-SIG-01(신호)을 지난다(p6-s2-spec 4.7)
    "DOC-APV": ["DOC-APV-01", "DOC-SIG-01", "DOC-APV-02"],
    "DOC-RJT": ["DOC-RJT-01", "DOC-SIG-01", "DOC-RJT-02"],
    # P4 (dev-notes/document/p4-s2-flows.md)
    "DOC-CMP": ["DOC-CMP-01", "DOC-CMP-02", "DOC-CMP-03", "DOC-SIG-01", "DOC-CMP-04"],
    "DOC-ROP": ["DOC-ROP-01", "DOC-ROP-02", "DOC-SIG-01", "DOC-ROP-03"],
    "DOC-DVC": ["DOC-DVC-00", "DOC-DVC-01", "DOC-DVC-02", "DOC-DVC-03", "DOC-DVC-04"],
    "DOC-DVU": ["DOC-DVU-00", "DOC-DVU-01", "DOC-DVU-02", "DOC-DVU-03", "DOC-DVU-04"],
    "DOC-DVD": ["DOC-DVD-01", "DOC-DVD-02"],
    # 작성 요구(REQ) 전용 내부 함수: API 단계 없음. 01a(이미 있음/이미 연결됨)는 분기라 제외
    "DOC-GOC": [f"DOC-GOC-0{n}" for n in range(0, 6)],
    "DOC-ARR": [f"DOC-ARR-0{n}" for n in range(0, 7)],
    "DOC-FND": ["DOC-FND-01"],
    # P6 정정 (dev-notes/document-workflow/p6-s2-flows.md 2·2.1장)
    "DOC-COR": [*[f"DOC-COR-0{n}" for n in range(1, 5)], "DOC-SIG-01", "DOC-COR-05"],
    "DOC-CCN": [*[f"DOC-CCN-0{n}" for n in range(1, 4)], "DOC-SIG-01", "DOC-CCN-04"],
    # P7 (dev-notes/document-workflow/p7-s2-flows.md 4·5장, 11장). DOC-BIN은 문서 1건일 때
    # (04~06이 문서마다 반복 — 콘솔 비교는 항목별 묶음, S5). 같은 값이면 05 → 05a(성공)
    "DOC-BIN": [f"DOC-BIN-0{n}" for n in range(1, 8)],
    "DOC-BRF": [f"DOC-BRF-0{n}" for n in range(1, 5)],
    "DOC-FNL": ["DOC-FNL-01"],
    # 스프린트 3 파일 (p4-s2-flows 6장). FDT-05(파일 행 삭제)는 마지막 연결·보존 없음일 때만
    "DOC-FUP": [f"DOC-FUP-0{n}" for n in range(1, 7)],
    "DOC-FLK": [f"DOC-FLK-0{n}" for n in range(1, 6)],
    "DOC-FDT": [f"DOC-FDT-0{n}" for n in range(1, 5)],
    # C3 S5: 마지막 연결이라 파일까지 지우는 경로(05 = 커밋 뒤 삭제) — 콘솔이 trace로 고름
    "DOC-FDT-DEL": [f"DOC-FDT-0{n}" for n in range(1, 6)],
    "DOC-FSR": ["DOC-FSR-01", "DOC-FSR-02"],
    # P8 (dev-notes/document/p8-s2-spec.md 6장). DOC-SKP는 문서 1건일 때(04·05가 문서마다 반복)
    "DOC-SKP": [f"DOC-SKP-0{n}" for n in range(1, 7)],
    "DOC-USK": ["DOC-USK-01", "DOC-USK-02", "DOC-USK-03"],
    "DOC-RCV": ["DOC-RCV-01", "DOC-RCV-02"],
    "DOC-DAT": ["DOC-DAT-01"],
}

# P7 S5: 개발 콘솔의 항목별 비교(WF BATCH와 같은 모양: 머리 → 항목 × n → 꼬리).
# 끝이 a인 단계는 비교에서 빠지므로 같은 값(05 → 05a 성공)은 "same" = 04·05
BATCH = {
    "DOC-BIN": {
        "head": ["DOC-BIN-01", "DOC-BIN-02", "DOC-BIN-03"],
        "items": {
            "changed": ["DOC-BIN-04", "DOC-BIN-05", "DOC-BIN-06"],
            "same": ["DOC-BIN-04", "DOC-BIN-05"],
        },
        "tail": ["DOC-BIN-07"],
    },
    "DOC-SKP": {
        "head": ["DOC-SKP-01", "DOC-SKP-02", "DOC-SKP-03"],
        "items": {"skipped": ["DOC-SKP-04", "DOC-SKP-05"]},
        "tail": ["DOC-SKP-06"],
    },
}


def _group(step_id):
    return step_id.rsplit("-", 1)[0]  # DOC-CMP-03 → DOC-CMP


def matches(flow_id, step_ids):
    """정상 경로 단계가 빠짐없이 순서대로 실행됐는지 본다.

    P6: 생명주기 신호(DOC-SIG-01) 안에서 실행된 받는 쪽 단계(EFF-…와 그 안의 DOC 조회)만 건너뛴다.
    신호 다음에 이 흐름의 단계 묶음이 다시 나오면 신호 구간이 끝난 것이다. 그 밖에 다른 묶음의
    단계가 끼면 불일치로 잡힌다(P6 S4b 검토 B1).
    """
    expected = FLOWS[flow_id]
    groups = {_group(s) for s in expected} - {"DOC-SIG"}
    own, inside_signal = [], False
    for step_id in step_ids:
        if step_id.endswith("a"):
            continue
        if step_id == "DOC-SIG-01":
            own.append(step_id)
            inside_signal = True
            continue
        if inside_signal:
            if _group(step_id) not in groups:
                continue
            inside_signal = False
        own.append(step_id)
    return own == expected
