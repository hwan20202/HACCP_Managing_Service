"""CCP 현황 REQ-F11 (dev-notes/dashboard/p11-s2-spec.md 2.1).

- 쓰기·트랜잭션 없음. 어떤 양식이 CCP인지는 REQ 상수(rules.CCP_PROCESSES·CCP_BY_ITEM)만 안다.
  DOC N8(measurement_summary)에 양식 목록을 넘겨 측정 요약·이탈 행·개선조치를 받는다.
- 결과는 사용자에 따라 달라지지 않는다(X-Staff-Id 선택 — B2).
- 계층(NFR-03): DOC 서비스만 부른다.
"""

from apps.core.trace import step
from apps.documents import services as doc

from . import errors, periodic, rules, sources

TODO_STATUSES = doc.TODO_STATUSES  # P10 REQ-F10 "작성 필요"와 같은 집합(S1a-Q4 a)
# 측정 섹션 밖에서 배치 줄에 합계로 보여 줄 값(B6): 양식 → (반복 섹션, 필드)
SUMMARY_TOTALS = {"CCP-3P": ("summary", "detected_qty")}
# P11 S5 r1 특이사항 칸(배치 영역 특이사항 표): 양식 → {반복 섹션: 필드}. 값이 있는 행만
NOTE_FIELDS = {
    "CCP-1P": {"rounds": "note"},
    "CCP-2B": {"rounds": "note"},
    "CCP-3P": {"summary": "note"},  # 3P v2(P12 DP-03 M2): 감도 행 비고 없음 — 제품 통과 특이사항만
}
# 이탈 줄·다른 개선조치 줄에 그대로 내려 주는 개선조치 내용(DOC N8 deviations)
ACTION_KEYS = ("version", "description", "action_result", "actor_id")


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
    out.update({k: rep.get(k) for k in ACTION_KEYS})  # P11 S5 r1: 대표 개선조치 내용
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


def document_summaries(work_date, document_ids):
    """P11 S5 r2(D-176): 문서마다 측정 요약 — 배치별 연결 문서(REQ-A02)의 CCP 줄에 붙인다.

    대시보드와 같은 DOC N8(measurement_summary)을 그 작업일로 한 번 읽고 그 문서들만 고른다.
    반환 {document_id: summary}. 이탈 행의 개선조치 상태는 _deviation_state와 같은 규칙.
    """
    wanted = set(document_ids)
    if not wanted or not work_date:
        return {}
    found = doc.measurement_summary(str(work_date), ccp_types())
    out = {}
    for d in found["documents"]:
        if d["document_id"] not in wanted:
            continue
        row = _batch_row(d)
        states = {"none": 0, "pending": 0, "no_checker": 0, "checked": 0}
        matched = set()
        for bad in d["nonconforming"]:
            items = [x for x in d["deviations"] if x["section_id"] == bad["section_id"]]
            matched.update(x["deviation_id"] for x in items)
            states[_deviation_state(items)["state"]] += 1
        for x in d["deviations"]:
            if x["deviation_id"] not in matched:
                state = _deviation_state([x])["state"]
                if state != "none":
                    states[state] += 1
        latest = row["latest"]
        out[d["document_id"]] = {
            "row_count": row["row_count"],
            "latest": {k: latest.get(k) for k in ("at", "phase", "verdict")} if latest else None,
            "nonconforming_count": row["nonconforming_count"],
            "deviation_count": row["deviation_count"],
            "no_action": states["none"],
            "pending": states["pending"],
            "no_checker": states["no_checker"],
            "checked": states["checked"],
        }
    return out


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
        found = doc.measurement_summary(
            base.isoformat(), codes, {c: NOTE_FIELDS[c] for c in codes if c in NOTE_FIELDS}
        )
    with step("REQ-CCP-05", "REQ", "카드·줄 정렬·이탈 줄"):
        by_type = {code: [] for code in codes}
        for document in found["documents"]:
            by_type.setdefault(document["type_code"], []).append(document)
        cards, deviations, others, notes = [], [], [], []
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
                matched = set()
                for bad in d["nonconforming"]:
                    items = [x for x in d["deviations"] if x["section_id"] == bad["section_id"]]
                    matched.update(x["deviation_id"] for x in items)
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
                # P11 S5 r1: 이탈 행에 걸리지 않은 개선조치(관련 행 없음·적합 행에 씀)
                for x in d["deviations"]:
                    if x["deviation_id"] in matched:
                        continue
                    others.append(
                        {
                            "document_id": d["document_id"],
                            "type_code": code,
                            "label": d["label"],
                            "section_id": x["section_id"],
                            "deviation": _deviation_state([x]),
                        }
                    )
                for n in d["notes"]:
                    head = {"document_id": d["document_id"], "type_code": code}
                    notes.append({**head, "label": d["label"], **n})
        deviations.sort(
            key=lambda x: (x["at"] is None, x["at"] or "", x["document_id"], x["row_no"])
        )
        others.sort(key=lambda x: (x["document_id"], x["deviation"]["deviation_id"]))
        # P11 S5 r1: 배치마다 적용 CCP 공정과 순서(품목 예외 → 공정 유형 기본, 규칙 상수 순서)
        made = {
            b["production_batch_id"]: b
            for b in sources.batches_by_ids(
                d["batch_id"] for d in found["documents"] if d.get("batch_id") is not None
            )
        }
        batches = {}
        for d in found["documents"]:
            if d["label"] in batches:
                continue
            b = made.get(d.get("batch_id"))
            order = (
                [rules.ccp_type(p) for p in rules.processes_for(b["item_id"], b["process_type"])]
                if b
                else []
            )
            batches[d["label"]] = {
                "label": d["label"],
                "batch_id": d.get("batch_id"),
                "item_id": b["item_id"] if b else None,
                "item_name": (b["item_name"] if b else None) or d["item_name"],
                "processes": order,
                "status": b["status"] if b else None,  # D-171 정렬: PLANNED·IN_PROGRESS·COMPLETED
                "started_at": b["started_at"] if b else None,
                "completed_at": b["completed_at"] if b else None,
                # D-172 생산 수량(기준 단위): 계획, 산출(생산 실적 LOT 합 — 없으면 0)
                "planned_qty": b["planned_qty"] if b else None,
                "output_qty": b["output_qty"] if b else None,
                "unit": b["unit"] if b else None,
            }
        with step("REQ-CCP-06", "REQ", "배치별 생산일지·공정 n/m(DOC N16·N14, P15)") as s:
            keyed = {
                rules.prod_log_key(b["batch_id"]): b
                for b in batches.values()
                if b["batch_id"] is not None
            }
            logs = doc.documents_by_record_keys(keyed)
            counts = doc.section_counts([v["document_id"] for v in logs.values()], "steps")
            for key, b in keyed.items():
                log = logs.get(key)
                b["production_log"] = (
                    None
                    if log is None
                    else {
                        "document_id": log["document_id"],
                        "status": log["status"],
                        "steps_total": counts[log["document_id"]]["total"],
                        "steps_done": counts[log["document_id"]]["done"],
                    }
                )
            for b in batches.values():
                b.setdefault("production_log", None)
            s.note(f"생산일지 {len(logs)}건")
        notes.sort(key=lambda x: (x["at"] is None, x["at"] or "", x["document_id"], x["row_no"]))
        from django.utils import timezone

        return {
            "base_date": base.isoformat(),
            "cards": cards,
            "deviations": deviations,
            "other_deviations": others,
            "batches": list(batches.values()),
            "notes": notes,
            "generated_at": timezone.now().isoformat(),
        }
