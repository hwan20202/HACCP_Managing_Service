"""설계 흐름(dev-notes/document-workflow/s2-flows.md 7장)의 정상 경로 단계 ID.

WF 단계 안에 도메인 단계가 이어서 기록된다. 도식을 바꾸면 이 목록도 함께 바꾼다.
"""

_SUB = (
    ["WF-SUB-01", "WF-SUB-02", "WF-SUB-03", "APR-VAL-01", "APR-VAL-02", "APR-VAL-03"]
    + ["WF-SUB-04", "WF-SUB-05", "DOC-LCK-00", "DOC-LCK-01", "DOC-LCK-02"]
    + ["WF-SUB-06", "DOC-GET-01", "DOC-GET-02", "DOC-GET-03"]
    + ["WF-SUB-07", *[f"APR-OPN-0{n}" for n in range(0, 6)], "WF-SUB-08"]
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
        "head": ["WF-BSB-01", "WF-BSB-02", "WF-BSB-03", "APR-VAL-01", "APR-VAL-02", "APR-VAL-03"]
        + ["WF-BSB-04", *[f"DOC-BRF-0{n}" for n in range(1, 5)], "WF-BSB-05"],
        "items": {"submitted": ["WF-BSB-06", *_SUB[7:-1], "WF-BSB-06b"]},
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
    }
)


def matches_batch(flow_id, step_ids):
    """일괄 흐름: 머리 → (항목 단계 묶음 중 하나) × n(≥1) → 꼬리. 실패 분기 a 단계는 제외.

    반환: 항목마다 고른 묶음 이름 목록(일치하지 않으면 None).
    """
    spec = BATCH[flow_id]
    steps = [s for s in step_ids if not s.endswith("a")]
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


def matches(flow_id, step_ids):
    """정상 경로 단계가 빠짐없이 순서대로 실행됐는지 본다(실패 분기 a 단계는 제외)."""
    return [s for s in step_ids if not s.endswith("a")] == FLOWS[flow_id]
