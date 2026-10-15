"""문서 결정 규칙 상수(s2-spec 2.4, D-050 Q2, D-065 Q6). 실제 목록을 받으면 상수만 바꾼다."""

INCOMING = "INCOMING"
CANCELLED = "CANCELLED"  # 생산 쪽 실제 상태 이름 확인 요청(requests-p5 X2, REQ-S2-Q9)
LOT_DOCUMENTS = ("D01", "D02", "D03")  # 모든 입고 LOT(REQ-S2-Q3). D03도 LOT마다 1건(P6a, D-084)
D03 = "D03"
D03_INSPECTION = "inspection"  # D03 v2 검사 섹션 — 승인본 판정을 읽는 곳(F03)
# F01 inspection(D-080, P6-VR-07): 문서 쪽이 정하는 입력 형식 = D03 v2 inspection 섹션의 입력 항목.
# 값(선택지)은 DOC N1이 양식 규칙으로 검사한다. 양식 항목이 바뀌면 이 상수도 바꾼다.
D03_INSPECTION_KEYS = ("appearance", "packaging", "labeling", "verdict", "has_coa")
D03_INSPECTION_REQUIRED = ("appearance", "packaging", "labeling", "verdict")

# P8 REQ-F06: 주 묶음 조회 대상(하루 문서를 월~금으로 모아 보는 양식, DOC BUNDLE_UNITS week와 같음)
WEEK_BUNDLE_TYPES = ("D10", "D12")

# 공정 유형 → CCP 공정 목록, 품목 id → 예외 목록
CCP_PROCESSES = {"MANUFACTURE": ["1P", "2B", "3P"], "PACKAGING": []}
CCP_BY_ITEM = {}


def lot_key(type_code, lot_id):
    return f"{type_code}|lot:{lot_id}"


def ccp_type(process):
    return f"CCP-{process}"


def ccp_key(process, batch_id):
    return f"{ccp_type(process)}|batch:{batch_id}"


def processes_for(item_id, process_type):
    if item_id in CCP_BY_ITEM:
        return list(CCP_BY_ITEM[item_id])
    return list(CCP_PROCESSES.get(process_type, []))


def process_of(type_code):
    """F04 process_code: 'CCP-1P' → '1P'(DOC 변경 없이 type_code에서 계산, s2-spec 2.5)."""
    return type_code[4:] if type_code.startswith("CCP-") else None
