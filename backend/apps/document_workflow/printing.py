"""P12 출력(WF-F09·F10·A06) — 종이 한 장 데이터 조립 (p12-s2-spec 2·3·4·5장, p12-ccp-policy.md).

범위: CCP-1P·2B·3P 단건(`kind: single`) · D03 입고일 묶음(`kind: receiving`,
p12-d03-policy.md DP-10) · D10·D12 주 묶음(`kind: weekly`, p12-d10-policy.md DP-12 ·
p12-d12-policy.md DP-13) · D11 월 묶음(`kind: monthly`, p12-d11-policy.md DP-17) ·
P15 생산일지(`kind: prodlog`, p15-s7-print.md — 결재 칸 없음, 작성완료 고정 값).

- 쓰기 없음(출력 기록 없음 — D-104 Q5). DOC·APR 공개 함수만 부른다(WF-NFR-01).
- 값: 열린 정정이 있으면 유효 승인본 스냅샷(S2-Q1 a), 아니면 지금 문서 값. 개선조치는 늘 현재 값.
- 결재 칸: 칸 구성 = 역할 설정(양식 고정, DP-02), 찍는 사람 = 고른 회차에서 같은 역할의 칸.
  역할 없는 옛 회차만 첫 슬롯 → 첫 칸, 마지막 슬롯 → 마지막 칸(DP-01 Q1 a). 승인한 칸만 찍음.
"""

import datetime
from datetime import timedelta

from django.utils import timezone

from apps.approvals import services as apr
from apps.core.http import ApiError
from apps.core.trace import step
from apps.documents import errors as doc_errors
from apps.documents import services as doc
from apps.staff import roles
from apps.staff import services as staff_services

from . import print_forms

PRINTABLE = ("completed", "submitted", "approved", "correcting")
SHOWN_REQUEST = ("in_progress", "approved")  # 이 상태의 최신 회차만 칸을 찍는다


class NotPrintableType(ApiError):
    status, code, message = 400, "NOT_PRINTABLE_TYPE", "이 양식은 출력하지 않습니다."


class NotPrintableStatus(ApiError):
    status, code, message = 409, "NOT_PRINTABLE_STATUS", "작성완료 뒤 출력할 수 있습니다."


class InvalidPrintFilter(ApiError):
    status, code, message = 400, "INVALID_FILTER", "조회 조건을 확인하세요."


def sheet_for_document(document_id):
    """WF-F09: 문서 → 종이 종류(CCP = single, D03 = receiving). 출력 없는 양식은 400."""
    with step("WF-PRT-01", "WF", "양식 → 종이 종류") as s:
        type_code = doc.document_type(document_id)
        kind = print_forms.PRINT_SHEETS.get(type_code)
        if kind is None:
            s.fail(f"{type_code} 출력 없음")
            raise NotPrintableType()
        s.note(f"{type_code} → {kind}")
    return {"kind": kind, "type_code": type_code, "document_id": document_id}


def _boxes_of(type_code):
    """양식의 결재 칸 [(role, label)] — 역할 설정의 칸 구성(DP-02). 없으면 기본 2칸.

    칸 이름은 종이 이름이 있으면 그것(`print_forms.BOX_LABELS`, D03 "팀장" — DP-11 U2 a).
    """
    config = roles.load()
    form = None if config.error else config.forms.get(type_code)
    if form is None:
        boxes = list(print_forms.DEFAULT_BOXES)
    else:
        boxes = [(role, form.labels[role]) for role in form.slots]
    paper = print_forms.BOX_LABELS.get(type_code, {})
    return [(role, paper.get(role, label)) for role, label in boxes]


def _pick_slots(boxes, slots):
    """칸 i → 그 칸에 찍을 슬롯(없으면 None)."""
    if not slots:
        return [None] * len(boxes)
    if any(s["role"] for s in slots):  # P14 역할 칸
        return [next((s for s in slots if s["role"] == role), None) for role, _ in boxes]
    picked = [None] * len(boxes)  # 옛 직접 지정 회차: 첫·마지막(D-126 S1-Q1)
    picked[0] = slots[0]
    if len(boxes) > 1 and len(slots) > 1:
        picked[-1] = slots[-1]
    return picked


