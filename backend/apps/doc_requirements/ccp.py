"""CCP 현황 REQ-F11 (dev-notes/dashboard/p11-s2-spec.md 2.1).

- 쓰기·트랜잭션 없음. 어떤 양식이 CCP인지는 REQ 상수(rules.CCP_PROCESSES·CCP_BY_ITEM)만 안다.
  DOC N8(measurement_summary)에 양식 목록을 넘겨 측정 요약·이탈 행·개선조치를 받는다.
- 결과는 사용자에 따라 달라지지 않는다(X-Staff-Id 선택 — B2).
- 계층(NFR-03): DOC 서비스만 부른다.
"""

from apps.core.trace import step
from apps.documents import services as doc

from . import errors, periodic, rules

TODO_STATUSES = doc.TODO_STATUSES  # P10 REQ-F10 "작성 필요"와 같은 집합(S1a-Q4 a)
# 측정 섹션 밖에서 배치 줄에 합계로 보여 줄 값(B6): 양식 → (반복 섹션, 필드)
SUMMARY_TOTALS = {"CCP-3P": ("summary", "detected_qty")}


def _bad(path, message):
    return errors.InvalidFilter(details=[{"path": path, "code": "invalid", "message": message}])


def ccp_types():
    """CCP 양식 코드(CCP_PROCESSES 값 전체 + 품목 예외, 처음 나온 순서)."""
    seen = []
    for processes in [*rules.CCP_PROCESSES.values(), *rules.CCP_BY_ITEM.values()]:
        for process in processes:
            code = rules.ccp_type(process)
            if code not in seen:
                seen.append(code)
    return seen


def _deviation_state(items):
    """한 이탈 행의 개선조치 상태(B4): none → pending → no_checker → checked."""
    if not items:
        return {"state": "none"}
    pending = [x for x in items if x["checked_at"] is None and x["checker_ids"]]
    loose = [x for x in items if x["checked_at"] is None and not x["checker_ids"]]
    if pending:
        state, rep = "pending", pending[0]
    elif loose:
        state, rep = "no_checker", loose[0]
    else:
        state, rep = "checked", items[0]
    out = {"state": state, "deviation_id": rep["deviation_id"], "checker_ids": rep["checker_ids"]}
    if state == "checked":
        out.update(checked_by=rep["checked_by"], checked_at=rep["checked_at"])
    return out


def _total(document, type_code):
    spec = SUMMARY_TOTALS.get(type_code)
    if not spec:
        return None
    section, field = spec
    values = [v.get(field) for v in document["repeat_values"].get(section, [])]
    numbers = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    return sum(numbers) if numbers else 0


def _batch_row(document):
    row_count = sum(document["rows_by_section"].values())
    latest = document["latest"]
    row = {
        "document_id": document["document_id"],
        "version": document["version"],
        "status": document["status"],
        "label": document["label"],
        "item_name": document["item_name"],
        "row_count": row_count,
        "latest": latest,
        "nonconforming_count": len(document["nonconforming"]),
        "deviation_count": len(document["deviations"]),
        "todo": document["status"] in TODO_STATUSES,
        "no_rows": row_count == 0,
    }
    total = _total(document, document["type_code"])
    if total is not None:
        row["detected_qty"] = total
    return row


def _row_rank(row):
    if row["nonconforming_count"]:
        return 0
    if row["no_rows"]:
        return 1
    return 2 if row["todo"] else 3


def ccp_dashboard(actor_id=None, base_date=None):
    """F11: CCP 현황(REQ-CCP). actor_id는 API가 확인만 한다(결과에 쓰지 않음)."""
    with step("REQ-CCP-02", "REQ", "기준일 확인"):
        today = periodic._today()
        if base_date in (None, ""):
            base = today
        else:
            base = periodic._parse_day(base_date)
            if base is None:
                raise _bad("date", "YYYY-MM-DD 형식입니다.")
            if base > today:
                raise _bad("date", "오늘 이후 날짜는 볼 수 없습니다.")
    with step("REQ-CCP-03", "REQ", "CCP 양식 목록") as s:
        codes = ccp_types()
        s.note(", ".join(codes))
    with step("REQ-CCP-04", "REQ", "작업일 측정 요약(DOC N8)"):
        found = doc.measurement_summary(base.isoformat(), codes)
    with step("REQ-CCP-05", "REQ", "카드·줄 정렬·이탈 줄"):
        by_type = {code: [] for code in codes}
        for document in found["documents"]:
            by_type.setdefault(document["type_code"], []).append(document)
        cards, deviations = [], []
        for code in codes:
            documents = by_type[code]
            rows = [_batch_row(d) for d in documents]
            rows.sort(key=lambda r: r["label"] or "")
            rows.sort(key=_row_rank)
            cards.append(
                {
                    "type_code": code,
                    "template_name": found["templates"].get(code)
                    or (documents[0]["template_name"] if documents else code),
                    "counts": {
                        "batches": len(rows),
                        "todo": sum(1 for r in rows if r["todo"]),
                        "no_rows": sum(1 for r in rows if r["no_rows"]),
                        "deviation_rows": sum(r["nonconforming_count"] for r in rows),
                    },
                    "rows": rows,
                }
            )
            for d in documents:
                for bad in d["nonconforming"]:
                    items = [x for x in d["deviations"] if x["section_id"] == bad["section_id"]]
                    deviations.append(
                        {
                            "document_id": d["document_id"],
                            "type_code": code,
                            "label": d["label"],
                            "section_def": bad["section_def"],
                            "section_id": bad["section_id"],
                            "row_no": bad["row_no"],
                            "at": bad["at"],
                            "phase": bad["phase"],
                            "reasons": bad["reasons"],
                            "deviation": _deviation_state(items),
                            "doc_deviation_count": len(d["deviations"]),
                        }
                    )
        deviations.sort(
            key=lambda x: (x["at"] is None, x["at"] or "", x["document_id"], x["row_no"])
        )
        from django.utils import timezone

        return {
            "base_date": base.isoformat(),
            "cards": cards,
            "deviations": deviations,
            "generated_at": timezone.now().isoformat(),
        }
