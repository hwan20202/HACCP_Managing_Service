"""작성 필요 목록 REQ-F10 (dev-notes/document-workflow/p10-s2-spec.md 2장).

- 쓰기·트랜잭션 없음. DOC N7(requirement_documents) 한 번 + 규칙 파일 읽기.
- 구분(오늘·주간·월간·연간·수시) 판단은 REQ만 안다: 규칙 파일 cadence가 우선, 파일이 깨졌으면
  기본 구분 상수(S2-Q1 a), 사건 양식(입고·생산) → 오늘, 그 밖 작성 요구 문서 → 수시.
- 문서 없음 줄은 P9 3장과 같은 날짜 규칙(periodic.plan_lines)으로 계산한다. 미래는 계산하지 않는다.
- 계층(NFR-03): DOC 서비스와 staff 서비스만 부른다.
"""

import datetime

from apps.core.trace import step
from apps.documents import services as doc

from . import errors, periodic

PAST_DAYS = 30  # 지난 미완료: 기준일 −30일 ~ −1일(주간은 월요일이 −30일 이후인 주)
GROUPS = (
    ("today", "오늘"),
    ("week", "주간"),
    ("month", "월간"),
    ("year", "연간"),
    ("adhoc", "수시"),
)
CADENCE_GROUP = {"daily": "today", "weekly": "week"}
PERIODIC_DEFAULT = {"D10": "today", "D12": "today", "D11": "week"}  # 규칙 파일이 깨졌을 때
EVENT_TYPES = {"D01", "D02", "D03", "CCP-1P", "CCP-2B", "CCP-3P"}  # 입고·생산 사건 → 오늘
TODO_STATUSES = doc.TODO_STATUSES
BUNDLE_PRIORITY = ("rejected", "correcting", "draft")  # D03 묶음 상태: 앞선 것
REQUIREMENT_ORDER = {"periodic": 0, "lot": 1, "batch": 2}  # 같은 날: 주기 → 입고 → 생산


def _bad(path, message):
    return errors.InvalidFilter(details=[{"path": path, "code": "invalid", "message": message}])


def _check_input(base_date, mine):
    today = periodic._today()
    if base_date in (None, ""):
        base = today
    else:
        base = periodic._parse_day(base_date)
        if base is None:
            raise _bad("date", "YYYY-MM-DD 형식입니다.")
        if base > today:
            raise _bad("date", "오늘 이후 날짜는 볼 수 없습니다.")
    if mine in (None, "", "0", 0, False):
        mine = False
    elif mine in ("1", 1, True):
        mine = True
    else:
        raise _bad("mine", "0 또는 1입니다.")
    return base, mine


def _row(source, **extra):
    row = {
        "kind": "document",
        "work_date": source["work_date"],
        "type_code": source["type_code"],
        "template_name": source["template_name"],
        "requirement": source["requirement"],
        "target_summary": source["target_summary"],
        "status": source["status"],
        "document_id": source["document_id"],
        "version": source["version"],
        "assignee_id": source["assignee_id"],
        "inspector_id": source["inspector_id"],
        "created_by": source["created_by"],
        "updated_at": source["updated_at"],
        "tags": source["tags"],
    }
    row.update(extra)
    return row


def _sort(rows):
    rows.sort(key=lambda r: (r["type_code"],))
    rows.sort(key=lambda r: REQUIREMENT_ORDER.get(r["requirement"], 3))
    rows.sort(key=lambda r: r["work_date"], reverse=True)
    return rows


def _bundle_d03(rows):
    """같은 입고일의 D03 작성 필요 줄을 1줄로(mine 거르기 뒤 — B2)."""
    out, bundles = [], {}
    for row in rows:
        if row["type_code"] != "D03":
            out.append(row)
            continue
        day = row.pop("received_date", None) or row["work_date"]
        group = bundles.get(day)
        if group is None:
            group = bundles[day] = dict(row, bundle={"received_date": day, "count": 0})
            out.append(group)
        group["bundle"]["count"] += 1
        rank = BUNDLE_PRIORITY.index
        if rank(row["status"]) < rank(group["status"]):
            group["status"] = row["status"]
        if row["document_id"] < group["document_id"]:
            group["document_id"], group["version"] = row["document_id"], row["version"]
    return out


def _period(work_date, group, base, monday):
    """'current' · 'past' · None(30일 넘음 — older로)."""
    day = datetime.date.fromisoformat(work_date)
    oldest = base - datetime.timedelta(days=PAST_DAYS)
    if group == "week":
        if day == monday:
            return "current"
        return "past" if oldest <= day < monday else None
    if day == base:
        return "current"
    return "past" if oldest <= day < base else None


