"""P12 출력(WF-F09·F10·A06) — 종이 한 장 데이터 조립 (p12-s2-spec 2·3·4·5장, p12-ccp-policy.md).

이번 범위: CCP-1P·2B·3P 단건(`kind: single`). 묶음(D03·D10·D12·D11)은 다음 단계.

- 쓰기 없음(출력 기록 없음 — D-104 Q5). DOC·APR 공개 함수만 부른다(WF-NFR-01).
- 값: 열린 정정이 있으면 유효 승인본 스냅샷(S2-Q1 a), 아니면 지금 문서 값. 개선조치는 늘 현재 값.
- 결재 칸: 칸 구성 = 역할 설정(양식 고정, DP-02), 찍는 사람 = 고른 회차에서 같은 역할의 칸.
  역할 없는 옛 회차만 첫 슬롯 → 첫 칸, 마지막 슬롯 → 마지막 칸(DP-01 Q1 a). 승인한 칸만 찍음.
"""

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
    """WF-F09: 문서 → 종이 한 장의 열쇠. 지금은 CCP 단건만."""
    with step("WF-PRT-01", "WF", "양식 → 종이 종류") as s:
        type_code = doc.document_type(document_id)
        kind = print_forms.PRINT_SHEETS.get(type_code)
        if kind is None:
            s.fail(f"{type_code} 출력 없음")
            raise NotPrintableType()
        s.note(f"{type_code} → {kind}")
    return {"kind": kind, "type_code": type_code, "document_id": document_id}


def _boxes_of(type_code):
    """양식의 결재 칸 [(role, label)] — 역할 설정의 칸 구성(DP-02). 없으면 기본 2칸."""
    config = roles.load()
    form = None if config.error else config.forms.get(type_code)
    if form is None:
        return list(print_forms.DEFAULT_BOXES)
    return [(role, form.labels[role]) for role in form.slots]


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
    keep = ("key", "label", "type", "unit", "display", "options", "readonly")
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


def _single(detail, slot_info):
    type_code = detail["template"]["type_code"]
    schema_sections = detail["schema_sections"]
    with step("WF-PRT-03", "WF", "값 출처·결재 회차") as s:
        if detail["open_correction"] and slot_info.get("approved"):
            request = slot_info["approved"]
            source = request["snapshot"].get("sections", [])
            s.note(f"정정 중 → 승인본 {request['attempt']}회차")
        else:
            latest = slot_info.get("latest")
            request = latest if latest and latest["status"] in SHOWN_REQUEST else None
            source = detail["sections"]
            s.note(f"지금 값, 칸 = {request['attempt']}회차" if request else "지금 값, 칸 없음")
    with step("WF-PRT-04", "WF", "칸 채우기·조립"):
        boxes = fill_boxes(_boxes_of(type_code), request)
        sections = {}
        for row in source:
            sections.setdefault(row["section_def"], []).append(
                {
                    "row_no": row["row_no"],
                    "values": row.get("values") or {},
                    "recorded_by": row.get("recorded_by"),
                }
            )
        by_key = {sec["key"]: sec for sec in schema_sections}
        sections = {k: _ordered(v, by_key[k]) if k in by_key else v for k, v in sections.items()}
        info = (sections.get("info") or [{"values": {}}])[0]["values"]
        batch = next((r for r in detail["refs"] if r.get("production_batch_id")), None)
        deviations = [
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
            "guide": print_forms.GUIDES.get(type_code, detail["guide"]),
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
            "people": {
                str(k): v
                for k, v in sorted(
                    staff_services.names_of(p for p in people if p is not None).items()
                )
            },
        }


def print_sheet(document_id):
    """WF-F10(single): 문서 → 종이 데이터. 404·400 NOT_PRINTABLE_TYPE·409 NOT_PRINTABLE_STATUS."""
    sheet_for_document(document_id)
    with step("WF-PRT-02", "WF", "문서·결재 칸 읽기") as s:
        detail = doc.documents_for_print([document_id]).get(document_id)
        if detail is None:  # 사이에 삭제됨
            raise doc_errors.DocumentNotFound()
        if detail["status"] not in PRINTABLE:
            s.fail(detail["status"])
            raise NotPrintableStatus()
        slot_info = apr.print_slots([document_id]).get(document_id, {})
    return _single(detail, slot_info)


def parse_query(params):
    """A06 쿼리: document_id(필수, 정수), kind(선택, 지금은 single만). 그 밖의 키는 400."""
    problems = []
    unknown = sorted(set(params) - {"document_id", "kind"})
    for key in unknown:
        problems.append({"path": key, "code": "unknown_key", "message": "알 수 없는 조건입니다."})
    kind = params.get("kind")
    if kind not in (None, "single"):
        problems.append(
            {"path": "kind", "code": "invalid", "message": "지금은 문서 단건(single)만 출력합니다."}
        )
    raw = params.get("document_id")
    if raw is None or not str(raw).isdigit():
        problems.append({"path": "document_id", "code": "invalid", "message": "문서 번호(정수)."})
    if problems:
        raise InvalidPrintFilter(details=problems)
    return int(raw)
