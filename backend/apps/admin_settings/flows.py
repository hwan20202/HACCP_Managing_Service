"""설계 흐름의 정상 경로 단계 ID(P16 — p16-s2-spec 3.2 F10~F20).

코드를 바꾸면 함께 바꾼다.
"""

FLOWS = {
    "ADM-CCP-LST": ["ADM-CCP-LST-01", "ADM-CCP-LST-02"],
    "ADM-CCP-SAV": ["ADM-CCP-SAV-01", "ADM-CCP-SAV-02", "ADM-CCP-SAV-03", "ADM-CCP-SAV-04"],
    "ADM-HIS": ["ADM-HIS-01"],
    # 묶음 ② 직원(F12~F15·F17)·문서 권한(F18·F19)
    "ADM-STF-LST": ["ADM-STF-LST-01"],
    "ADM-STF-COD": ["ADM-STF-COD-01"],
    "ADM-STF-NEW": ["ADM-STF-NEW-01", "ADM-STF-NEW-02", "ADM-STF-NEW-03", "ADM-STF-NEW-04"],
    "ADM-STF-REN": ["ADM-STF-REN-01", "ADM-STF-REN-02", "ADM-STF-REN-03"],
    "ADM-STF-ACT": ["ADM-STF-ACT-01", "ADM-STF-ACT-02", "ADM-STF-ACT-03", "ADM-STF-ACT-04"],
    # 01 안에서 DOC 활성 양식 목록(DOC-TPL-01)을 읽는다 — A07(ADM-STF-IMP)과 같음(D-274)
    "ADM-ROL-GET": ["ADM-ROL-GET-01", "DOC-TPL-01", "ADM-ROL-GET-02"],
    "ADM-ROL-SAV": [f"ADM-ROL-SAV-{n:02d}" for n in range(1, 8)],
    # 묶음 ③ 비활성 영향(F16) — APR·DOC 읽기 함수 단계 포함
    "ADM-STF-IMP": [
        "ADM-STF-IMP-01",
        "ADM-STF-IMP-02",
        "DOC-TPL-01",
        "ADM-STF-IMP-03",
        "APR-IMP-01",
        "APR-IMP-02",
        "ADM-STF-IMP-04",
        "DOC-IMP-01",
        "DOC-IMP-02",
    ],
}
API_WRITES = ("ADM-CCP-SAV", "ADM-STF-NEW", "ADM-STF-REN", "ADM-STF-ACT", "ADM-ROL-SAV")
# 같은 값 저장(changed false)은 저장·이력 단계 없이 끝남 — 콘솔이 누락으로 세지 않음.
# 직원·문서 권한은 같은 값이어도 단계는 지나고(skip) 안에서 건너뜀 — 조건부 없음
OPTIONAL = {"ADM-CCP-SAV": ["ADM-CCP-SAV-03", "ADM-CCP-SAV-04"]}


def _service_step(step_id):
    """비교 대상: 실패 갈래(끝 `a`)·API 입력 단계(`-00`·`-00b`)·역할 읽기(ROLE-CFG)는 뺀다."""
    return (
        not step_id.endswith("a")
        and not step_id.endswith(("-00", "-00b"))
        and not step_id.startswith("ROLE-CFG")
    )


def matches(flow_id, step_ids):
    return [s for s in step_ids if _service_step(s)] == FLOWS[flow_id]


# 개발 콘솔: API 호출 전체 trace 비교 — 쓰기는 API 입력 단계(-00) 먼저
# (`-00b`는 콘솔이 실패 갈래 규칙으로 뺌 — production_log/flows.py와 같음)
CONSOLE = {k: ([f"{k}-00"] if k in API_WRITES else []) + v for k, v in FLOWS.items()}