def fill_boxes(boxes, request):
    slots = (request or {}).get("slots") or []
    result = []
    for (role, label), slot in zip(boxes, _pick_slots(boxes, slots), strict=True):
        approved = slot is not None and slot["state"] == "approved"
        result.append(
            {
                "role": role,
                "label": label,
                "staff_id": slot["approver_id"] if approved else None,
                "date": ((slot["decided_at"] or "")[:10] or None) if approved else None,
            }
        )
    return result


def _ordered(rows, section):
    order = section.get("phase_order")
    if not order:
        return sorted(rows, key=lambda r: r["row_no"])
    field, time_field = order["field"], order["time_field"]

    def key(row):
        values = row["values"] or {}
        phase = values.get(field)
        rank = 0 if phase == order["first"] else 2 if phase == order["last"] else 1
        return (rank, values.get(time_field) or "", row["row_no"])

    return sorted(rows, key=key)


def _fields_of(section):
    keep = ("key", "label", "type", "unit", "display", "options", "option_labels", "readonly")
    keep += ("cadence", "group")  # 점검표(D10) 주기·관리 칸
    return [{k: f[k] for k in keep if k in f} for f in section["fields"]]


def _measured_until(sections, schema_sections, work_date):
    """측정 시각 중 가장 늦은 날(작업일과 같으면 None) — 2B "작성일자 ~"(T6 a)."""
    days = []
    for section in schema_sections:
        order = section.get("phase_order")
        if not order:
            continue
        for row in sections.get(section["key"], []):
            value = (row["values"] or {}).get(order["time_field"])
            if value:
                days.append(value[:10])
    last = max(days) if days else None
    return last if last and last != work_date else None


def _source(detail, slot_info):
    """값 출처·결재 회차(CCP 1장 5·9): 열린 정정이면 유효 승인본, 아니면 지금 값 + 진행·승인 회차.

    반환 (회차 또는 None, 섹션 행 목록, trace 설명).
    """
    if detail["open_correction"] and slot_info.get("approved"):
        request = slot_info["approved"]
        note = f"정정 중 → 승인본 {request['attempt']}회차"
        return request, request["snapshot"].get("sections", []), note
    latest = slot_info.get("latest")
    request = latest if latest and latest["status"] in SHOWN_REQUEST else None
    note = f"지금 값, 칸 = {request['attempt']}회차" if request else "지금 값, 칸 없음"
    return request, detail["sections"], note


def _rows_by_section(source):
    sections = {}
    for row in source:
        sections.setdefault(row["section_def"], []).append(
            {
                "row_no": row["row_no"],
                "values": row.get("values") or {},
                "recorded_by": row.get("recorded_by"),
            }
        )
    return sections


def _first_values(sections, key):
    return (sections.get(key) or [{"values": {}}])[0]["values"]


def _deviation_rows(detail):
    """개선조치는 늘 지금 값(D-125 Q5 a)."""
    return [
        {
            "deviation_id": d["deviation_id"],
            "description": d["description"],
            "action_result": d["action_result"],
            "actor_id": d["actor_id"],
            "checked_by": d["checked_by"],
            "checked_on": (d["checked_at"] or "")[:10] or None,
        }
        for d in detail["deviations"]
    ]


def _people(ids):
    names = staff_services.names_of(p for p in ids if p is not None)
    return {str(k): v for k, v in sorted(names.items())}


def _single_guide(detail):
    type_code = detail["template"]["type_code"]
    version = detail["template"]["version"]
    if type_code == "CCP-1P" and version >= 3:
        return print_forms.CCP_1P_8000_GUIDE
    if type_code == "CCP-2B" and version >= 3:
        return print_forms.CCP_2B_ELAPSED_GUIDE
    return print_forms.GUIDES.get(type_code, detail["guide"])


