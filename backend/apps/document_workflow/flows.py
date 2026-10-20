"""설계 흐름(dev-notes/document-workflow/s2-flows.md 7장)의 정상 경로 단계 ID.

WF 단계 안에 도메인 단계가 이어서 기록된다. 도식을 바꾸면 이 목록도 함께 바꾼다.
"""

# P14(p14-s2-flows.md 3.2): 결재선 검증(APR-VAL) 대신 양식 유형 → 설정 상태·권한 → 결재선 구성
_LINE = ["WF-SUB-02b", "WF-SUB-03", "WF-SUB-03b"]
_OPN = [*[f"APR-OPN-0{n}" for n in range(0, 5)], "APR-OPN-04b", "APR-OPN-05"]
_SUB = (
    ["WF-SUB-01", "WF-SUB-02", *_LINE]
    + ["WF-SUB-04", "WF-SUB-05", "DOC-LCK-00", "DOC-LCK-01", "DOC-LCK-01b", "DOC-LCK-02"]
    + ["WF-SUB-06", "DOC-GET-01", "DOC-GET-02", "DOC-GET-03"]
    + ["WF-SUB-07", *_OPN, "WF-SUB-08"]
)
_DEC_HEAD = ["WF-DEC-01", "WF-DEC-02", "WF-DEC-03", "WF-DEC-04"] + [
    f"APR-DEC-0{n}" for n in range(0, 6)
]

FLOWS = {
    "WF-SUB": _SUB,
    "WF-DEC-PROGRESS": [*_DEC_HEAD, "WF-DEC-05", "WF-DEC-06"],
    # P6: DOC 생명주기 신호(DOC-SIG-01)가 DOC 단계 안에 더해진다
    "WF-DEC-APPROVED": [
        *_DEC_HEAD,
        "WF-DEC-05",
        "DOC-APV-01",
        "DOC-SIG-01",
        "DOC-APV-02",
        "WF-DEC-06",
    ],
    "WF-DEC-REJECTED": [
        *_DEC_HEAD,
        "WF-DEC-05",
        "DOC-RJT-01",
        "DOC-SIG-01",
        "DOC-RJT-02",
        "WF-DEC-06",
    ],
}


# P7 일괄 (p7-s2-flows 11장). 항목 단계(06 … 06b)가 항목 수만큼 반복된다. FLOWS에는 항목 1개일 때를
# 두고, 여러 항목은 matches_batch로 본다(콘솔의 항목별 비교는 S5).
_APV = ["DOC-APV-01", "DOC-SIG-01", "DOC-APV-02"]
_DEC_ITEM = ["WF-DEC-04", *[f"APR-DEC-0{n}" for n in range(0, 6)], "WF-DEC-05"]
BATCH = {
    "WF-BAP": {
        "head": ["WF-BAP-01", "WF-BAP-02", "WF-BAP-03", "WF-BAP-04", "APR-SRF-01", "DOC-TPL-01"]
        + ["WF-BAP-05"],
        "items": {
            "approved": ["WF-BAP-06", *_DEC_ITEM, *_APV, "WF-BAP-06b"],
            "progress": ["WF-BAP-06", *_DEC_ITEM, "WF-BAP-06b"],
        },
        "tail": ["WF-BAP-07"],
    },
    "WF-BSB": {
        # P14: 03(문서마다 권한·결재선)은 04 뒤. 03 안의 _LINE은 문서 수만큼 반복되므로 머리에는
        # 한 번만 두고, 두 번째부터는 head_skip으로 뺀다(matches_batch)
        "head": ["WF-BSB-01", "WF-BSB-02", "WF-BSB-04", *[f"DOC-BRF-0{n}" for n in range(1, 5)]]
        + ["WF-BSB-03", *_LINE, "WF-BSB-05"],
        "head_skip": list(_LINE),
        "items": {"submitted": ["WF-BSB-06", *_SUB[6:-1], "WF-BSB-06b"]},
        "tail": ["WF-BSB-07"],
    },
}
FLOWS.update(
    {
        "WF-BAP": [*BATCH["WF-BAP"]["head"], *BATCH["WF-BAP"]["items"]["approved"], "WF-BAP-07"],
        "WF-BAP-PROGRESS": [
            *BATCH["WF-BAP"]["head"],
            *BATCH["WF-BAP"]["items"]["progress"],
            "WF-BAP-07",
        ],
        "WF-BSB": [*BATCH["WF-BSB"]["head"], *BATCH["WF-BSB"]["items"]["submitted"], "WF-BSB-07"],
        "WF-CFG": ["WF-CFG-01", "WF-CFG-02", "DOC-TPL-01"],
        # P10 상신 취소(p10-s2-spec 5장): API 사용자 확인 → [APR A7 → DOC F23] 한 트랜잭션
        # P12 출력(p12-s4-impl.md): API 조건 → 종이 종류 → [DOC N9 → APR A12] → 값 출처 → 조립
        "WF-PRT": ["WF-PRT-00", "WF-PRT-01", "WF-PRT-02", "DOC-PRT-01"]
        + ["APR-PRT-01", "APR-PRT-02", "WF-PRT-03", "WF-PRT-04"],
        "WF-PRT-NOT-PRINTABLE": ["WF-PRT-00", "WF-PRT-01", "WF-PRT-02", "DOC-PRT-01"],
        "WF-CAN": ["WF-CAN-01", "WF-CAN-01b", "WF-CAN-02", "WF-CAN-03"]
        + [f"APR-CAN-0{n}" for n in range(0, 4)]
        + ["WF-CAN-04", "DOC-ULK-00", "DOC-ULK-01", "DOC-ULK-02", "WF-CAN-05"],
    }
)


def matches_batch(flow_id, step_ids):
    """일괄 흐름: 머리 → (항목 단계 묶음 중 하나) × n(≥1) → 꼬리. 실패 분기 a 단계는 제외.

    반환: 항목마다 고른 묶음 이름 목록(일치하지 않으면 None).
    """
    spec = BATCH[flow_id]
    steps = [s for s in _normal(step_ids)]
    skip = set(spec.get("head_skip", ()))
    if skip and spec["head"][-1] in steps:
        cut, seen, kept = steps.index(spec["head"][-1]), set(), []
        for s in steps[:cut]:
            if s in skip and s in seen:
                continue  # 두 번째 문서부터의 반복
            seen.add(s)
            kept.append(s)
        steps = kept + steps[cut:]
    head, tail = spec["head"], spec["tail"]
    if steps[: len(head)] != head or steps[len(steps) - len(tail) :] != tail:
        return None
    body, kinds = steps[len(head) : len(steps) - len(tail)], []
    while body:
        for name, item in spec["items"].items():
            if body[: len(item)] == item:
                kinds.append(name)
                body = body[len(item) :]
                break
        else:
            return None
    return kinds or None


def _normal(step_ids):
    """실패 분기(a)와 역할 설정 읽기(ROLE-CFG)를 뺀다.

    ROLE-CFG는 서버 시작 뒤 처음 한 번만 나온다(테스트는 매번).
    """
    return [s for s in step_ids if not s.endswith("a") and not s.startswith("ROLE-CFG")]


def matches(flow_id, step_ids):
    """정상 경로 단계가 빠짐없이 순서대로 실행됐는지 본다(실패 분기 a 단계는 제외)."""
    return _normal(step_ids) == FLOWS[flow_id]