def todo_list(actor_id, base_date=None, mine=False):
    """F10: 작성 필요 목록(REQ-TDO). actor_id는 API가 확인한 현재 사용자."""
    with step("REQ-TDO-02", "REQ", "날짜·mine 확인"):
        base, mine = _check_input(base_date, mine)
    monday = periodic._monday(base)
    oldest = base - datetime.timedelta(days=PAST_DAYS)
    warnings = []
    with step("REQ-TDO-03", "REQ", "규칙 파일 읽기(오류면 문서 없음 계산만 뺌)") as s:
        try:
            rules = periodic.load_rules()
        except errors.RulesInvalid:
            rules = None
            warnings.append("RULES_INVALID")
            s.fail("RULES_INVALID")
    cadence = dict(PERIODIC_DEFAULT)
    if rules is not None:
        cadence.update({r["type_code"]: CADENCE_GROUP[r["cadence"]] for r in rules})
    with step("REQ-TDO-04", "REQ", "기간의 작성 요구 문서(DOC N7)"):
        found = doc.requirement_documents(
            periodic._monday(oldest), base, type_codes=sorted(cadence), count_older=True
        )
    with step("REQ-TDO-05", "REQ", "구분·상태 거르기·문서 없음·D03 묶음·mine") as s:
        buckets = {key: {"current": [], "past": []} for key, _ in GROUPS}
        awaiting, older, keys = [], found["older_count"], set()
        for source in found["rows"]:
            keys.add(source["record_key"])
            code = source["type_code"]
            group = cadence.get(code) or ("today" if code in EVENT_TYPES else "adhoc")
            status = source["status"]
            if status == "completed":
                if oldest.isoformat() <= source["work_date"] <= base.isoformat():
                    if not mine or actor_id in (source["assignee_id"], source["inspector_id"]):
                        awaiting.append(_row(source))
                continue
            if status not in TODO_STATUSES:
                continue
            when = _period(source["work_date"], group, base, monday)
            if when is None:
                older += 1  # 기간 앞쪽(그 주 월요일부터 −30일 전까지)
                continue
            if mine and actor_id not in (source["assignee_id"], source["inspector_id"]):
                continue
            extra = {"received_date": source["received_date"]} if code == "D03" else {}
            if group == "week":
                extra["week_start"] = source["work_date"]
            buckets[group][when].append(_row(source, **extra))
        missing = 0
        if rules is not None and not mine:
            for line in periodic.plan_lines(rules, oldest, base):
                if line["reason"] is not None or line["record_key"] in keys:
                    continue
                group = CADENCE_GROUP["weekly" if "|week:" in line["record_key"] else "daily"]
                work = line["work_date"]
                if group == "week" and work < oldest:
                    continue  # 주간 지난 미완료는 월요일이 −30일 이후인 주만
                template = found["templates"].get(line["type_code"]) or {}
                when = "current" if work in (base, monday) else "past"
                if group == "today" and work != base:
                    when = "past"
                row = {
                    "kind": "missing",
                    "work_date": work.isoformat(),
                    "type_code": line["type_code"],
                    "template_name": template.get("name"),
                    "requirement": "periodic",
                    "target_summary": None,
                    "record_key": line["record_key"],
                    "tags": doc.tags_for(template.get("tag_rules", []), work),
                }
                if group == "week":
                    row["week_start"] = work.isoformat()
                buckets[group][when].append(row)
                missing += 1
        s.note(f"문서 없음 {missing}, 30일 넘음 {older}")
    with step("REQ-TDO-06", "REQ", "조립"):
        groups, counts = [], {}
        week_past_from = periodic._monday(oldest)
        if week_past_from < oldest:
            week_past_from += datetime.timedelta(days=7)
        ranges = {
            "today": (oldest, base - datetime.timedelta(days=1)),
            "week": (week_past_from, monday - datetime.timedelta(days=7)),
        }
        for key, label in GROUPS:
            current = _sort(_bundle_d03(buckets[key]["current"]))
            past = _sort(_bundle_d03(buckets[key]["past"]))
            has_forms = key in ("today", "week") or bool(current or past)
            count = len(current) + len(past)
            counts[key] = count
            span = ranges.get(key)
            groups.append(
                {
                    "key": key,
                    "label": label,
                    "has_forms": has_forms,
                    "count": count,
                    "rows": current,
                    "past": {
                        "count": len(past),
                        "from": span[0].isoformat() if span else None,
                        "to": span[1].isoformat() if span else None,
                        "rows": past,
                    },
                }
            )
        awaiting = _sort(awaiting)
        return {
            "base_date": base.isoformat(),
            "mine": mine,
            "groups": groups,
            "counts": counts,
            "awaiting_submit": {"count": len(awaiting), "rows": awaiting},
            "older": {"count": older, "before": oldest.isoformat()},
            "warnings": warnings,
        }