def _single(detail, slot_info):
    type_code = detail["template"]["type_code"]
    schema_sections = detail["schema_sections"]
    with step("WF-PRT-03", "WF", "값 출처·결재 회차") as s:
        request, source, note = _source(detail, slot_info)
        s.note(note)
    with step("WF-PRT-04", "WF", "칸 채우기·조립"):
        boxes = fill_boxes(_boxes_of(type_code), request)
        sections = _rows_by_section(source)
        by_key = {sec["key"]: sec for sec in schema_sections}
        sections = {k: _ordered(v, by_key[k]) if k in by_key else v for k, v in sections.items()}
        info = _first_values(sections, "info")
        batch = next((r for r in detail["refs"] if r.get("production_batch_id")), None)
        deviations = _deviation_rows(detail)
        people = {b["staff_id"] for b in boxes}
        people.add(info.get("inspector"))
        people.update(r["recorded_by"] for rows in sections.values() for r in rows)
        people.update(x for d in deviations for x in (d["actor_id"], d["checked_by"]))
        title, subtitle = print_forms.TITLES[type_code]
        return {
            "kind": "single",
            "type_code": type_code,
            "template": {
                "name": detail["template"]["name"],
                "version": detail["template"]["version"],
            },
            "title": title,
            "subtitle": subtitle,
            "guide": _single_guide(detail),
            "boxes": boxes,
            "key": {"document_id": detail["document_id"]},
            "printable_count": 1,
            "document": {
                "document_id": detail["document_id"],
                "status": detail["status"],
                "work_date": detail["work_date"],
                "measured_until": _measured_until(sections, schema_sections, detail["work_date"]),
                "batch_label": batch["label"] if batch else None,
                "info": info,
                "sections": sections,
                "fields": {sec["key"]: _fields_of(sec) for sec in schema_sections},
                "section_labels": {sec["key"]: sec["label"] for sec in schema_sections},
                "deviations": deviations,
            },
            "people": _people(people),
        }


# ---------------------------------------------------------------- D03 입고일 묶음(receiving)
# p12-d03-policy.md(DP-10): 그날 D03 문서 1건 = 1줄(LOT 번호 순), 결재 칸 줄마다(역할 칸),
# 출력 불가 줄은 LOT 정보만, 문서 없는 LOT은 줄 없음, 점검자는 출력하지 않음.

D03 = "D03"
D03_INSPECTION = "inspection"  # D03 v2 검사 섹션(REQ rules.D03_INSPECTION과 같음)
LOT_KEYS = (
    "lot_number",
    "received_date",
    "supplier_name",
    "material_kind",
    "item_name",
    "quantity",
    "expiration_date",
)


# ---------------------------------------------------------------- P15 생산일지(prodlog)
# p15-s7-print.md(D-255): 문서 1건 = A4 세로, 결재 칸 없음. 기본정보·원료는 작성완료 때 고정한
# 시스템 섹션(frozen_batch·frozen_materials — 출력 시점 연동이 아님), 점검·원료 입력·공정은 문서 값.
# WF는 PLG를 import하지 않는다 — 섹션 값만 읽는다.


def _product_name(product):
    """고정 값 `product` = "[유형] 이름" → 제목용 이름."""
    text = (product or "").strip()
    if text.startswith("[") and "]" in text:
        return text[text.index("]") + 1 :].strip() or text
    return text


def _prodlog(detail):
    with step("WF-PRT-08", "WF", "생산일지 조립(고정 값·점검·원료·공정)"):
        sections = _rows_by_section(detail["sections"])
        for rows in sections.values():
            rows.sort(key=lambda r: r["row_no"])
        batch = _first_values(sections, "frozen_batch")
        info = _first_values(sections, "info")
        inputs = {
            r["values"].get("bom_line_id"): r["values"] for r in sections.get("materials", [])
        }
        materials = []
        for row in sorted(
            (r["values"] for r in sections.get("frozen_materials", [])),
            key=lambda v: v.get("line_no") or 0,
        ):
            given = inputs.get(row.get("bom_line_id")) or {}
            materials.append({**row, "worker": given.get("worker"), "note": given.get("note")})
        steps = [
            {k: v for k, v in r["values"].items() if k != "done"} for r in sections.get("steps", [])
        ]
        people = {info.get("inspector")}
        people.update(m["worker"] for m in materials)
        people.update(st.get("worker") for st in steps)
        name = _product_name(batch.get("product"))
        return {
            "kind": "prodlog",
            "type_code": detail["template"]["type_code"],
            "template": {
                "name": detail["template"]["name"],
                "version": detail["template"]["version"],
            },
            "title": f"[ {name} ] 생산일지" if name else "생산일지",
            "boxes": [],
            "key": {"document_id": detail["document_id"]},
            "printable_count": 1,
            "prechecks": [list(x) for x in print_forms.PROD_LOG_PRECHECKS],
            "document": {
                "document_id": detail["document_id"],
                "status": detail["status"],
                "work_date": detail["work_date"],
                "batch": batch,
                "info": info,
                "materials": materials,
                "steps": steps,
                "ccp_line": [
                    st.get("name") for st in steps if st.get("kind") in print_forms.PROD_LOG_CCP
                ],
            },
            "people": _people(people),
        }


