"""CCP-3P v1 → v2 값 바꾸기 (P12 DP-03 — 캔디류 양식).

마이그레이션 0004가 문서 행(`doc_section`)과 결재 회차 스냅샷(`approval_request.snapshot_json`)에
같은 규칙을 쓴다. 기록된 값을 바꾸는 예외 작업(D-032·D-007 예외, DP-03 F1·F2·M3 a).

- M1 a: 시편 좌·중·우 3칸 → 1칸. 하나라도 X면 X, 셋 다 ○면 ○, 그 밖(빈칸 섞임)은 빈칸.
  Fe(fe_l·fe_c·fe_r) → fe_only, SUS(sus_l·sus_c·sus_r) → sts_only.
- M2 a: 행 비고(note)는 제품 통과 요약 첫 줄의 특이사항 끝에 "[행 비고] MM-DD HH:mm 내용"으로
  옮긴다(요약 줄이 없으면 한 줄 만듦). 특이사항은 v2에서 500자, 넘치면 자르고 "…".
- 판정(verdict)은 v2 규칙으로 다시 계산한다.
"""

from apps.documents import validation

V1_SPECIMENS = {"fe_only": ("fe_l", "fe_c", "fe_r"), "sts_only": ("sus_l", "sus_c", "sus_r")}
KEPT_KEYS = ("phase", "passed_at", "product_only", "product_fe", "product_sus")
NOTE_LIMIT = 500
NOTE_HEAD = "[행 비고]"


def combine(values):
    if "X" in values:
        return "X"
    if values and all(v == "○" for v in values):
        return "○"
    return None


def convert_check(values, checks_section):
    """v1 점검 행 값 → v2 값(판정 다시 계산). 비고는 따로 모은다(note_line)."""
    values = values or {}
    new = {key: values[key] for key in KEPT_KEYS if key in values}
    for key, sources in V1_SPECIMENS.items():
        merged = combine([values.get(k) for k in sources])
        if merged is not None:
            new[key] = merged
    return validation.with_computed(checks_section, new)


def note_line(values):
    note = ((values or {}).get("note") or "").strip()
    if not note:
        return None
    at = (values.get("passed_at") or "")[5:16].replace("T", " ")  # "MM-DD HH:mm"
    return f"{at} {note}".strip()


def merge_note(existing, lines):
    if not lines:
        return existing
    moved = f"{NOTE_HEAD} " + " / ".join(lines)
    text = f"{existing.strip()} {moved}" if (existing or "").strip() else moved
    return text if len(text) <= NOTE_LIMIT else text[: NOTE_LIMIT - 1] + "…"


def _time_key(values):
    return (values or {}).get("passed_at") or ""


def convert(checks, summaries, item_name, checks_section):
    """checks·summaries = 행 순서대로의 값 목록. 반환 (새 checks, 새 summaries, 요약 줄 추가 여부).

    요약 줄이 없는데 옮길 비고가 있으면 summaries 끝에 한 줄을 더한다(품명 = 배치 품명).
    """
    lines = [x for x in (note_line(v) for v in sorted(checks, key=_time_key)) if x]
    new_checks = [convert_check(v, checks_section) for v in checks]
    new_summaries = [dict(v or {}) for v in summaries]
    added = False
    if lines:
        if not new_summaries:
            new_summaries.append({"item_name": item_name} if item_name else {})
            added = True
        first = new_summaries[0]
        first["note"] = merge_note(first.get("note"), lines)
    return new_checks, new_summaries, added


def checks_section_of(schema):
    return validation.sections_of(schema)["checks"]


def convert_snapshot(snapshot, template_summary, checks_section):
    """결재 스냅샷(DOC get_document 모양)을 v2로. 바뀐 스냅샷을 돌려준다(입력은 그대로)."""
    snapshot = dict(snapshot)
    sections = [dict(s) for s in snapshot.get("sections", [])]
    checks = [s for s in sections if s.get("section_def") == "checks"]
    summaries = [s for s in sections if s.get("section_def") == "summary"]
    info = next((s for s in sections if s.get("section_def") == "info"), {})
    new_checks, new_summaries, added = convert(
        [s.get("values") for s in checks],
        [s.get("values") for s in summaries],
        (info.get("values") or {}).get("item_name"),
        checks_section,
    )
    for row, values in zip(checks, new_checks, strict=True):
        row["values"] = values
    for row, values in zip(summaries, new_summaries, strict=False):
        row["values"] = values
    if added:
        sections.append(
            {
                "section_id": None,
                "section_def": "summary",
                "row_no": 1,
                "values": new_summaries[-1],
                "recorded_at": None,
                "recorded_by": None,
            }
        )
    snapshot["sections"] = sections
    snapshot["template"] = {**snapshot.get("template", {}), **template_summary}
    return snapshot
