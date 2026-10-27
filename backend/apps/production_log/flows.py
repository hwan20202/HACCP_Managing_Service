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


# ---------------------------------------------------------------- 개발 콘솔 흐름 (P15 S5b)
# 콘솔은 API 호출 전체 trace를 비교한다 — 서비스 흐름(FLOWS) 앞에 API 입력 단계(`-00`,
# `-00b`는 콘솔이 실패 갈래 규칙으로 뺌)를 붙이고, 생산일지 저장·작성완료·작성 재개는 DOC 흐름
# 사이에 끼는 확장 단계(DOC-EXT·PLG-SAV/CMP/ROP·REQ-PLS·DOC-SEC/BRF/SYS)까지 실행 순서대로 둔다
# (p15-s2-flows.md r4 3.3·3.8·3.9).
WRT = ["DOC-WRT-01", "DOC-WRT-02"]
API_WRITES = (
    "PRC-NEW",
    "PRC-UPD",
    "PRC-ACT",
    "PRC-DEL",
    "TPL-NEW",
    "TPL-UPD",
    "TPL-ACT",
    "TPL-DEL",
)
SAVE_CHECK = [
    "DOC-EXT-01",
    "PLG-SAV-01",
    "REQ-PLS-02",
    "PLG-SAV-02",
    "PLG-SAV-03",
    "DOC-BRF-01",
    "PLG-SAV-04",
    "PLG-SAV-05",
    "PLG-SAV-06",
]
CONSOLE = {
    **{k: ([f"{k}-00"] if k in API_WRITES else []) + v for k, v in FLOWS.items()},
    "PLG-LNK": [
        "PLG-LNK-01",
        "DOC-SEC-01",
        "PLG-LNK-02",
        "PLG-LNK-03",
        "REQ-PLS-01",
        "PLG-LNK-04",
        "PLG-LNK-05",
        "DOC-LSV-01",
        "DOC-BRF-01",
    ],
    "PLG-TPL": [
        "PLG-TPL-00",
        "PLG-TPL-01",
        *WRT,
        "DOC-SEC-01",
        "REQ-PLS-02",
        "PLG-TPL-02",
        "PLG-TPL-03",
        "DOC-BRF-01",
        "PLG-TPL-04",
        "PLG-TPL-05",
        "PLG-TPL-06",
    ],
    "PLG-TSV": [
        "PLG-TSV-00",
        "PLG-TSV-01",
        *WRT,
        "DOC-SEC-01",
        "PLG-TSV-02",
        "PLG-TSV-03",
        "PLG-TSV-04",
        "TPL-NEW-01",
        "TPL-NEW-02",
        "TPL-NEW-03",
        "TPL-GET-01",
        "PLG-TSV-05",
    ],
    "PLG-REG": [
        "PLG-REG-00",
        "PLG-REG-01",
        *WRT,
        "DOC-SEC-01",
        "PLG-REG-02",
        "PLG-REG-03",
        "PRC-NEW-01",
        "PRC-NEW-02",
        "PRC-NEW-03",
        "PLG-REG-04",
    ],
    "PLG-CCP": [
        "PLG-CCP-01",
        "DOC-SEC-01",
        "PLG-CCP-02",
        "DOC-BRF-01",
        "DOC-SEC-01",
        "PLG-CCP-03",
        "PLG-CCP-04",
    ],
    # 생산일지 저장 = DOC-UPD + 확장 검사(N12)
    "PLG-SAV": [
        "DOC-UPD-01",
        "DOC-UPD-02",
        *WRT,
        "DOC-UPD-03",
        "DOC-UPD-04",
        "DOC-UPD-05",
        *SAVE_CHECK,
        "DOC-UPD-05b",
        "DOC-EXT-01b",
        "DOC-UPD-06",
        "DOC-UPD-07",
        "DOC-UPD-08",
        "DOC-UPD-08b",
        "DOC-UPD-09",
        "DOC-UPD-10",
    ],
    "PLG-CMP": [
        "DOC-CMP-01",
        *WRT,
        "DOC-CMP-02",
        "DOC-CMP-03",
        "DOC-EXT-02",
        "PLG-CMP-01",
        "REQ-PLS-02",
        "PLG-CMP-02",
        "PLG-CMP-03",
        "PLG-CMP-03b",
        "PLG-CMP-03c",
        "DOC-BRF-01",
        "DOC-EXT-03",
        "DOC-SEC-01",
        "PLG-CMP-04",
        "REQ-PLS-01",
        "DOC-SYS-01",
        "DOC-SIG-01",
        "DOC-CMP-04",
    ],
    "PLG-ROP": [
        "DOC-ROP-01",
        *WRT,
        "DOC-ROP-02",
        "DOC-EXT-03",
        "DOC-SEC-01",
        "PLG-ROP-01",
        "REQ-PLS-02",
        "PLG-ROP-02",
        "DOC-SYS-01",
        "DOC-SIG-01",
        "DOC-ROP-03",
    ],
}
# 조건부 단계 — 흐름별(S5b r1 B3: 다른 단위 흐름의 필수 단계를 숨기지 않게).
# CCP 행이 없으면 CCP 일지 찾기(DOC-BRF-01) 없음, 작성완료 전이면 고정 섹션(PLG-LNK-02) 없음
OPTIONAL = {
    **{k: ["DOC-BRF-01"] for k, v in CONSOLE.items() if "DOC-BRF-01" in v},
    "PLG-LNK": ["PLG-LNK-02", "DOC-BRF-01"],
}