def _details_and_slots(ids):
    """N9는 100건씩 나눠 부름(B5, ISS-021) · A12는 한 번(SQL 2)."""
    details = {}
    for start in range(0, len(ids), doc.PRINT_BATCH):
        details.update(doc.documents_for_print(ids[start : start + doc.PRINT_BATCH]))
    return details, apr.print_slots(ids)


def _lot_of(info):
    return {key: info.get(key) for key in LOT_KEYS}


def _receiving(day):
    """WF-F10(receiving): 입고일 하루의 D03 종이. 문서 0건·모두 출력 불가면 printable_count 0."""
    with step("WF-PRT-05", "WF", "묶음 문서(DOC N7) — 입고일 D03") as s:
        rows = doc.requirement_documents(day, day)["rows"]
        ids = [r["document_id"] for r in rows if r["type_code"] == D03]
        s.note(f"{len(ids)}건")
    with step("WF-PRT-07", "WF", "묶음 문서·결재 칸 읽기") as s:
        if ids:
            details, slots = _details_and_slots(ids)
        else:
            details, slots = {}, {}
            s.skip("문서 없음")
    with step("WF-PRT-06", "WF", "줄 조립") as s:
        boxes = _boxes_of(D03)
        ordered = sorted(
            details.values(),
            key=lambda d: (
                str(_first_values(_rows_by_section(d["sections"]), "info").get("lot_number") or ""),
                d["document_id"],
            ),
        )
        lines, deviations, people, sample = [], [], set(), None
        for detail in ordered:
            line = {
                "document_id": detail["document_id"],
                "status": detail["status"],
                "work_date": detail["work_date"],
            }
            if detail["status"] in PRINTABLE:
                request, source, _ = _source(detail, slots.get(detail["document_id"], {}))
                sections = _rows_by_section(source)
                approval = fill_boxes(boxes, request)
                line |= {
                    "printable": True,
                    "state": "ok",
                    "lot": _lot_of(_first_values(sections, "info")),
                    "values": _first_values(sections, D03_INSPECTION),
                    "approval": approval,
                }
                people.update(b["staff_id"] for b in approval)
                for d in _deviation_rows(detail):
                    deviations.append(
                        {
                            **d,
                            "document_id": detail["document_id"],
                            "work_date": detail["work_date"],
                            "lot_number": line["lot"]["lot_number"],
                        }
                    )
                    people.update((d["actor_id"], d["checked_by"]))
                sample = sample or detail
            else:  # 작성중·반려(·작성 안 함): LOT 정보만(D-124 Q4)
                line |= {
                    "printable": False,
                    "state": detail["status"],
                    "lot": _lot_of(_first_values(_rows_by_section(detail["sections"]), "info")),
                    "values": None,
                    "approval": fill_boxes(boxes, None),
                }
                if detail["status"] == "skipped":
                    line["skip_reason"] = detail["skip_reason"]
            lines.append(line)
        sample = sample or (ordered[0] if ordered else None)
        inspection = next(
            (
                sec
                for sec in (sample["schema_sections"] if sample else [])
                if sec["key"] == D03_INSPECTION
            ),
            None,
        )
        printable = sum(line["printable"] for line in lines)
        s.note(f"줄 {len(lines)} · 출력 가능 {printable}")
        title, subtitle = print_forms.TITLES[D03]
        return {
            "kind": "receiving",
            "type_code": D03,
            "template": (
                {"name": sample["template"]["name"], "version": sample["template"]["version"]}
                if sample
                else None
            ),
            "title": title,
            "subtitle": subtitle,
            "guide": print_forms.GUIDES.get(D03, sample["guide"] if sample else []),
            "boxes": [{"role": role, "label": label} for role, label in boxes],
            "box_group": print_forms.BOX_GROUPS.get(D03),
            "key": {"type": D03, "date": day},
            "printable_count": printable,
            "date": day,
            "fields": _fields_of(inspection) if inspection else [],
            "lines": lines,
            "deviations": deviations,
            "people": _people(people),
        }


