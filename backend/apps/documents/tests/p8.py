"""P8 테스트 준비물 (p8-s2-spec 7장): 점검표 양식 D10·D12·D11 + 주기 작성 요구 문서.

주기 문서는 P9가 만들 때처럼 N1(get_or_create_document)로 만든다 — record_key `{코드}|day:{날짜}`
(D11은 `|week:{월요일}`, p9-s2-spec 3장). 날짜: 2026-10-12(월) ~ 10-16(금) 주, 11-02 = 11월 첫째 월.
"""

from contextlib import contextmanager

from django.db import transaction

from apps.core import trace
from apps.documents import services
from apps.documents.seed import ensure_p4_templates, ensure_p8_templates, ensure_staff
from apps.documents.seed_forms import D10, D11, D12

MON, TUE, WED, THU, FRI = "2026-10-12", "2026-10-13", "2026-10-14", "2026-10-15", "2026-10-16"
FIRST_MON = "2026-11-02"
SCHEMAS = {"D10": D10, "D11": D11, "D12": D12}


def setup_p8():
    ensure_staff(5)
    templates = ensure_p4_templates()
    templates.update(ensure_p8_templates())
    return templates


def periodic(code, day, values=None, actor=3):
    """주기 작성 요구 문서(N1). 반환 N1 결과의 문서 상세."""
    unit = "week" if code == "D11" else "day"
    with transaction.atomic():
        return services.get_or_create_document(
            actor, code, f"{code}|{unit}:{day}", day, [], values=values
        )["document"]


def checks_row(detail):
    return next(s for s in detail["sections"] if s["section_def"] == "checks")


def info_row(detail):
    return next(s for s in detail["sections"] if s["section_def"] == "info")


def result_keys(code):
    section = next(s for s in SCHEMAS[code]["sections"] if s["key"] == "checks")
    return [f["key"] for f in section["fields"] if f["type"] == "select"]


def fill(document_id, value="O", inspector=4, extra=None, actor=3):
    """점검자 + 모든 결과를 value로(NA가 있던 항목은 그대로) 저장. 반환 상세."""
    detail = services.get_document(document_id)
    checks, info = checks_row(detail), info_row(detail)
    code = detail["template"]["type_code"]
    values = {k: value for k in result_keys(code) if checks["values"].get(k) != "NA"}
    info_values = {"inspector": inspector}
    if code == "D12":
        info_values["process_name"] = "내포장"
    if code == "D11":
        info_values["checked_on"] = detail["work_date"]
    info_values.update((extra or {}).get("info", {}))
    values.update((extra or {}).get("checks", {}))
    return services.update_document(
        actor,
        document_id,
        {
            "expected_version": detail["version"],
            "sections": {
                "update": [
                    {"section_id": info["section_id"], "values": info_values},
                    {"section_id": checks["section_id"], "values": values},
                ]
            },
        },
    )


@contextmanager
def captured():
    """개발 trace를 켜고 실행된 단계 ID 목록을 돌려준다(블록이 끝난 뒤 채워짐)."""
    record, token = trace.start("TEST", "p8")
    ids = []
    try:
        yield ids
    finally:
        trace.stop(token)
        ids.extend(s.step_id for s in record.steps)