# ---------------------------------------------------------------- D10 주 묶음(weekly)
# p12-d10-policy.md(DP-12): 월~금 + 출력 가능한 주말 문서가 있는 토·일 칸(W3 a),
# 점검자 = 가장 늦은 요일 문서의 점검자,
# 결재 칸 = 칸마다 그 주에서 그 역할로 가장 최근에 승인한 사람, 출력 불가·없음·오늘 뒤 칸은 값 없음.
# D12(p12-d12-policy.md DP-13): 요일 칸마다 그날 회차의 결재 칸(`approval`)과
# 공정명(`process_name`), 점검자는 출력하지 않음(종이에 칸 없음).
DAY_APPROVAL_TYPES = ("D12",)  # 요일마다 기록확인 칸이 있는 종이
NO_INSPECTOR_TYPES = ("D12",)

WEEKDAYS = "월화수목금토일"
WEEK_CHECKS = "checks"  # D10 점검 섹션


def _monday(day):
    return day - timedelta(days=day.weekday())


def _latest_box_people(boxes, picked_by_day):
    """칸마다 그 역할로 가장 최근에 승인한 사람(승인 시각 기준, 같으면 늦은 요일).

    picked_by_day = 요일 순 [[슬롯|None] × 칸].
    """
    result = []
    for i, (role, label) in enumerate(boxes):
        best = None
        for picked in picked_by_day:
            slot = picked[i]
            if slot is None or slot["state"] != "approved" or not slot["decided_at"]:
                continue
            if best is None or slot["decided_at"] >= best["decided_at"]:
                best = slot
        result.append(
            {
                "role": role,
                "label": label,
                "staff_id": best["approver_id"] if best else None,
                "date": (best["decided_at"][:10] or None) if best else None,
            }
        )
    return result


def _weekly(type_code, day):
    """WF-F10(weekly): 그 주(월~일) 문서. 칸 = 월~금 + 문서 있는 토·일."""
    monday = _monday(day)
    sunday = monday + timedelta(days=6)
    with step("WF-PRT-05", "WF", f"묶음 문서(DOC N7) — {type_code} 주") as s:
        rows = doc.requirement_documents(monday.isoformat(), sunday.isoformat(), [type_code])
        by_day = {}
        for row in sorted(rows["rows"], key=lambda r: r["document_id"]):
            if row["type_code"] == type_code:
                by_day.setdefault(row["work_date"], row["document_id"])  # 하루 1건(record_key)
        ids = sorted(by_day.values())
        s.note(f"{monday} 주 {len(ids)}건")
    with step("WF-PRT-07", "WF", "묶음 문서·결재 칸 읽기") as s:
        if ids:
            details, slots = _details_and_slots(ids)
        else:
            details, slots = {}, {}
            s.skip("문서 없음")
    with step("WF-PRT-06", "WF", "요일 칸 조립") as s:
        boxes = _boxes_of(type_code)
        today = timezone.localdate()
        dates = [monday + timedelta(days=n) for n in range(5)]
        for weekend in (monday + timedelta(days=5), sunday):  # 출력 가능한 주말 문서만(W3 a)
            detail = details.get(by_day.get(weekend.isoformat()))
            if detail and detail["status"] in PRINTABLE:
                dates.append(weekend)
        days, deviations, picked_by_day, people = [], [], [], set()
        inspector, sample, latest_dates = None, None, {}
        for date in dates:
            iso = date.isoformat()
            document_id = by_day.get(iso)
            detail = details.get(document_id) if document_id else None
            cell = {"date": iso, "weekday": WEEKDAYS[date.weekday()], "document_id": document_id}
            if detail is None:
                cell |= {"printable": False, "state": "future" if date > today else "missing"}
                cell["values"] = None
            elif detail["status"] in PRINTABLE:
                request, source, _ = _source(detail, slots.get(document_id, {}))
                sections = _rows_by_section(source)
                values = _first_values(sections, WEEK_CHECKS)
                info = _first_values(sections, "info")
                cell |= {"printable": True, "state": "ok", "status": detail["status"]}
                cell["values"] = values
                inspector = info.get("inspector") or inspector  # 날짜 순 → 마지막 요일이 남음
                picked_by_day.append(_pick_slots(boxes, (request or {}).get("slots") or []))
                if type_code in DAY_APPROVAL_TYPES:
                    cell["approval"] = fill_boxes(boxes, request)
                    cell["process_name"] = info.get("process_name")
                    people.update(b["staff_id"] for b in cell["approval"])
                for d in _deviation_rows(detail):
                    deviations.append({**d, "document_id": document_id, "work_date": iso})
                    people.update((d["actor_id"], d["checked_by"]))
                sample = detail
            else:  # 작성중·반려·작성 안 함 — 값 없음(Q4 보류: 화면은 빈칸, ISP-02)
                cell |= {"printable": False, "state": detail["status"], "status": detail["status"]}
                cell["values"] = None
                if detail["status"] == "skipped":
                    cell["skip_reason"] = detail["skip_reason"]
                sample = sample or detail
            days.append(cell)
        section = next(
            (x for x in (sample["schema_sections"] if sample else []) if x["key"] == WEEK_CHECKS),
            None,
        )
        fields = _fields_of(section) if section else []
        for field in fields:  # 연간 날짜(Q5 a): 그 주 값 중 가장 늦은 날짜
            if field["type"] == "date":
                found = [c["values"].get(field["key"]) for c in days if c["printable"]]
                found = [v for v in found if v]
                latest_dates[field["key"]] = max(found) if found else None
        header = _latest_box_people(boxes, picked_by_day)
        people.update(b["staff_id"] for b in header)
        if type_code in NO_INSPECTOR_TYPES:
            inspector = None
        people.add(inspector)
        printable = sum(c["printable"] for c in days)
        s.note(f"칸 {len(days)} · 출력 가능 {printable}")
        title, subtitle = print_forms.TITLES[type_code]
        return {
            "kind": "weekly",
            "type_code": type_code,
            "template": (
                {"name": sample["template"]["name"], "version": sample["template"]["version"]}
                if sample
                else None
            ),
            "title": title,
            "subtitle": subtitle,
            "guide": print_forms.GUIDES.get(type_code, sample["guide"] if sample else []),
            "boxes": header,
            "key": {"type": type_code, "date": monday.isoformat()},
            "printable_count": printable,
            "week_start": monday.isoformat(),
            "period": {"from": days[0]["date"], "to": days[-1]["date"]},
            "inspector_id": inspector,
            "fields": fields,
            "days": days,
            "latest_dates": latest_dates,
            "deviations": deviations,
            "people": _people(people),
        }


# ---------------------------------------------------------------- D11 월 묶음(monthly)
# p12-d11-policy.md(DP-17): 그 달에 월요일(work_date)이 있는 주 문서(D-125 Q7) — 월요일 수만큼 4~5칸
# (4개인 달은 5주 칸 없음, Q5 c). 결재 칸 = D10과 같은 "칸마다 가장 최근 승인자", 점검자 없음,
# 주 칸 날짜 = 점검일(checked_on), 특이사항(remark)은 출력 가능 주만.


def _mondays(year, month):
    day = datetime.date(year, month, 1)
    day += timedelta(days=(7 - day.weekday()) % 7)
    result = []
    while day.month == month:
        result.append(day)
        day += timedelta(days=7)
    return result


def _monthly(type_code, year, month):
    """WF-F10(monthly): 그 달 주 문서(주 1건, work_date = 월요일)."""
    mondays = _mondays(year, month)
    with step("WF-PRT-05", "WF", f"묶음 문서(DOC N7) — {type_code} {year}-{month:02d}") as s:
        rows = doc.requirement_documents(
            mondays[0].isoformat(), mondays[-1].isoformat(), [type_code]
        )
        by_week = {}
        for row in sorted(rows["rows"], key=lambda r: r["document_id"]):
            if row["type_code"] == type_code:
                by_week.setdefault(row["work_date"], row["document_id"])  # 주 1건(record_key)
        ids = sorted(by_week.values())
        s.note(f"주 {len(mondays)} · 문서 {len(ids)}건")
    with step("WF-PRT-07", "WF", "묶음 문서·결재 칸 읽기") as s:
        if ids:
            details, slots = _details_and_slots(ids)
        else:
            details, slots = {}, {}
            s.skip("문서 없음")
    with step("WF-PRT-06", "WF", "주 칸 조립") as s:
        boxes = _boxes_of(type_code)
        today = timezone.localdate()
        weeks, picked_by_week, people, sample = [], [], set(), None
        for n, monday in enumerate(mondays, start=1):
            iso = monday.isoformat()
            document_id = by_week.get(iso)
            detail = details.get(document_id) if document_id else None
            cell = {"week_no": n, "week_start": iso, "document_id": document_id}
            if detail is None:
                cell |= {"printable": False, "state": "future" if monday > today else "missing"}
                cell["values"] = None
            elif detail["status"] in PRINTABLE:
                request, source, _ = _source(detail, slots.get(document_id, {}))
                sections = _rows_by_section(source)
                info = _first_values(sections, "info")
                cell |= {"printable": True, "state": "ok", "status": detail["status"]}
                cell["values"] = _first_values(sections, WEEK_CHECKS)
                cell["checked_on"] = info.get("checked_on")
                cell["remark"] = info.get("remark") or None
                picked_by_week.append(_pick_slots(boxes, (request or {}).get("slots") or []))
                sample = detail
            else:
                cell |= {"printable": False, "state": detail["status"], "status": detail["status"]}
                cell["values"] = None
                if detail["status"] == "skipped":
                    cell["skip_reason"] = detail["skip_reason"]
                sample = sample or detail
            weeks.append(cell)
        section = next(
            (x for x in (sample["schema_sections"] if sample else []) if x["key"] == WEEK_CHECKS),
            None,
        )
        header = _latest_box_people(boxes, picked_by_week)
        people.update(b["staff_id"] for b in header)
        printable = sum(w["printable"] for w in weeks)
        s.note(f"주 {len(weeks)} · 출력 가능 {printable}")
        title, subtitle = print_forms.TITLES[type_code]
        return {
            "kind": "monthly",
            "type_code": type_code,
            "template": (
                {"name": sample["template"]["name"], "version": sample["template"]["version"]}
                if sample
                else None
            ),
            "title": title,
            "subtitle": subtitle,
            "guide": print_forms.GUIDES.get(type_code, sample["guide"] if sample else []),
            "boxes": header,
            "key": {"type": type_code, "month": f"{year}-{month:02d}"},
            "printable_count": printable,
            "month": f"{year}-{month:02d}",
            "fields": _fields_of(section) if section else [],
            "weeks": weeks,
            "remarks": [
                {"week_no": w["week_no"], "checked_on": w["checked_on"], "remark": w["remark"]}
                for w in weeks
                if w["printable"] and w["remark"]
            ],
            "people": _people(people),
        }


# ---------------------------------------------------------------- 진입(F09 → F10)


def print_sheet(document_id, kind=None):
    """WF-F10(문서로 열기): 문서 → 그 문서가 들어가는 종이. 404·400·409 NOT_PRINTABLE_STATUS.

    CCP = 그 문서 한 장(single), D03 = 그 문서의 입고일 장(receiving), D10 = 그 문서의 주(weekly —
    주말 문서도 그 주 종이, DP-12 W2 a).
    """
    sheet = sheet_for_document(document_id)
    if kind is not None and kind != sheet["kind"]:
        raise InvalidPrintFilter(
            details=[
                {"path": "kind", "code": "invalid", "message": f"이 문서는 {sheet['kind']}입니다."}
            ]
        )
    with step("WF-PRT-02", "WF", "문서·결재 칸 읽기") as s:
        detail = doc.documents_for_print([document_id]).get(document_id)
        if detail is None:  # 사이에 삭제됨
            raise doc_errors.DocumentNotFound()
        if detail["status"] not in PRINTABLE:
            s.fail(detail["status"])
            raise NotPrintableStatus()
        if sheet["kind"] == "prodlog" and detail["status"] != "completed":
            s.fail(detail["status"])  # 결재 없는 문서 — 작성완료만(D-255 Q2)
            raise NotPrintableStatus()
        if sheet["kind"] != "single":
            s.note(f"{sheet['kind']} {detail['work_date']}")
            slot_info = None
        else:
            slot_info = apr.print_slots([document_id]).get(document_id, {})
    if sheet["kind"] == "prodlog":
        return _prodlog(detail)
    if sheet["kind"] == "receiving":
        return _receiving(detail["work_date"])
    if sheet["kind"] == "weekly":
        return _weekly(sheet["type_code"], datetime.date.fromisoformat(detail["work_date"]))
    if sheet["kind"] == "monthly":
        day = datetime.date.fromisoformat(detail["work_date"])
        return _monthly(sheet["type_code"], day.year, day.month)
    return _single(detail, slot_info)


def print_by_query(query):
    """WF-A06 본체: parse_query 결과 → 종이 데이터."""
    if "document_id" in query:
        return print_sheet(query["document_id"], query.get("kind"))
    if query["kind"] == "weekly":
        return _weekly(query["type"], datetime.date.fromisoformat(query["date"]))
    if query["kind"] == "monthly":
        year, month = (int(x) for x in query["month"].split("-"))
        return _monthly(query["type"], year, month)
    return _receiving(query["date"])


BUILT_KINDS = ("single", "receiving", "weekly", "monthly")  # weekend 종이 없음(DP-12 W2)
QUERY_KEYS = {"document_id", "kind", "type", "date", "month"}


def _problem(path, message, code="invalid"):
    return {"path": path, "code": code, "message": message}


def parse_query(params):
    """A06 쿼리. 문서로 열기 `document_id`(+ kind=single) 또는 묶음 `kind`·`type`·`date`.

    순서(B3): 키·형식 400 → `type`이 출력 양식이 아니면 400 NOT_PRINTABLE_TYPE → kind 조합·날짜 400.
    """
    problems = [
        _problem(key, "알 수 없는 조건입니다.", "unknown_key")
        for key in sorted(set(params) - QUERY_KEYS)
    ]
    kind = params.get("kind")
    raw = params.get("document_id")
    if raw is not None:
        problems += [
            _problem(key, "문서 번호로 열 때는 쓰지 않습니다.")
            for key in ("type", "date", "month")
            if key in params
        ]
        if kind not in (None, "single"):
            problems.append(_problem("kind", "문서 번호로 열 때는 single만(묶음은 문서가 정함)."))
        if not str(raw).isdigit():
            problems.append(_problem("document_id", "문서 번호(정수)."))
        if problems:
            raise InvalidPrintFilter(details=problems)
        return {"document_id": int(raw), "kind": kind}
    type_code = params.get("type")
    if not type_code:
        problems.append(_problem("type", "양식(type)이 필요합니다.", "required"))
    if not kind:
        problems.append(_problem("kind", "종이 종류(kind)가 필요합니다.", "required"))
    if problems:
        raise InvalidPrintFilter(details=problems)
    expected = print_forms.PRINT_SHEETS.get(type_code)
    if expected is None:
        raise NotPrintableType()
    if expected == "single" or kind != expected:
        raise InvalidPrintFilter(details=[_problem("kind", f"{type_code}는 {expected}입니다.")])
    if kind not in BUILT_KINDS:
        raise InvalidPrintFilter(details=[_problem("kind", "아직 만들지 않은 종이입니다.")])
    if kind == "monthly":  # month=YYYY-MM(date 아님)
        raw_month = params.get("month") or ""
        if "date" in params:
            raise InvalidPrintFilter(details=[_problem("date", "월 종이는 month로 엽니다.")])
        try:
            first = datetime.date.fromisoformat(f"{raw_month}-01") if len(raw_month) == 7 else None
        except ValueError:
            first = None
        if first is None:
            raise InvalidPrintFilter(details=[_problem("month", "YYYY-MM 형식입니다.")])
        if first > timezone.localdate():
            raise InvalidPrintFilter(details=[_problem("month", "미래 달은 출력하지 않습니다.")])
        return {"kind": kind, "type": type_code, "month": raw_month}
    if "month" in params:
        raise InvalidPrintFilter(details=[_problem("month", "월 종이(monthly)에만 씁니다.")])
    day = params.get("date") or ""
    try:
        parsed = datetime.date.fromisoformat(day) if len(day) == 10 else None
    except ValueError:
        parsed = None
    if parsed is None:
        raise InvalidPrintFilter(details=[_problem("date", "YYYY-MM-DD 형식입니다.")])
    if parsed > timezone.localdate():
        raise InvalidPrintFilter(details=[_problem("date", "미래 날짜는 출력하지 않습니다.")])
    return {"kind": kind, "type": type_code, "date": day}
