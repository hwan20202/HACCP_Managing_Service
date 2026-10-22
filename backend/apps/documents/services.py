"""문서 도메인 서비스 (s2-spec 4.1, 흐름은 s2-flows.md).

- 상태 판단은 상태 집합(EDITABLE, COMPLETABLE, REOPENABLE, LOCKABLE, CORRECTABLE, DELETABLE)으로
  한다(DOC-FR-12). P6: 작성 재개·반려의 목적지만 "열린 정정 여부"를 UPDATE 안의 CASE로 더 본다
  (p6-s2-spec 2.2).
- P4(p4-s2-spec): 작성완료·작성 재개, 업무 대상 참조, 작성 요구 함수(N1~N3), 개선조치.
  모든 쓰기 기능은 트랜잭션의 첫 SQL을 쓰기로 한다(p4-s2-flows "읽는 법").
- 쓰기 기능은 트랜잭션의 첫 SQL을 조건부 UPDATE로 해서 검사와 잠금을 한 번에 한다(DOC-NFR-02).
- step("DOC-…") 단계 ID는 흐름 도식과 같다. 개발 설정에서만 기록된다.
- 이 모듈은 결재(apps.approvals)·워크플로우(apps.document_workflow)를 import하지 않는다.
"""

import json

from django.db import IntegrityError, models, transaction
from django.db.models import Case, Count, Exists, F, Func, OuterRef, Q, Subquery, Value, When
from django.utils import timezone

from apps.core import batch
from apps.core.http import ApiError
from apps.core.trace import step
from apps.staff import roles
from apps.staff import services as staff_services

from . import errors, signals, validation
from .models import (
    SKIP_REASON_MAX,
    STATUS_CHOICES,
    DeviationAction,
    DeviationChecker,
    DocSection,
    Document,
    DocumentCorrection,
    DocumentFile,
    DocumentRef,
    DocumentTemplate,
    File,
)

EDITABLE = ("draft", "rejected", "correcting")  # P6: 정정 중도 수정·작성완료(P6-FR-04)
COMPLETABLE = ("draft", "rejected", "correcting")
REOPENABLE = ("completed",)  # 목적지: 열린 정정이 있으면 correcting, 없으면 draft(P6-FR-05)
LOCKABLE = ("completed",)  # 상신은 작성완료 상태에서만(P4-S2-Q1, D-055)
CORRECTABLE = ("approved",)  # 정정 시작(P6-FR-01)
ROW_APPENDABLE = ("draft", "rejected")  # N2 — P4 그대로(P6a: 정정 중 문서에 행 추가 경로 없음)
CORRECTION_REASON_MAX = 200
NOTE_MAX = 200  # 작성완료 메모(판정 변경 사유) — 저장하지 않고 신호로만(D-080, P6-VR-06)
DELETABLE = ("draft",)  # 그리고 submitted_at IS NULL, 작성 요구 문서 삭제 불가(C-3)
# — 주기 문서(참조 없음)는 예외(D-149, ISS-028)
REF_TARGETS = ("lot_id", "production_batch_id", "item_id", "process_code")
DEVIATION_MAX_CHECKERS = 10
PAGE_SIZE = 20
MAX_RANGE_DAYS = 366
# P14(Q3 a): 문서 머리 담당자(assignee_id)는 더 받지 않는다 — 담당자는 양식에 있음(D-181)
EDITABLE_FIELDS = ("subject", "work_date", "due_at")
# P7(p7-s2-spec 3.2, Q9): DOC가 양식 코드를 직접 아는 첫 예외 — 스키마 표시로 옮기는 일은 ISS-020
# P8(p8-s2-spec 4.1, Q5 a): 목록 묶음 단위 — day = 작업일마다 1줄, week = 그 주 월요일마다 1줄
BUNDLE_UNITS = {"D03": "day", "D10": "week", "D12": "week"}
LIST_BUNDLE_TYPES = tuple(BUNDLE_UNITS)
INSPECTOR_TYPES = ("D03", "D10", "D11", "D12")  # 점검자 일괄 지정 대상(info.inspector)
BRIEF_MAX = 50
SKIPPABLE = ("draft",)  # P8 작성 안 함: 작성중 + record_key + 양식 skippable(VR-P8-05)
RECENT_MAX = 10  # P8 F29 최근 값 개수


def _open_correction(**match):
    """열린 정정(closed_at NULL) 서브쿼리. 문서마다 최대 1개(ux_correction_open)."""
    return DocumentCorrection.objects.filter(
        document_id=OuterRef("document_id"), closed_at__isnull=True, **match
    )


# ---------------------------------------------------------------- 직렬화


def _iso(value):
    if value is None:
        return None
    if hasattr(value, "tzinfo"):
        return timezone.localtime(value).isoformat(timespec="seconds")
    return value.isoformat()


def _template_summary(template):
    return {
        "template_id": template.template_id,
        "type_code": template.type_code,
        "version": template.version,
        "name": template.name,
    }


def _template_detail(template, *, with_schema):
    data = _template_summary(template)
    data["is_active"] = template.is_active
    data["requirement_only"] = bool(template.schema_json.get("requirement_only"))  # F02 변경
    data["sections"] = [
        {"key": s["key"], "label": s.get("label", s["key"]), "repeat": s["repeat"]}
        for s in template.schema_json["sections"]
    ]
    if with_schema:
        data["schema"] = template.schema_json
    return data


def _document_head(document):
    return {
        "document_id": document.document_id,
        "template": _template_summary(document.template),
        "subject": document.subject,
        "work_date": _iso(document.work_date),
        "status": document.status,
        "created_by": document.created_by_id,
        "assignee_id": document.assignee_id,
        "due_at": _iso(document.due_at),
        "created_at": _iso(document.created_at),
        "updated_at": _iso(document.updated_at),
        "submitted_at": _iso(document.submitted_at),
        "version": document.version,
        "record_key": document.record_key,
        "completed_at": _iso(document.completed_at),
        "completed_by": document.completed_by_id,
    }


def _ref_row(ref):
    return {
        "ref_id": ref.ref_id,
        "section_id": ref.section_id,
        "lot_id": ref.lot_id,
        "production_batch_id": ref.production_batch_id,
        "item_id": ref.item_id,
        "process_code": ref.process_code,
        "label": ref.label,
    }


def _requirement(record_key, refs):
    """작성 요구 출처(F04·F05): record_key가 없으면 None, 배치 참조 → batch, 참조 없음 → periodic
    (P9 D-115 규칙을 P8 S4에서 앞당김 — 주기 문서), 그 밖 → lot."""
    if not record_key:
        return None
    if any(r["production_batch_id"] is not None for r in refs):
        return "batch"
    if not refs:
        return "periodic"
    return "lot"


def _item_names(document_ids):
    """작성 요구 문서의 info.item_name(목록 대상 표시용, SQL 1개). 빈 목록이면 SQL 없음."""
    if not document_ids:
        return {}
    names = {}
    for document_id, values in DocSection.objects.filter(
        document_id__in=document_ids, section_def="info"
    ).values_list("document_id", "values_json"):
        name = (values or {}).get("item_name")
        if name:
            names[document_id] = name
    return names


def _target_summary(document, refs, item_name=None, supplier_name=None):
    """대상 표시(S1 SC-01). 작성 요구 문서는 업무 대상, 아니면 subject.

    문서 단위 LOT이면 `LOT {label} · {품명}`(P6a-S2 2.4 — info.item_name이 있을 때).
    P7(ISS-018): 상세·요약은 매입처까지 — `LOT {label} · {품명} · {매입처}`(있는 값만 붙임).
    목록은 supplier_name을 넘기지 않는다(지금 그대로).
    """
    if not document.record_key or not refs:
        return document.subject
    doc_level = [r for r in refs if r["section_id"] is None]
    if doc_level:
        ref = doc_level[0]
        if ref["production_batch_id"] is not None:
            tail = f" · {ref['process_code']}" if ref["process_code"] else ""
            return f"배치 {ref['label'] or ref['production_batch_id']}{tail}"
        if ref["lot_id"] is not None:
            parts = [f"LOT {ref['label'] or ref['lot_id']}", item_name, supplier_name]
            return " · ".join(p for p in parts if p)
        return ref["label"] or document.subject
    lots = [r for r in refs if r["lot_id"] is not None]
    return f"{_iso(document.work_date)} · LOT {len(lots)}건"


def _refs_by_document(document_ids):
    grouped = {doc_id: [] for doc_id in document_ids}
    for ref in DocumentRef.objects.filter(document_id__in=list(document_ids)).order_by("ref_id"):
        grouped[ref.document_id].append(_ref_row(ref))
    return grouped


def _section_row(row):
    return {
        "section_id": row.section_id,
        "section_def": row.section_def,
        "row_no": row.row_no,
        "values": row.values_json,
        "recorded_at": _iso(row.recorded_at),
        "recorded_by": row.recorded_by_id,
    }


def _correction_row(c, document=None):
    row = {
        "correction_id": c.correction_id,
        "started_at": _iso(c.started_at),
        "started_by": c.started_by_id,
        "reason": c.reason,
        "closed_at": _iso(c.closed_at),
        "outcome": c.outcome,
    }
    if document is not None:
        # 정정 취소 가능 = 정정 중이고 정정 시작 뒤 수정하지 않음(D-075)
        row["cancellable"] = document.status == "correcting" and document.version == c.start_version
    return row


def _corrections_of(document):
    """(열린 정정, 정정 이력 최신순). SQL 1개(ix_correction_document)."""
    history = list(
        DocumentCorrection.objects.filter(document_id=document.document_id).order_by(
            "-started_at", "-correction_id"
        )
    )
    current = next((c for c in history if c.closed_at is None), None)
    return (
        None if current is None else _correction_row(current, document),
        [_correction_row(c) for c in history],
    )


def _assemble(document, rows, refs=None, files=None, deviations=None, hints=None, corrections=None):
    order = validation.section_order(document.template.schema_json)
    rows = sorted(rows, key=lambda r: (order.get(r.section_def, len(order)), r.row_no))
    refs = refs or []
    data = _document_head(document)
    data["requirement"] = _requirement(document.record_key, refs)
    data["refs"] = refs
    data["sections"] = [_section_row(r) for r in rows]
    frozen = document.status in FROZEN_STATUSES
    for row in data["sections"]:
        if hints and row["section_id"] in hints:
            row["hints"] = hints[row["section_id"]]
            # D-234 r1: values = 실제 값(성적서 유무는 시스템 계산, 잠긴 문서는 확정 값)
            row["values"], _ = _effective(row["values"], row["hints"], frozen)
    data["files"] = files or []
    data["deviations"] = deviations or []
    data["correction"], data["corrections"] = corrections or (None, [])
    # P8 DOC-F05 변경: 작성 안 함 가능 양식·작성 안 함 기록·N1이 미리 채운 필드
    schema = document.template.schema_json
    data["skippable"] = bool(schema.get("skippable"))
    data["skip"] = (
        None
        if document.skipped_at is None
        else {
            "at": _iso(document.skipped_at),
            "by": document.skipped_by_id,
            "reason": document.skip_reason,
        }
    )
    data["prefilled"] = _prefilled(document, rows)
    info = next((r.values_json or {} for r in rows if r.section_def == "info"), {})
    data["target_summary"] = _target_summary(  # P7 DOC-F05 변경(ISS-018)
        document, refs, info.get("item_name"), info.get("supplier_name")
    )
    return data


def _prefilled(document, rows):
    """N1이 na_default·initial로 채운 필드("섹션.필드"). 아무도 저장하지 않은(version 1)
    작성 요구 문서만 — 값이 규칙 값과 같으면 미리 채운 것으로 본다(P8-S2-Q1 a)."""
    if document.version != 1 or not document.record_key:
        return []
    sections = validation.sections_of(document.template.schema_json)
    result = []
    for row in rows:
        section = sections.get(row.section_def)
        if section is None or section["repeat"]:
            continue
        values = row.values_json or {}
        for key, value in validation.initial_values(section, document.work_date).items():
            if values.get(key) == value:
                result.append(f"{row.section_def}.{key}")
    return result


def _files_of(document_id):
    shared = DocumentFile.objects.filter(file_id=OuterRef("file_id")).values("file_id")
    links = (
        DocumentFile.objects.filter(document_id=document_id)
        .select_related("file")
        .annotate(shared_count=Subquery(shared.annotate(n=Count("pk")).values("n")[:1]))
        .order_by("linked_at")
    )
    return [
        {
            "file_id": link.file.file_id,
            "original_name": link.file.original_name,
            "mime_type": link.file.mime_type,
            "size_bytes": link.file.size_bytes,
            "uploaded_by": link.file.uploaded_by_id,
            "uploaded_at": _iso(link.file.uploaded_at),
            "linked_by": link.linked_by_id,
            "linked_at": _iso(link.linked_at),
            "shared_count": link.shared_count,
        }
        for link in links
    ]


def _deviation_row(deviation, checker_ids):
    return {
        "deviation_id": deviation.deviation_id,
        "document_id": deviation.document_id,
        "section_id": deviation.section_id,
        "description": deviation.description,
        "action_result": deviation.action_result,
        "actor_id": deviation.actor_id,
        "checker_ids": checker_ids,
        "checked_by": deviation.checked_by_id,
        "checked_at": _iso(deviation.checked_at),
        "version": deviation.version,
        "created_by": deviation.created_by_id,
        "created_at": _iso(deviation.created_at),
        "updated_by": deviation.updated_by_id,
        "updated_at": _iso(deviation.updated_at),
    }


def _deviations_of(document_id):
    items = list(
        DeviationAction.objects.filter(document_id=document_id, deleted_at__isnull=True).order_by(
            "deviation_id"
        )
    )
    checkers = {}
    for row in DeviationChecker.objects.filter(
        deviation_id__in=[d.deviation_id for d in items]
    ).order_by("staff_id"):
        checkers.setdefault(row.deviation_id, []).append(row.staff_id)
    return [_deviation_row(d, checkers.get(d.deviation_id, [])) for d in items]


# ---------------------------------------------------------------- D-234 성적서 유무(파생 값)


COA_TYPE = "D01"  # 성적서 유무 = 같은 LOT의 시험성적서(D01)에 파일이 있는가


def _hint_rules(schema):
    """file_exists hint 필드 [(섹션 키, 필드 키, 양식 코드, 반복 여부)](FR-28)."""
    return [
        (section["key"], field["key"], field["hint"].get("type_code"), section.get("repeat", False))
        for section in schema["sections"]
        for field in section["fields"]
        if isinstance(field.get("hint"), dict) and field["hint"].get("kind") == "file_exists"
    ]


def _lots_with_files(lot_ids, type_code):
    """LOT 중 지정 양식(type_code) 문서에 파일이 있는 LOT 집합. SQL 1(빈 목록이면 0)."""
    lots = sorted({lot for lot in lot_ids if lot is not None})
    if not lots:
        return set()
    has_file = DocumentFile.objects.filter(document_id=OuterRef("document_id"))
    matched = Document.objects.filter(
        pk=OuterRef("document_id"), deleted_at__isnull=True, template__type_code=type_code
    )
    return set(
        DocumentRef.objects.filter(lot_id__in=lots, section_id__isnull=True)
        .filter(Exists(matched), Exists(has_file))
        .values_list("lot_id", flat=True)
    )


def coa_status(lot_ids):
    """N11(D-234): LOT별 시험성적서(D01) 파일 유무 {lot_id: "유"|"무"}. SQL 1(빈 목록이면 0).

    성적서 유무의 계산 규칙은 이 한 곳 — 상세·묶음(F26)·출력(N9)·상신 확정(DOC-LCK)이 모두 같은
    계산(_lots_with_files)을 쓴다. D-234 r1: **시스템 계산 값만**(사람 입력 없음 — _effective).
    """
    lots = sorted({i for i in lot_ids if isinstance(i, int) and not isinstance(i, bool)})
    with_files = _lots_with_files(lots, COA_TYPE)
    return {lot: "유" if lot in with_files else "무" for lot in lots}


def _hints_many(items):
    """FR-28 hint 계산을 문서 여러 건에 한 번에. items = [(document, rows, refs)].

    rows: section_def·section_id를 가진 행, refs: _ref_row 목록. LOT은 반복 섹션이면 그 행의
    행 단위 참조, 반복 아닌 섹션이면 문서 단위 참조(P6a-S2 2.3 — D03 v2).
    SQL = 양식 코드 종류 수(보통 1, 규칙·LOT이 없으면 0).
    반환 {document_id: {section_id: {필드: "유"|"무"}}}.
    """
    plans, wanted = [], {}
    for document, rows, refs in items:
        rules = _hint_rules(document.template.schema_json)
        if not rules:
            continue
        row_lots = {r["section_id"]: r["lot_id"] for r in refs if r["section_id"] and r["lot_id"]}
        doc_lot = next((r["lot_id"] for r in refs if r["section_id"] is None and r["lot_id"]), None)
        for section_key, field_key, type_code, repeat in rules:
            for row in rows:
                if row.section_def != section_key:
                    continue
                lot = row_lots.get(row.section_id) if repeat else doc_lot
                if lot is not None:
                    plans.append((document.document_id, row.section_id, field_key, type_code, lot))
                    wanted.setdefault(type_code, set()).add(lot)
    with_files = {code: _lots_with_files(lots, code) for code, lots in wanted.items()}
    result = {}
    for document_id, section_id, field_key, type_code, lot in plans:
        value = "유" if lot in with_files[type_code] else "무"
        result.setdefault(document_id, {}).setdefault(section_id, {})[field_key] = value
    return result


def _hints(document, rows, refs):
    """필드 hint 규칙 계산(FR-28) — 한 문서.

    저장 값은 여기서 바꾸지 않는다(확정은 상신 잠금 D-234).
    """
    return _hints_many([(document, rows, refs)]).get(document.document_id, {})


# D-234 r1: 상신 때 확정한 저장 값을 보여 주는 상태(잠긴 문서). 그 밖에는 지금 계산 값
FROZEN_STATUSES = ("submitted", "approved")


def _effective(values, hints, frozen=False):
    """D-234 r1 실제 값: hint 필드(성적서 유무)는 **시스템 계산 값만** — 사람 입력 없음.

    frozen(결재중·승인)이면 상신 때 확정한 저장 값, 저장 값이 없으면(이 규칙 전에 잠긴 문서)
    계산 값. 반환 (값, 지금 계산으로 채운 키 목록).
    """
    merged, derived = dict(values or {}), []
    for key, value in (hints or {}).items():
        if frozen and merged.get(key) not in (None, ""):
            continue
        merged[key] = value
        derived.append(key)
    return merged, derived


def _freeze_hints(document_id):
    """D-234 R1: 상신 잠금 때 hint 필드(성적서 유무)를 지금 계산 값으로 저장한다(r1: 항상 덮어씀).

    이후 스냅샷·승인본·출력은 이 값으로 고정된다(파일이 나중에 바뀌어도 그대로). 반려·상신 취소·
    정정 뒤 다시 상신하면 그때 계산 값으로 다시 확정. hint 규칙이 없는 양식은 SQL 1(문서·양식).
    반환 바뀐 칸 수.
    """
    document = Document.objects.select_related("template").get(pk=document_id)
    if not _hint_rules(document.template.schema_json):
        return 0
    rows = list(DocSection.objects.filter(document_id=document_id))
    hints = _hints(document, rows, _refs_by_document([document_id])[document_id])
    filled = 0
    for row in rows:
        merged, _ = _effective(row.values_json, hints.get(row.section_id))
        changed = [k for k in merged if merged[k] != (row.values_json or {}).get(k)]
        if changed:
            DocSection.objects.filter(section_id=row.section_id).update(values_json=merged)
            filled += len(changed)
    return filled


def _full(document):
    rows = list(DocSection.objects.filter(document_id=document.document_id))
    refs = _refs_by_document([document.document_id])[document.document_id]
    return _assemble(
        document,
        rows,
        refs=refs,
        files=_files_of(document.document_id),
        deviations=_deviations_of(document.document_id),
        hints=_hints(document, rows, refs),
        corrections=_corrections_of(document),
    )


def _detail(document_id):
    return _full(Document.objects.select_related("template").get(pk=document_id))


# ---------------------------------------------------------------- F01~F03 조회


def list_staff(include_inactive=False):
    """활성 직원 [{id, staff_code, name}](P14 ROLE-A02 — 예전에는 id 목록, D-185).

    include_inactive면 비활성 포함 + is_active(S5 r1 Q1 b — 지난 기록의 사람 표시용).
    """
    with step("DOC-STF-01", "DOC", "staff 목록"):
        if include_inactive:
            return staff_services.all_people()
        return staff_services.active_people()


@roles.scope()
def roles_summary(actor_id=None):
    """P14 ROLE-A01 역할 보기: 활성 양식(최신 버전) 순서로 설정 내용·경고·내 역할."""
    with step("DOC-ROL-01", "DOC", "활성 양식"):
        forms = [(t["type_code"], t["name"]) for t in list_templates()]
    with step("DOC-ROL-02", "DOC", "역할 설정 요약"):
        return roles.summary(forms, actor_id)


def list_templates(all_versions=False):
    """F02 양식 목록. all_versions=True면 모든 버전(비활성 포함) — P7 WF 일괄 설정용(S4 G1)."""
    with step("DOC-TPL-01", "DOC", "최신 활성 양식 목록"):
        if all_versions:
            templates = DocumentTemplate.objects.order_by("type_code", "version")
            return [_template_detail(t, with_schema=False) for t in templates]
        latest = (
            DocumentTemplate.objects.filter(type_code=OuterRef("type_code"), is_active=True)
            .order_by("-version")
            .values("version")[:1]
        )
        templates = DocumentTemplate.objects.filter(
            is_active=True, version=Subquery(latest)
        ).order_by("type_code")
        return [_template_detail(t, with_schema=False) for t in templates]


def get_template(template_id):
    with step("DOC-TPL-02", "DOC", "양식 상세"):
        template = DocumentTemplate.objects.filter(pk=template_id).first()
        if template is None:
            raise errors.TemplateNotFound()
        return _template_detail(template, with_schema=True)


# ---------------------------------------------------------------- F04 목록


def _int_filter(filters, key, problems):
    value = filters.get(key)
    if value in (None, ""):
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    problems.append(validation.error(key, "invalid", "정수여야 합니다."))
    return None


def list_documents(filters=None, page=1):
    filters = filters or {}
    with step("DOC-LST-01", "DOC", "필터 검증"):
        problems = []
        date_from = date_to = None
        if filters.get("from"):
            date_from = validation.parse_work_date(filters["from"])
            if date_from is None:
                problems.append(
                    validation.error("from", "invalid", "YYYY-MM-DD 형식이어야 합니다.")
                )
        if filters.get("to"):
            date_to = validation.parse_work_date(filters["to"])
            if date_to is None:
                problems.append(validation.error("to", "invalid", "YYYY-MM-DD 형식이어야 합니다."))
        if date_from and date_to:
            if date_from > date_to:
                problems.append(validation.error("from", "range", "시작일이 종료일보다 늦습니다."))
            elif (date_to - date_from).days > MAX_RANGE_DAYS:
                problems.append(
                    validation.error("to", "range", f"기간은 {MAX_RANGE_DAYS}일 이내여야 합니다.")
                )
        status = filters.get("status") or None
        if status is not None and status not in STATUS_CHOICES:
            problems.append(validation.error("status", "invalid", "알 수 없는 상태입니다."))
        target = filters.get("target") or None
        if target is not None and (not isinstance(target, str) or not 1 <= len(target) <= 50):
            problems.append(validation.error("target", "invalid", "대상은 1~50자여야 합니다."))
        correcting = filters.get("correcting") or None
        if correcting is not None and correcting not in ("true", "false"):
            problems.append(
                validation.error("correcting", "invalid", "true 또는 false여야 합니다.")
            )
        template_id = _int_filter(filters, "template_id", problems)
        author_id = _int_filter(filters, "author_id", problems)
        owner_id = _int_filter(filters, "owner_id", problems)  # P14 [내 담당 양식]
        page_number = _int_filter({"page": page}, "page", problems) or 1
        if page_number < 1 or page in (0, "0"):
            problems.append(validation.error("page", "invalid", "1 이상이어야 합니다."))
        if problems:
            raise errors.InvalidFilter(details=problems)

    where, params = _list_where(
        correcting=correcting,
        date_from=date_from,
        date_to=date_to,
        status=status,
        template_id=template_id,
        author_id=author_id,
        owner_types=None if owner_id is None else roles.forms_of(owner_id),
        target=target,
    )
    filtered = len(where) > 1  # 삭제 제외 말고 필터가 하나라도 있는가(DOC-LST-06)
    where = " AND ".join(where)
    bundle_in = ", ".join(["%s"] * len(LIST_BUNDLE_TYPES))
    bundle = list(LIST_BUNDLE_TYPES)

    with step("DOC-LST-02", "DOC", "건수(UNION)"):
        with connection_cursor() as cursor:
            cursor.execute(
                f"SELECT COUNT(*) FROM ({_list_union(where, bundle_in, count_only=True)})",
                [*params, *bundle, *params, *bundle],
            )
            total = cursor.fetchone()[0]
    with step("DOC-LST-03", "DOC", "페이지(UNION)"):
        offset = (page_number - 1) * PAGE_SIZE
        with connection_cursor() as cursor:
            cursor.execute(
                f"{_list_union(where, bundle_in)} ORDER BY sort_day DESC, 1, 2 DESC, 4 DESC "
                "LIMIT %s OFFSET %s",
                [*params, *bundle, *params, *bundle, PAGE_SIZE, offset],
            )
            rows = cursor.fetchall()
    documents = [_list_document(row) for row in rows if row[0] == 1]
    bundles = [row for row in rows if row[0] == 0]
    with step("DOC-LST-04", "DOC", "문서 줄 값(참조·품명)") as s:
        refs, names = {}, {}
        if documents:
            refs = _refs_by_document([d.document_id for d in documents])
            names = _item_names([d.document_id for d in documents if d.record_key])
        else:
            s.skip("문서 줄 없음")
    days = sorted({_text_date(row[1]) for row in bundles})
    with step("DOC-LST-05", "DOC", "묶음 집계") as s:
        counts = {}
        if bundles:
            marks = ", ".join(["%s"] * len(days))
            span = [days[0], _week_end(days[-1])]  # 작업일 범위(인덱스용) — 주 묶음은 일요일까지
            with connection_cursor() as cursor:
                cursor.execute(
                    f"SELECT {_BUNDLE_KEY_SQL}, t.type_code, d.status, "
                    f"{_OPEN_CORRECTION_SQL} AS correcting, COUNT(*) "
                    "FROM document d JOIN document_template t ON t.template_id = d.template_id "
                    f"WHERE {where} AND t.type_code IN ({bundle_in}) "
                    f"AND d.work_date BETWEEN %s AND %s AND {_BUNDLE_KEY_SQL} IN ({marks}) "
                    "GROUP BY 1, 2, 3, 4",
                    [*params, *bundle, *span, *days],
                )
                for day, type_code, row_status, row_correcting, n in cursor.fetchall():
                    item = counts.setdefault(
                        (_text_date(day), type_code), {"status": {}, "correcting": 0, "count": 0}
                    )
                    item["status"][row_status] = item["status"].get(row_status, 0) + n
                    item["correcting"] += n if row_correcting else 0
                    item["count"] += n
        else:
            s.skip("묶음 줄 없음")
    with step("DOC-LST-06", "DOC", "묶음 전체 건수") as s:
        totals = {}
        if bundles and filtered:
            marks = ", ".join(["%s"] * len(days))
            span = [days[0], _week_end(days[-1])]
            with connection_cursor() as cursor:
                cursor.execute(
                    f"SELECT {_BUNDLE_KEY_SQL}, t.type_code, COUNT(*) FROM document d "
                    "JOIN document_template t ON t.template_id = d.template_id "
                    f"WHERE d.deleted_at IS NULL AND t.type_code IN ({bundle_in}) "
                    f"AND d.work_date BETWEEN %s AND %s AND {_BUNDLE_KEY_SQL} IN ({marks}) "
                    "GROUP BY 1, 2",
                    [*bundle, *span, *days],
                )
                totals = {(_text_date(d), t): n for d, t, n in cursor.fetchall()}
        else:
            s.skip("묶음 줄 없음" if not bundles else "필터 없음 — 걸러진 수와 같음")
    with step("DOC-LST-07", "DOC", "결과 조립"):
        by_id = {d.document_id: d for d in documents}
        items = []
        for row in rows:
            if row[0] == 1:
                d = by_id[row[3]]
                item = {"kind": "document", **_document_head(d)}
                item["correcting"] = d.correcting
                item["requirement"] = _requirement(d.record_key, refs.get(d.document_id, []))
                item["target_summary"] = _target_summary(
                    d, refs.get(d.document_id, []), names.get(d.document_id)
                )
                items.append(item)
                continue
            key = (_text_date(row[1]), row[2])
            agg = counts.get(key, {"status": {}, "correcting": 0, "count": 0})
            unit = BUNDLE_UNITS[row[2]]
            items.append(
                {
                    "kind": "bundle",
                    "type_code": row[2],
                    "template_name": row[_COL_NAME],
                    "work_date": key[0],
                    # P8: 주 묶음은 work_date = 월요일, period_end = 금요일(표시용)
                    "bundle_unit": unit,
                    "period_end": _week_friday(key[0]) if unit == "week" else None,
                    "count": agg["count"],
                    "total": totals.get(key, agg["count"]) if filtered else agg["count"],
                    "status_counts": {k: v for k, v in agg["status"].items() if v},
                    "correcting_count": agg["correcting"],
                    "requirement": "lot" if unit == "day" else "periodic",
                }
            )
        return {
            "items": items,
            "total": total,
            "page": page_number,
            "page_size": PAGE_SIZE,
        }


# 목록 SQL (p7-s2-flows 6장, P7 S3 1.1). d.deleted_at IS NULL은 부분 인덱스 ix_document_list의
# 조건이라 문자 그대로 넣는다. 열린 정정 EXISTS는 ux_correction_open(부분 인덱스)으로 찾는다.
_OPEN_CORRECTION_SQL = (
    "EXISTS (SELECT 1 FROM document_correction c "
    "WHERE c.document_id = d.document_id AND c.closed_at IS NULL)"
)
_LIST_COLUMNS = (
    "t.template_id",
    "t.version",
    "t.name",
    "d.subject",
    "d.status",
    "d.created_by",
    "d.assignee_id",
    "d.due_at",
    "d.created_at",
    "d.updated_at",
    "d.submitted_at",
    "d.version",
    "d.record_key",
    "d.completed_at",
    "d.completed_by",
    _OPEN_CORRECTION_SQL,
)
_COL_NAME = 4 + _LIST_COLUMNS.index("t.name")  # kind, work_date, type_code, document_id 다음


def _bundle_key_sql():
    """묶음 줄의 날짜 키: week 양식은 그 주 월요일(SQLite date — 'weekday 0'은 그 주 일요일),
    그 밖은 작업일. 양식 코드는 코드 상수라 SQL에 문자로 넣는다."""
    import re

    weeks = [code for code, unit in BUNDLE_UNITS.items() if unit == "week"]
    assert all(re.fullmatch(r"[A-Z0-9-]+", code) for code in weeks)
    if not weeks:
        return "d.work_date"
    codes = ", ".join(f"'{code}'" for code in weeks)
    return (
        f"CASE WHEN t.type_code IN ({codes}) "
        "THEN date(d.work_date, 'weekday 0', '-6 days') ELSE d.work_date END"
    )


_BUNDLE_KEY_SQL = _bundle_key_sql()


def _week_end(day):
    from datetime import date, timedelta

    return (date.fromisoformat(day) + timedelta(days=6)).isoformat()


def _week_friday(monday):
    from datetime import date, timedelta

    return (date.fromisoformat(monday) + timedelta(days=4)).isoformat()


def _list_where(**f):
    """문서마다 필터 F(p7-s2-flows 6장). 반환: ([조건], [값]) — 첫 조건은 삭제 제외."""
    where, params = ["d.deleted_at IS NULL"], []
    if f["correcting"] is not None:
        where.append(
            _OPEN_CORRECTION_SQL if f["correcting"] == "true" else f"NOT {_OPEN_CORRECTION_SQL}"
        )
    if f["date_from"]:
        where.append("d.work_date >= %s")
        params.append(_db_date(f["date_from"]))
    if f["date_to"]:
        where.append("d.work_date <= %s")
        params.append(_db_date(f["date_to"]))
    for column, key in (
        ("d.status", "status"),
        ("d.template_id", "template_id"),
        ("d.created_by", "author_id"),
    ):
        if f[key] is not None:
            where.append(f"{column} = %s")
            params.append(f[key])
    if f.get("owner_types") is not None:  # P14: 내가 담당자인 양식(설정)
        types = list(f["owner_types"]) or [""]
        marks = ", ".join(["%s"] * len(types))
        where.append(
            "d.template_id IN (SELECT template_id FROM document_template"
            f" WHERE type_code IN ({marks}))"
        )
        params.extend(types)
    if f["target"]:
        # 지금까지의 label__icontains와 같은 식(SQLite LIKE, ESCAPE)
        from django.db import connection

        where.append(
            "EXISTS (SELECT 1 FROM document_ref rf WHERE rf.document_id = d.document_id "
            "AND rf.label LIKE %s ESCAPE '\\')"
        )
        params.append(f"%{connection.ops.prep_for_like_query(f['target'])}%")
    return where, params


def _list_union(where, bundle_in, count_only=False):
    """문서 줄(kind 1)과 묶음 줄(kind 0, 묶음 키·양식 유형마다 1줄)의 UNION ALL.

    묶음 키: day 양식은 작업일, week 양식은 그 주 월요일(P8 F04 변경).
    정렬 날짜(sort_day, 맨 뒤 열): 문서 줄은 작업일, 묶음 줄은 그 묶음의 가장 늦은 작업일 — 이번 주
    주 줄이 화~오늘 문서 뒤로 밀리지 않게(ISS-031, P8-S5-Q1 a). day 묶음은 키와 같음.
    같은 정렬 날짜에서는 묶음 줄이 먼저(P7처럼), 그다음 묶음 키·문서 번호 내림차순."""
    columns = ["NULL"] if count_only else list(_LIST_COLUMNS)
    sort = "" if count_only else ", d.work_date AS sort_day"
    sort_bundle = "" if count_only else ", MAX(d.work_date)"
    nulls = ["NULL"] * len(columns)
    if not count_only:
        nulls[_LIST_COLUMNS.index("t.name")] = "MAX(t.name)"
    source = "FROM document d JOIN document_template t ON t.template_id = d.template_id"
    return (
        f"SELECT 1 AS kind, d.work_date, t.type_code, d.document_id, {', '.join(columns)}{sort} "
        f"{source} WHERE {where} AND t.type_code NOT IN ({bundle_in}) "
        f"UNION ALL SELECT 0, {_BUNDLE_KEY_SQL}, t.type_code, MIN(d.document_id), "
        f"{', '.join(nulls)}{sort_bundle} "
        f"{source} WHERE {where} AND t.type_code IN ({bundle_in}) "
        f"GROUP BY t.type_code, {_BUNDLE_KEY_SQL}"
    )


def _text_date(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def _list_document(row):
    """페이지 쿼리의 문서 줄을 _document_head가 읽는 모양으로(SQL 다시 읽지 않음 — 검토 B-3)."""
    from types import SimpleNamespace

    from django.db import connection

    ops = connection.ops
    values = dict(zip(("kind", "work_date", "type_code", "document_id", *_LIST_COLUMNS), row))

    def dt(key):
        return ops.convert_datetimefield_value(values[key], None, connection)

    def day(key):
        return ops.convert_datefield_value(values[key], None, connection)

    return SimpleNamespace(
        document_id=values["document_id"],
        template=SimpleNamespace(
            template_id=values["t.template_id"],
            type_code=values["type_code"],
            version=values["t.version"],
            name=values["t.name"],
        ),
        subject=values["d.subject"],
        work_date=day("work_date"),
        status=values["d.status"],
        created_by_id=values["d.created_by"],
        assignee_id=values["d.assignee_id"],
        due_at=dt("d.due_at"),
        created_at=dt("d.created_at"),
        updated_at=dt("d.updated_at"),
        submitted_at=dt("d.submitted_at"),
        version=values["d.version"],
        record_key=values["d.record_key"],
        completed_at=dt("d.completed_at"),
        completed_by_id=values["d.completed_by"],
        correcting=bool(values[_OPEN_CORRECTION_SQL]),
    )


# ---------------------------------------------------------------- F05 상세


def get_document(document_id):
    with step("DOC-GET-01", "DOC", "문서 조회"):
        document = (
            Document.objects.select_related("template")
            .filter(pk=document_id, deleted_at__isnull=True)
            .first()
        )
        if document is None:
            raise errors.DocumentNotFound()
    with step("DOC-GET-02", "DOC", "섹션 행·참조·파일·개선조치 조회"):
        rows = list(DocSection.objects.filter(document_id=document_id))
        refs = _refs_by_document([document_id])[document_id]
        files = _files_of(document_id)
        deviations = _deviations_of(document_id)
        hints = _hints(document, rows, refs)
    with step("DOC-GET-03", "DOC", "정정 기록 조회·조립"):
        return _assemble(document, rows, refs, files, deviations, hints, _corrections_of(document))


# ---------------------------------------------------------------- 검증 공통


def _check_staff(pairs, problems):
    """pairs: [(path, staff_id)] — 존재하지 않는 staff를 경로별 오류로 추가."""
    existing = staff_services.existing_ids(sid for _, sid in pairs)
    for path, staff_id in pairs:
        if staff_id not in existing:
            problems.append(validation.error(path, "unknown_staff", "등록되지 않은 사용자입니다."))


def _raise_if_invalid(problems, duplicates):
    if problems:
        raise errors.ValidationFailed(details=problems + duplicates)
    if duplicates:
        raise errors.DuplicateRound(details=duplicates)


def _is_round_violation(error):
    return "ux_section_round" in str(error)


# ---------------------------------------------------------------- F06 작성


@roles.scope()
def create_document(actor_id, data):
    now = timezone.now()
    with step("DOC-WRT-01", "DOC", "양식 유형(새 문서 — 점검자 없음)") as s:
        new_type = (
            DocumentTemplate.objects.filter(pk=data.get("template_id"))
            .values_list("type_code", flat=True)
            .first()
        )
        if new_type is None:
            s.skip("양식 없음 — DOC-CRT-03에서 404")
    if new_type is not None:
        _check_write(actor_id, (new_type, None, None))  # ROLE-R07(r13): 404 → 403 → 409
    with step("DOC-CRT-03", "DOC", "양식 확인"):
        template = DocumentTemplate.objects.filter(pk=data.get("template_id")).first()
        if template is None:
            raise errors.TemplateNotFound()
        if not template.is_active:
            raise errors.TemplateInactive()
        if template.schema_json.get("requirement_only"):
            raise errors.TemplateRequirementOnly()
        schema_sections = validation.sections_of(template.schema_json)

    with step("DOC-CRT-04", "DOC", "기본 정보 검증") as s:
        basic, problems, _ = validation.check_basic(data, partial=False)
        if problems:
            s.fail(f"오류 {len(problems)}건")

    rows_in = data.get("sections")
    staff_pairs = []
    if "assignee_id" in basic and basic["assignee_id"] is not None:
        staff_pairs.append(("assignee_id", basic["assignee_id"]))
    for i, row in enumerate(rows_in if isinstance(rows_in, list) else []):
        if isinstance(row, dict) and row.get("section_def") in schema_sections:
            staff_pairs += validation.staff_field_paths(
                schema_sections[row["section_def"]], row.get("values"), f"sections[{i}].values"
            )
    with step("DOC-CRT-05", "DOC", "staff 존재 확인") as s:
        before = len(problems)
        _check_staff(staff_pairs, problems)
        if len(problems) > before:
            s.fail(f"오류 {len(problems) - before}건")

    with step("DOC-CRT-06", "DOC", "섹션 검증") as s:
        before = len(problems)
        duplicates = []
        new_rows = []
        counts = {key: 0 for key in schema_sections}
        by_section = {key: [] for key in schema_sections}
        if not isinstance(rows_in, list):
            problems.append(
                validation.error("sections", "invalid", "sections는 목록이어야 합니다.")
            )
            rows_in = []
        for i, row in enumerate(rows_in):
            path = f"sections[{i}]"
            if not isinstance(row, dict) or row.get("section_def") not in schema_sections:
                problems.append(
                    validation.error(
                        f"{path}.section_def", "unknown_section", "양식에 없는 섹션입니다."
                    )
                )
                continue
            key = row["section_def"]
            values = row.get("values", {})
            problems += validation.system_key_errors(schema_sections[key], values, f"{path}.values")
            row_errors, _ = validation.check_values(schema_sections[key], values, f"{path}.values")
            problems += row_errors
            problems += validation.context_errors(  # P8 VR-P8-02·03
                schema_sections[key], values, f"{path}.values", basic.get("work_date")
            )
            counts[key] += 1
            by_section[key].append((f"{path}.values", values))
            if isinstance(values, dict):
                values = validation.with_computed(schema_sections[key], values)
            new_rows.append((key, counts[key], values))
        for key, section in schema_sections.items():
            if not section["repeat"] and counts[key] == 0:
                # 필수값은 작성완료 때 검사한다(C-2). 빈 행을 만들어 둔다(VR-07 ②).
                counts[key] = 1
                new_rows.append((key, 1, validation.with_computed(section, {})))
            if not section["repeat"] and counts[key] != 1:
                problems.append(
                    validation.error(
                        f"sections[{key}]",
                        "row_count",
                        f"'{section.get('label', key)}' 영역은 정확히 1행이어야 합니다.",
                    )
                )
            if section["repeat"] and section.get("max_rows") and counts[key] > section["max_rows"]:
                problems.append(validation.max_rows_error(key, section))
            if section["repeat"]:
                duplicates += validation.duplicate_rounds(by_section[key])
        if len(problems) > before or duplicates:
            s.fail(f"오류 {len(problems) - before}건, 중복 {len(duplicates)}건")
        _raise_if_invalid(problems, duplicates)

    try:
        with transaction.atomic():
            with step("DOC-CRT-07", "DOC", "문서 저장"):
                document = Document.objects.create(
                    template=template,
                    subject=basic.get("subject"),
                    work_date=basic["work_date"],
                    assignee_id=basic.get("assignee_id"),
                    created_by_id=actor_id,
                    due_at=basic.get("due_at"),
                    status="draft",
                    created_at=now,
                    updated_at=now,
                )
            with step("DOC-CRT-08", "DOC", "섹션 저장"):
                DocSection.objects.bulk_create(
                    DocSection(
                        document=document,
                        section_def=key,
                        row_no=row_no,
                        values_json=values,
                        recorded_at=now,
                        recorded_by_id=actor_id,
                    )
                    for key, row_no, values in new_rows
                )
    except IntegrityError as error:
        if _is_round_violation(error):
            with step("DOC-CRT-08a", "DOC", "측정시점 중복(DB 제약)") as s:
                s.fail("ux_section_round")
            raise errors.DuplicateRound() from error
        raise

    with step("DOC-CRT-09", "DOC", "결과 조회"):
        return _detail(document.document_id)


# ---------------------------------------------------------------- F07 수정


def _patch_parts(patch):
    sections = patch.get("sections") or {}
    return (
        patch.get("document") or {},
        sections.get("add") or [],
        sections.get("update") or [],
        sections.get("delete") or [],
    )


def _lock_failure(
    document_id,
    step_id,
    *,
    deletable=False,
    expected_version=None,
    allowed=EDITABLE,
    skipped_transition=False,
):
    """조건부 UPDATE가 0행일 때 이유를 구분한다: 404 → 409 상태 → 409 버전 순서.

    allowed: 그 기능이 허용하는 상태 집합(수정·작성완료는 EDITABLE, 상신 잠금은 LOCKABLE).
    skipped_transition: 작성 안 함 문서면 INVALID_TRANSITION(P8 F12 — 작성완료).
    """
    with step(step_id, "DOC", "잠금 실패 사유 확인"):
        row = (
            Document.objects.filter(pk=document_id)
            .values("status", "deleted_at", "submitted_at", "version", "updated_at", "record_key")
            .first()
        )
        if row is None or row["deleted_at"] is not None:
            raise errors.DocumentNotFound()
        if deletable:
            periodic = (
                row["record_key"] is not None
                and not DocumentRef.objects.filter(document_id=document_id).exists()
            )
            if row["record_key"] is not None and not periodic:
                reason, message = "requirement", "작성 요구로 만들어진 문서는 삭제할 수 없습니다."
            elif row["status"] not in DELETABLE:
                reason, message = "status", f"현재 상태: {row['status']}"
            else:
                reason, message = "submitted", "상신 이력이 있는 문서입니다."
            raise errors.DocumentNotDeletable(
                details=[{"path": "document", "code": reason, "reason": reason, "message": message}]
            )
        if skipped_transition and row["status"] == "skipped":
            raise errors.InvalidTransition(
                details=[{"path": "status", "code": "skipped", "message": "작성 안 함 문서입니다."}]
            )
        if row["status"] in allowed and expected_version is not None:
            if row["version"] != expected_version:
                raise errors.VersionConflict(
                    details=[
                        {
                            "path": "expected_version",
                            "code": "conflict",
                            "message": f"내가 연 버전 {expected_version}, 현재 {row['version']}",
                            "expected": expected_version,
                            "current": row["version"],
                            "updated_at": _iso(row["updated_at"]),
                        }
                    ]
                )
        raise errors.DocumentLocked(
            details=[
                {"path": "status", "code": row["status"], "message": f"현재 상태: {row['status']}"}
            ]
        )


def _expected_version(patch):
    value = patch.get("expected_version")
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ApiError(
            "expected_version(화면이 읽은 문서 버전)이 필요합니다.",
            [
                {
                    "path": "expected_version",
                    "code": "required",
                    "message": "1 이상의 정수여야 합니다.",
                }
            ],
        )
    return value


def update_document(actor_id, document_id, patch):
    """바뀐 부분만 반영한다. patch["expected_version"]이 현재 버전과 같아야 한다(ISS-001)."""
    expected_version = _expected_version(patch)
    doc_fields, adds, updates, deletes = _patch_parts(patch)
    if not (doc_fields or adds or updates or deletes):
        raise errors.NoChanges()
    with roles.scope():
        target = require_write(actor_id, document_id)  # ROLE-R07(r13)
        if _inspector_changed(updates, target):
            _require_inspector_setter(actor_id, target[0])  # ROLE-R08(r13)
    now = timezone.now()
    try:
        with transaction.atomic():
            with step("DOC-UPD-03", "DOC", "문서 잠금(조건부 UPDATE)") as s:
                locked = Document.objects.filter(
                    pk=document_id,
                    deleted_at__isnull=True,
                    status__in=EDITABLE,
                    version=expected_version,
                ).update(updated_at=now, version=F("version") + 1)
                s.note(f"영향 행 {locked}")
            if locked == 0:
                _lock_failure(document_id, "DOC-UPD-03a", expected_version=expected_version)

            with step("DOC-UPD-04", "DOC", "현재 데이터 읽기"):
                document = Document.objects.select_related("template").get(pk=document_id)
                schema_sections = validation.sections_of(document.template.schema_json)
                current = {r.section_id: r for r in DocSection.objects.filter(document=document)}
                wanted = {u.get("section_id") for u in updates if isinstance(u, dict)} | set(
                    deletes
                )
                missing = sorted((i for i in wanted if i not in current), key=str)
                if missing:
                    raise errors.SectionRowNotFound(
                        details=[
                            {
                                "path": "sections",
                                "code": "not_found",
                                "message": f"section_id {i}은(는) 이 문서의 행이 아닙니다.",
                            }
                            for i in missing
                        ]
                    )

            with step("DOC-UPD-05", "DOC", "변경 결과 검증") as s:
                basic, problems, _ = validation.check_basic(doc_fields, partial=True)
                if document.record_key and "work_date" in doc_fields:
                    problems.append(
                        validation.error(
                            "document.work_date",
                            "fixed",
                            "작성 요구 문서의 작업일은 바꿀 수 없습니다.",
                        )
                    )
                staff_pairs = []
                if basic.get("assignee_id") is not None:
                    staff_pairs.append(("document.assignee_id", basic["assignee_id"]))
                work_date = basic.get("work_date", document.work_date)  # P8 date_window 기준
                final = {
                    sid: (f"section_id:{sid}", r.section_def, r.values_json)
                    for sid, r in current.items()
                }
                for sid in deletes:
                    key = current[sid].section_def
                    if schema_sections.get(key, {}).get("system_rows"):
                        problems.append(
                            validation.error(
                                f"sections.delete[{sid}]",
                                "system_rows",
                                "자동으로 추가된 행은 삭제할 수 없습니다.",
                            )
                        )
                    if not schema_sections.get(key, {}).get("repeat", True):
                        problems.append(
                            validation.error(
                                f"sections.delete[{sid}]",
                                "single_row",
                                "1행 영역은 삭제할 수 없습니다.",
                            )
                        )
                    final.pop(sid, None)
                merged_updates = []
                for i, item in enumerate(updates):
                    path = f"sections.update[{i}].values"
                    row = current[item["section_id"]]
                    patch_values = item.get("values")
                    if not isinstance(patch_values, dict):
                        problems.append(
                            validation.error(path, "invalid", "values는 객체여야 합니다.")
                        )
                        continue
                    merged = validation.merge_patch(row.values_json, patch_values)
                    section = schema_sections.get(row.section_def)
                    if section:
                        problems += validation.system_key_errors(section, patch_values, path)
                        row_errors, _ = validation.check_values(section, merged, path)
                        problems += row_errors
                        problems += validation.context_errors(section, merged, path, work_date)
                        staff_pairs += validation.staff_field_paths(section, patch_values, path)
                    final[row.section_id] = (path, row.section_def, merged)
                    merged_updates.append((row.section_id, patch_values))
                new_rows = []
                for i, item in enumerate(adds):
                    path = f"sections.add[{i}]"
                    key = item.get("section_def") if isinstance(item, dict) else None
                    section = schema_sections.get(key)
                    if section is None:
                        problems.append(
                            validation.error(
                                f"{path}.section_def", "unknown_section", "양식에 없는 섹션입니다."
                            )
                        )
                        continue
                    if not section["repeat"]:
                        problems.append(
                            validation.error(
                                f"{path}.section_def",
                                "single_row",
                                "1행 영역에는 행을 추가할 수 없습니다.",
                            )
                        )
                        continue
                    if section.get("system_rows"):
                        problems.append(
                            validation.error(
                                f"{path}.section_def",
                                "system_rows",
                                "이 영역의 행은 자동으로만 추가됩니다.",
                            )
                        )
                        continue
                    values = item.get("values", {})
                    problems += validation.system_key_errors(section, values, f"{path}.values")
                    row_errors, _ = validation.check_values(section, values, f"{path}.values")
                    problems += row_errors
                    problems += validation.context_errors(
                        section, values, f"{path}.values", work_date
                    )
                    staff_pairs += validation.staff_field_paths(section, values, f"{path}.values")
                    final[f"new{i}"] = (f"{path}.values", key, values)
                    new_rows.append((key, values))
                _check_staff(staff_pairs, problems)
                duplicates = []
                for key, section in schema_sections.items():
                    if not section["repeat"]:
                        continue
                    rows = [(p, v) for p, k, v in final.values() if k == key]
                    if section.get("max_rows") and len(rows) > section["max_rows"]:
                        problems.append(validation.max_rows_error(key, section))
                    duplicates += validation.duplicate_rounds(rows)
                if problems or duplicates:
                    s.fail(f"오류 {len(problems)}건, 중복 {len(duplicates)}건")
                _raise_if_invalid(problems, duplicates)

            with step("DOC-UPD-05b", "DOC", "판정(computed) 다시 계산") as s:
                recomputed = 0
                for index, (section_id, patch_values) in enumerate(merged_updates):
                    section = schema_sections.get(current[section_id].section_def)
                    if section is None:
                        continue
                    merged = validation.merge_patch(current[section_id].values_json, patch_values)
                    computed = validation.computed_values(section, merged)
                    if computed:
                        merged_updates[index] = (section_id, {**patch_values, **computed})
                        recomputed += 1
                for index, (key, values) in enumerate(new_rows):
                    if isinstance(values, dict) and schema_sections.get(key):
                        new_rows[index] = (
                            key,
                            validation.with_computed(schema_sections[key], values),
                        )
                s.note(f"계산한 행 {recomputed + len(new_rows)}")

            with step("DOC-UPD-06", "DOC", "기본 정보 반영") as s:
                if basic:
                    Document.objects.filter(pk=document_id).update(**basic)
                else:
                    s.skip("바뀐 기본 정보 없음")
            with step("DOC-UPD-07", "DOC", "행 삭제") as s:
                if deletes:
                    DocSection.objects.filter(
                        document_id=document_id, section_id__in=deletes
                    ).delete()
                else:
                    s.skip("삭제 행 없음")
            with step("DOC-UPD-08", "DOC", "행 변경(json_patch)") as s:
                for section_id, patch_values in merged_updates:
                    DocSection.objects.filter(
                        document_id=document_id, section_id=section_id
                    ).update(
                        values_json=Func(
                            F("values_json"),
                            Value(json.dumps(patch_values, ensure_ascii=False)),
                            function="json_patch",
                            output_field=models.JSONField(),
                        ),
                        recorded_at=now,
                        recorded_by_id=actor_id,
                    )
                if not merged_updates:
                    s.skip("변경 행 없음")
            with step("DOC-UPD-09", "DOC", "행 추가") as s:
                if new_rows:
                    next_no = {}
                    for row in current.values():
                        next_no[row.section_def] = max(next_no.get(row.section_def, 0), row.row_no)
                    objects = []
                    for key, values in new_rows:
                        next_no[key] = next_no.get(key, 0) + 1
                        objects.append(
                            DocSection(
                                document_id=document_id,
                                section_def=key,
                                row_no=next_no[key],
                                values_json=values,
                                recorded_at=now,
                                recorded_by_id=actor_id,
                            )
                        )
                    DocSection.objects.bulk_create(objects)
                else:
                    s.skip("추가 행 없음")
    except IntegrityError as error:
        if _is_round_violation(error):
            with step("DOC-UPD-09a", "DOC", "측정시점 중복(DB 제약)") as s:
                s.fail("ux_section_round")
            raise errors.DuplicateRound() from error
        raise

    with step("DOC-UPD-10", "DOC", "결과 조회"):
        return _detail(document_id)


# ---------------------------------------------------------------- F08 삭제(논리)


@roles.scope()
def delete_document(actor_id, document_id):
    require_write(actor_id, document_id)  # ROLE-R07(r13)
    now = timezone.now()
    with transaction.atomic():
        with step("DOC-DEL-02", "DOC", "삭제 표시(조건부 UPDATE)") as s:
            # 작성 요구 문서 중 주기 문서(record_key 있고 참조 없음 — _requirement periodic)는
            # 지울 수 있다(C4 S6, D-149 — ISS-028). 지우면 record_key를 비워 그 날짜를
            # 다시 만들 수 있게 한다(유일 인덱스).
            has_ref = Exists(DocumentRef.objects.filter(document_id=OuterRef("pk")))
            marked = (
                Document.objects.filter(
                    pk=document_id,
                    deleted_at__isnull=True,
                    status__in=DELETABLE,
                    submitted_at__isnull=True,
                )
                .filter(Q(record_key__isnull=True) | ~has_ref)
                .update(
                    deleted_at=now,
                    deleted_by_id=actor_id,
                    updated_at=now,
                    version=F("version") + 1,
                    record_key=None,
                )
            )
            s.note(f"영향 행 {marked}")
        if marked == 0:
            _lock_failure(document_id, "DOC-DEL-02a", deletable=True)
    with step("DOC-DEL-03", "DOC", "완료"):
        return None


def delete_source_documents(actor_id, document_ids):
    """N10(D-178): 원천 기록(입고)이 취소되어 그 문서들을 함께 소프트 딜리트한다(REQ F12 전용).

    사용자 삭제(F08 delete_document)의 조건 — 작성중·상신 이력 없음·작성 요구 문서 아님 — 을
    보지 않는다(D-017·D-021·C-3의 예외). 열린 정정은 닫는다(outcome cancelled).
    결재 회차는 APR이 닫는다(DOC → APR 의존 없음). 이미 지운 문서는 건너뜀.
    개선조치·파일 연결 행은 그대로(문서가 지워져 목록·확인 대기에서 빠짐).
    반환 {deleted: [id…], closed_corrections: n}.
    """
    with step("DOC-SDL-00", "DOC", "트랜잭션·입력 확인"):
        _require_transaction()
        ids = list(dict.fromkeys(document_ids))
        if not all(isinstance(i, int) and not isinstance(i, bool) for i in ids):
            raise errors.ValidationFailed(
                details=[validation.error("document_ids", "invalid", "정수 목록입니다.")]
            )
    now = timezone.now()
    with step("DOC-SDL-01", "DOC", "삭제 대상(지우지 않은 문서)") as s:
        targets = list(
            Document.objects.filter(pk__in=ids, deleted_at__isnull=True)
            .order_by("document_id")
            .values_list("pk", flat=True)
        )
        s.note(f"{len(targets)}건")
    with step("DOC-SDL-02", "DOC", "열린 정정 닫기") as s:
        closed = 0
        if targets:
            closed = DocumentCorrection.objects.filter(
                document_id__in=targets, closed_at__isnull=True
            ).update(closed_at=now, outcome="cancelled")
        else:
            s.skip("대상 없음")
        s.note(f"닫은 정정 {closed}")
    with step("DOC-SDL-03", "DOC", "삭제 표시(조건부 UPDATE)") as s:
        marked = 0
        if targets:
            marked = Document.objects.filter(pk__in=targets, deleted_at__isnull=True).update(
                deleted_at=now,
                deleted_by_id=actor_id,
                updated_at=now,
                version=F("version") + 1,
            )
        else:
            s.skip("대상 없음")
        s.note(f"영향 행 {marked}")
    return {"deleted": targets, "closed_corrections": closed}


# ---------------------------------------------------------------- F09~F11 생명주기 (WF 전용)


def _require_transaction():
    if not transaction.get_connection().in_atomic_block:
        raise errors.TransactionRequired()


def _lifecycle_result(document_id):
    row = (
        Document.objects.filter(pk=document_id)
        .values("document_id", "template_id", "status", "submitted_at", "version")
        .get()
    )
    row["submitted_at"] = _iso(row["submitted_at"])
    return row


def _transition_failure(document_id, step_id):
    with step(step_id, "DOC", "전이 실패 사유 확인"):
        exists = Document.objects.filter(pk=document_id, deleted_at__isnull=True).exists()
        raise errors.InvalidTransition() if exists else errors.DocumentNotFound()


def _send_signal(document_id, event, actor_id=None, note=None, at=None):
    """DOC-SIG-01: 생명주기 신호(P6-FR-17). 받는 쪽 단계(EFF-…)는 이 단계 안에 이어서 기록된다."""
    with step("DOC-SIG-01", "DOC", f"생명주기 신호({event})"):
        type_code = (
            Document.objects.filter(pk=document_id)
            .values_list("template__type_code", flat=True)
            .first()
        )
        signals.document_transitioned.send(
            sender=Document,
            document_id=document_id,
            event=event,
            actor_id=actor_id,
            note=note,
            at=at or timezone.now(),
            type_code=type_code,
        )


def lock_for_review(document_id, expected_version=None):
    """상신 잠금: completed → submitted (P4-S2-Q1). WF 트랜잭션 안에서만 호출한다.

    expected_version을 주면 화면이 본 버전과 같을 때만 잠근다(WF 변경 요청 C-1).
    """
    with step("DOC-LCK-00", "DOC", "트랜잭션 확인"):
        _require_transaction()
    now = timezone.now()
    with step("DOC-LCK-01", "DOC", "상신 잠금(조건부 UPDATE)") as s:
        filters = {"pk": document_id, "deleted_at__isnull": True, "status__in": LOCKABLE}
        if expected_version is not None:
            filters["version"] = expected_version
        changed = Document.objects.filter(**filters).update(
            status="submitted", submitted_at=now, updated_at=now, version=F("version") + 1
        )
        s.note(f"영향 행 {changed}")
    if changed == 0:
        _lock_failure(
            document_id, "DOC-LCK-01a", expected_version=expected_version, allowed=LOCKABLE
        )
    with step("DOC-LCK-01b", "DOC", "연결 파일 보존 표시") as s:
        # 스프린트 3(D-058, p4-s2-flows 9장): 상신된 문서의 파일은 끊어도 지우지 않는다(FR-24)
        kept = File.objects.filter(
            retained_at__isnull=True,
            file_id__in=DocumentFile.objects.filter(document_id=document_id).values("file_id"),
        ).update(retained_at=now)
        s.note(f"보존 표시 {kept}개")
    with step("DOC-LCK-01c", "DOC", "파생 값 확정(성적서 유무 — D-234)") as s:
        s.note(f"확정 {_freeze_hints(document_id)}칸")
    with step("DOC-LCK-02", "DOC", "결과"):
        return _lifecycle_result(document_id)


def mark_approved(document_id):
    """승인 확정: submitted → approved. 열린 정정이 있으면 같은 트랜잭션에서 닫는다(P6-FR-07).

    WF 트랜잭션 안에서만 호출한다.
    """
    _require_transaction()
    now = timezone.now()
    with step("DOC-APV-01", "DOC", "승인 확정(조건부 UPDATE)·정정 닫기") as s:
        changed = Document.objects.filter(
            pk=document_id, deleted_at__isnull=True, status="submitted"
        ).update(status="approved", updated_at=now, version=F("version") + 1)
        closed = 0
        if changed:
            closed = DocumentCorrection.objects.filter(
                document_id=document_id, closed_at__isnull=True
            ).update(closed_at=now, outcome="approved")
        s.note(f"영향 행 {changed}, 닫은 정정 {closed}")
    if changed == 0:
        _transition_failure(document_id, "DOC-APV-01a")
    _send_signal(document_id, "approved", at=now)
    with step("DOC-APV-02", "DOC", "결과"):
        return _lifecycle_result(document_id)


def mark_rejected(document_id):
    """반려: submitted → rejected, 열린 정정이 있으면 correcting(작성완료 기록 지움, P6-FR-06).

    목적지는 UPDATE 안의 CASE로 정한다 — 앞에 SELECT를 두지 않는다(P6-NFR-01).
    WF 트랜잭션 안에서만 호출한다.
    """
    _require_transaction()
    open_correction = Exists(_open_correction())
    with step("DOC-RJT-01", "DOC", "반려(조건부 UPDATE, 목적지 CASE)") as s:
        changed = Document.objects.filter(
            pk=document_id, deleted_at__isnull=True, status="submitted"
        ).update(
            status=Case(When(open_correction, then=Value("correcting")), default=Value("rejected")),
            completed_at=Case(When(open_correction, then=Value(None)), default=F("completed_at")),
            completed_by_id=Case(
                When(open_correction, then=Value(None)), default=F("completed_by_id")
            ),
            updated_at=timezone.now(),
            version=F("version") + 1,
        )
        s.note(f"영향 행 {changed}")
    if changed == 0:
        _transition_failure(document_id, "DOC-RJT-01a")
    _send_signal(document_id, "rejected")
    with step("DOC-RJT-02", "DOC", "결과"):
        return _lifecycle_result(document_id)


def unlock_for_review(document_id):
    """F23 상신 취소 되돌림: submitted → completed (P10, p10-s2-spec 3.1). WF 트랜잭션 안에서만.

    작성완료 기록(completed_at·completed_by)·submitted_at·열린 정정은 그대로 둔다 — 정정 재상신을
    취소하면 "작성완료 · 정정". 신호 없음(결재가 끝나지 않음).
    """
    with step("DOC-ULK-00", "DOC", "트랜잭션 확인"):
        _require_transaction()
    with step("DOC-ULK-01", "DOC", "상신 취소 되돌림(조건부 UPDATE)") as s:
        changed = Document.objects.filter(
            pk=document_id, deleted_at__isnull=True, status="submitted"
        ).update(status="completed", updated_at=timezone.now(), version=F("version") + 1)
        s.note(f"영향 행 {changed}")
    if changed == 0:
        _transition_failure(document_id, "DOC-ULK-01a")
    with step("DOC-ULK-02", "DOC", "결과"):
        return _lifecycle_result(document_id)


# ---------------------------------------------------------------- F12·F13 작성완료·작성 재개


def _clean_note(note):
    """작성완료 메모: 문자열, 앞뒤 공백 제거 후 0~200자, 빈 값은 없음(P6-VR-06)."""
    if note is None:
        return None
    if not isinstance(note, str):
        raise errors.ValidationFailed(
            details=[validation.error("note", "invalid", "문자열이어야 합니다.")]
        )
    text = note.strip()
    if len(text) > NOTE_MAX:
        raise errors.ValidationFailed(
            details=[validation.error("note", "too_long", f"{NOTE_MAX}자 이하여야 합니다.")]
        )
    return text or None


def complete_document(actor_id, document_id, expected_version, note=None):
    """작성완료: draft/rejected/correcting → completed. 잠근 뒤 검사하고, 실패하면 전체를 되돌린다.

    note(D-080): 저장하지 않고 생명주기 신호로만 넘긴다(육안검사 판정 변경 사유). 받는 쪽(EFF)이
    예외를 내면 작성완료도 롤백된다(P6-FR-17).
    """
    note = _clean_note(note)
    with roles.scope():
        require_write(actor_id, document_id)  # ROLE-R07(r13)
    now = timezone.now()
    with transaction.atomic():
        with step("DOC-CMP-02", "DOC", "작성완료(조건부 UPDATE)") as s:
            changed = Document.objects.filter(
                pk=document_id,
                deleted_at__isnull=True,
                status__in=COMPLETABLE,
                version=expected_version,
            ).update(
                status="completed",
                completed_at=now,
                completed_by_id=actor_id,
                updated_at=now,
                version=F("version") + 1,
            )
            s.note(f"영향 행 {changed}")
        if changed == 0:
            _lock_failure(
                document_id,
                "DOC-CMP-02a",
                expected_version=expected_version,
                allowed=COMPLETABLE,
                skipped_transition=True,
            )
        with step("DOC-CMP-03", "DOC", "작성완료 검사") as s:
            document = Document.objects.select_related("template").get(pk=document_id)
            rows = [
                (r.section_def, r.row_no, r.values_json)
                for r in DocSection.objects.filter(document_id=document_id)
            ]
            deviation_count = DeviationAction.objects.filter(
                document_id=document_id, deleted_at__isnull=True
            ).count()
            file_count = DocumentFile.objects.filter(document_id=document_id).count()
            problems = validation.completion_problems(
                document.template.schema_json,
                rows,
                deviation_count=deviation_count,
                file_count=file_count,
            )
            if problems:
                s.fail(f"빠진 항목 {len(problems)}건")
                raise errors.CompletionIncomplete(details=problems)
        _send_signal(document_id, "completed", actor_id, note, now)
    with step("DOC-CMP-04", "DOC", "결과 조회"):
        return _detail(document_id)


def reopen_document(actor_id, document_id, expected_version):
    """작성 재개: completed → draft, 열린 정정이 있으면 correcting(P6-FR-05).

    작성완료 기록을 지운다(P4-S2-Q7). 목적지는 UPDATE 안의 CASE(P6-NFR-01).
    """
    with roles.scope():
        require_write(actor_id, document_id)  # ROLE-R07(r13)
    now = timezone.now()
    with transaction.atomic():
        with step("DOC-ROP-02", "DOC", "작성 재개(조건부 UPDATE)") as s:
            changed = Document.objects.filter(
                pk=document_id,
                deleted_at__isnull=True,
                status__in=REOPENABLE,
                version=expected_version,
            ).update(
                status=Case(
                    When(Exists(_open_correction()), then=Value("correcting")),
                    default=Value("draft"),
                ),
                completed_at=None,
                completed_by_id=None,
                updated_at=now,
                version=F("version") + 1,
            )
            s.note(f"영향 행 {changed}")
        if changed == 0:
            with step("DOC-ROP-02a", "DOC", "실패 사유 확인"):
                row = (
                    Document.objects.filter(pk=document_id)
                    .values("status", "deleted_at", "version")
                    .first()
                )
                if row is None or row["deleted_at"] is not None:
                    raise errors.DocumentNotFound()
                if row["status"] not in REOPENABLE:
                    raise errors.InvalidTransition(
                        details=[
                            {
                                "path": "status",
                                "code": row["status"],
                                "message": f"현재 상태: {row['status']}",
                            }
                        ]
                    )
                raise errors.VersionConflict(
                    details=[
                        {
                            "path": "expected_version",
                            "code": "conflict",
                            "message": f"내가 연 버전 {expected_version}, 현재 {row['version']}",
                            "expected": expected_version,
                            "current": row["version"],
                        }
                    ]
                )
        _send_signal(document_id, "reopened", actor_id, at=now)
    with step("DOC-ROP-03", "DOC", "결과 조회"):
        return _detail(document_id)


# ---------------------------------------------------------------- F22·F24 정정 시작·정정 취소 (P6)


def _clean_reason(reason):
    """정정 사유: 문자열, 앞뒤 공백 제거 후 1~200자(P6-VR-02)."""
    text = reason.strip() if isinstance(reason, str) else ""
    if not text:
        message = "정정 사유를 입력하세요."
        code = "required"
    elif len(text) > CORRECTION_REASON_MAX:
        message = f"정정 사유는 {CORRECTION_REASON_MAX}자 이하여야 합니다."
        code = "too_long"
    else:
        return text
    raise errors.ValidationFailed(details=[validation.error("reason", code, message)])


def _correction_failure(document_id, step_id, expected_version, allowed):
    """조건부 쓰기가 0행일 때: 없음·삭제 404 → 상태 409 → 버전 409(P1 F07과 같은 순서)."""
    with step(step_id, "DOC", "실패 사유 확인"):
        row = (
            Document.objects.filter(pk=document_id)
            .values("status", "deleted_at", "version", "updated_at")
            .first()
        )
        if row is None or row["deleted_at"] is not None:
            raise errors.DocumentNotFound()
        if row["status"] not in allowed:
            raise errors.InvalidTransition(
                details=[
                    {
                        "path": "status",
                        "code": row["status"],
                        "message": f"현재 상태: {row['status']}",
                    }
                ]
            )
        if row["version"] != expected_version:
            raise errors.VersionConflict(
                details=[
                    {
                        "path": "expected_version",
                        "code": "conflict",
                        "message": f"내가 연 버전 {expected_version}, 현재 {row['version']}",
                        "expected": expected_version,
                        "current": row["version"],
                        "updated_at": _iso(row["updated_at"]),
                    }
                ]
            )
        return row


def start_correction(actor_id, document_id, expected_version, reason):
    """DOC-F22 정정 시작: approved → correcting, 정정 기록을 연다(T20, P6-FR-01~03).

    첫 SQL = 정정 기록 INSERT … SELECT(문서가 승인·버전 일치일 때만 1행). 정정 전 작성완료 기록을
    같은 문장에서 옮겨 적은 뒤 문서를 바꾼다 — 문서를 먼저 바꾸면 지운 작성완료 기록을 남길 곳이
    없다(P6-S4a G1). 회차는 읽지도 쓰지도 않는다.
    """
    with step("DOC-COR-01b", "DOC", "양식 유형"):
        type_code = document_type(document_id)
    with step("DOC-COR-01c", "DOC", "설정 상태·권한(ROLE-R04)") as s:
        try:
            roles.require_owner_or_leader(actor_id, type_code)
        except ApiError as error:
            s.fail(error.code)
            raise
    with step("DOC-COR-02", "DOC", "사유 검사"):
        text = _clean_reason(reason)
    now = timezone.now()
    with transaction.atomic():
        with step("DOC-COR-03", "DOC", "정정 기록 열기(조건부 INSERT … SELECT)") as s:
            with connection_cursor() as cursor:
                try:
                    cursor.execute(
                        "INSERT INTO document_correction (document_id, started_at, started_by,"
                        " reason, start_version, prev_completed_at, prev_completed_by)"
                        " SELECT document_id, %s, %s, %s, version + 1, completed_at, completed_by"
                        " FROM document WHERE document_id = %s AND deleted_at IS NULL"
                        " AND status = 'approved' AND version = %s",
                        [_db_datetime(now), actor_id, text, document_id, expected_version],
                    )
                except IntegrityError as error:
                    # 열린 정정이 이미 있는 승인 문서 = 어긋난 데이터 — 방어선(P6-NFR-05)
                    s.fail("열린 정정 중복")
                    raise errors.InvalidTransition() from error
                opened = cursor.rowcount
            s.note(f"영향 행 {opened}")
        if opened == 0:
            _correction_failure(document_id, "DOC-COR-03a", expected_version, CORRECTABLE)
        with step("DOC-COR-04", "DOC", "문서 정정 중(UPDATE)") as s:
            changed = Document.objects.filter(
                pk=document_id, status="approved", version=expected_version
            ).update(
                status="correcting",
                completed_at=None,
                completed_by_id=None,
                updated_at=now,
                version=F("version") + 1,
            )
            s.note(f"영향 행 {changed}")
        _send_signal(document_id, "correction_started", actor_id, at=now)
    with step("DOC-COR-05", "DOC", "결과 조회"):
        return _detail(document_id)


def cancel_correction(actor_id, document_id, expected_version):
    """DOC-F24 정정 취소: correcting → approved, 정정 시작 뒤 수정하지 않았을 때만(T30, D-075).

    작성완료 기록을 정정 전 값으로 되돌리고 정정 기록을 cancelled로 닫는다. 회차 변화 없음.
    """
    with roles.scope():
        require_write(actor_id, document_id)  # ROLE-R07(r13)
    now = timezone.now()
    current = _open_correction()
    with transaction.atomic():
        with step("DOC-CCN-02", "DOC", "정정 취소(조건부 UPDATE)") as s:
            changed = (
                Document.objects.filter(
                    pk=document_id,
                    deleted_at__isnull=True,
                    status="correcting",
                    version=expected_version,
                )
                .filter(Exists(_open_correction(start_version=expected_version)))
                .update(
                    status="approved",
                    completed_at=Subquery(current.values("prev_completed_at")[:1]),
                    completed_by_id=Subquery(current.values("prev_completed_by")[:1]),
                    updated_at=now,
                    version=F("version") + 1,
                )
            )
            s.note(f"영향 행 {changed}")
        if changed == 0:
            _correction_failure(document_id, "DOC-CCN-02a", expected_version, ("correcting",))
            with step("DOC-CCN-02b", "DOC", "시작 뒤 수정함"):
                raise errors.CorrectionHasChanges()
        with step("DOC-CCN-03", "DOC", "정정 기록 닫기(cancelled)") as s:
            closed = DocumentCorrection.objects.filter(
                document_id=document_id, closed_at__isnull=True
            ).update(closed_at=now, outcome="cancelled")
            s.note(f"영향 행 {closed}")
        _send_signal(document_id, "correction_cancelled", actor_id, at=now)
    with step("DOC-CCN-04", "DOC", "결과 조회"):
        return _detail(document_id)


# ---------------------------------------------------------------- F19~F21 개선조치


DEVIATION_FIELDS = ("section_id", "description", "action_result", "actor_id", "checker_ids")


def _clean_deviation(data, *, partial):
    """형식 검사(DB 없이, DVC-01·DVU-01). 반환: (정리된 값, 오류)."""
    cleaned, problems = {}, []
    if not isinstance(data, dict):
        return cleaned, [validation.error("deviation", "invalid", "객체여야 합니다.")]
    for key in data:
        if key not in DEVIATION_FIELDS:
            problems.append(validation.error(key, "unknown_field", "알 수 없는 항목입니다."))
    if "description" in data or not partial:
        value = data.get("description")
        value = value.strip() if isinstance(value, str) else value
        if not isinstance(value, str) or not value:
            problems.append(
                validation.error("description", "required", "한계기준 이탈내용을 입력하세요.")
            )
        elif len(value) > 500:
            problems.append(validation.error("description", "max_length", "500자 이하입니다."))
        else:
            cleaned["description"] = value
    if "action_result" in data:
        value = data["action_result"]
        value = value.strip() if isinstance(value, str) else value
        if value not in (None, "") and not isinstance(value, str):
            problems.append(validation.error("action_result", "invalid", "문자여야 합니다."))
        elif isinstance(value, str) and len(value) > 1000:
            problems.append(validation.error("action_result", "max_length", "1000자 이하입니다."))
        else:
            cleaned["action_result"] = value or None
    for key in ("section_id", "actor_id"):
        if key in data:
            value = data[key]
            if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
                problems.append(validation.error(key, "invalid", "정수여야 합니다."))
            else:
                cleaned[key] = value
    if "checker_ids" in data:
        value = data["checker_ids"]
        if not isinstance(value, list) or any(
            isinstance(v, bool) or not isinstance(v, int) for v in value
        ):
            problems.append(
                validation.error("checker_ids", "invalid", "staff id 목록이어야 합니다.")
            )
        elif len(set(value)) != len(value):
            problems.append(validation.error("checker_ids", "duplicate", "확인자가 중복됩니다."))
        elif len(value) > DEVIATION_MAX_CHECKERS:
            problems.append(
                validation.error(
                    "checker_ids", "max_items", f"확인자는 {DEVIATION_MAX_CHECKERS}명까지입니다."
                )
            )
        else:
            cleaned["checker_ids"] = value
    return cleaned, problems


def _check_deviation_refs(document_id, cleaned):
    """staff·관련 행 확인(DVC-03·DVU-03). 실패하면 ValidationFailed."""
    problems = []
    pairs = [("actor_id", cleaned["actor_id"])] if cleaned.get("actor_id") is not None else []
    pairs += [(f"checker_ids[{i}]", sid) for i, sid in enumerate(cleaned.get("checker_ids", []))]
    _check_staff(pairs, problems)
    section_id = cleaned.get("section_id")
    if (
        section_id is not None
        and not DocSection.objects.filter(pk=section_id, document_id=document_id).exists()
    ):
        problems.append(validation.error("section_id", "not_found", "이 문서의 행이 아닙니다."))
    if problems:
        raise errors.ValidationFailed(details=problems)


def _deviation_detail(deviation_id):
    deviation = DeviationAction.objects.get(pk=deviation_id)
    checkers = list(
        DeviationChecker.objects.filter(deviation_id=deviation_id)
        .order_by("staff_id")
        .values_list("staff_id", flat=True)
    )
    return _deviation_row(deviation, checkers)


@roles.scope()
def create_deviation(actor_id, document_id, data):
    """개선조치 쓰기(F19). 문서 상태와 무관하다(D-054). 문서 버전은 바뀌지 않는다.

    P14(ROLE-FR-12): checker_ids 키가 없으면 확인자 기본값 = 그 양식 담당자 + HACCP팀장(담당자
    먼저, 각각 id 순, 10명까지 — 넘치면 checker_default_truncated). 빈 목록을 보내면 비운다.
    기본값이 0명이면 저장하고 checker_warning(config_invalid·no_holders — r14 D-202 Q5 a).
    권한: ROLE-R07(r13) — 404 → 403 순서라 문서 확인이 INSERT보다 먼저다.
    """
    with step("DOC-DVC-01", "DOC", "형식 검사") as s:
        cleaned, problems = _clean_deviation(data, partial=False)
        if problems:
            s.fail(f"오류 {len(problems)}건")
            raise errors.ValidationFailed(details=problems)
    type_code = require_write(actor_id, document_id)[0]  # ROLE-R07(r13)
    truncated, warning = False, None
    with step("DOC-DVC-01b", "DOC", "확인자 기본값(담당자 + HACCP팀장)") as s:
        if "checker_ids" in data:
            s.skip("checker_ids 보냄")
        else:
            wanted = sorted(roles.owners(type_code))
            wanted += [sid for sid in sorted(roles.leaders()) if sid not in wanted]
            truncated = len(wanted) > DEVIATION_MAX_CHECKERS
            cleaned["checker_ids"] = wanted[:DEVIATION_MAX_CHECKERS]
            s.note(f"{len(cleaned['checker_ids'])}명" + (" (10명까지만)" if truncated else ""))
    with step("DOC-DVC-01c", "DOC", "확인자 0명 경고(r14)") as s:
        if "checker_ids" in data:
            s.skip("checker_ids 보냄")
        elif cleaned["checker_ids"]:
            s.skip("확인자 있음")
        else:
            warning = "config_invalid" if roles.config_error() else "no_holders"
            s.note(warning)  # 저장은 계속한다(작성을 막지 않음 — ROLE-C07과 같은 원칙)
    now = timezone.now()
    with transaction.atomic():
        with step("DOC-DVC-02", "DOC", "개선조치 저장(INSERT … WHERE 문서 있음)") as s:
            # 첫 SQL을 쓰기로: 문서가 있고 삭제되지 않았을 때만 INSERT한다.
            with connection_cursor() as cursor:
                cursor.execute(
                    "INSERT INTO deviation_action (document_id, section_id, description, "
                    "action_result, actor_id, created_by, created_at, updated_by, updated_at, "
                    "version) SELECT %s, %s, %s, %s, %s, %s, %s, %s, %s, 1 WHERE EXISTS "
                    "(SELECT 1 FROM document WHERE document_id = %s AND deleted_at IS NULL)",
                    [
                        document_id,
                        cleaned.get("section_id"),
                        cleaned["description"],
                        cleaned.get("action_result"),
                        cleaned.get("actor_id"),
                        actor_id,
                        _db_datetime(now),
                        actor_id,
                        _db_datetime(now),
                        document_id,
                    ],
                )
                inserted, deviation_id = cursor.rowcount, cursor.lastrowid
            s.note(f"영향 행 {inserted}")
            if inserted == 0:
                raise errors.DocumentNotFound()
        with step("DOC-DVC-03", "DOC", "staff·관련 행 확인"):
            _check_deviation_refs(document_id, cleaned)
        with step("DOC-DVC-04", "DOC", "확인자 저장"):
            DeviationChecker.objects.bulk_create(
                DeviationChecker(deviation_id=deviation_id, staff_id=sid)
                for sid in cleaned.get("checker_ids", [])
            )
    detail = _deviation_detail(deviation_id)
    if truncated:
        detail["checker_default_truncated"] = True
    if warning:
        detail["checker_warning"] = warning
    return detail


def _deviation_failure(deviation_id, expected_version, step_id):
    with step(step_id, "DOC", "실패 사유 확인"):
        row = (
            DeviationAction.objects.filter(pk=deviation_id)
            .values("deleted_at", "version", "document__deleted_at")
            .first()
        )
        if row is None or row["deleted_at"] is not None or row["document__deleted_at"] is not None:
            raise errors.DeviationNotFound()
        raise errors.VersionConflict(
            details=[
                {
                    "path": "expected_version",
                    "code": "conflict",
                    "message": f"내가 연 버전 {expected_version}, 현재 {row['version']}",
                    "expected": expected_version,
                    "current": row["version"],
                }
            ]
        )


def _live_deviation(deviation_id, expected_version):
    alive_document = Document.objects.filter(pk=OuterRef("document_id"), deleted_at__isnull=True)
    return DeviationAction.objects.filter(
        Q(pk=deviation_id, deleted_at__isnull=True, version=expected_version),
        Exists(alive_document),
    )


@roles.scope()
def update_deviation(actor_id, deviation_id, expected_version, patch):
    """개선조치 수정(F20). 문서를 잠그지 않고 개선조치 자기 version으로 충돌을 감지한다.

    권한: ROLE-R07(r13) 또는 그 개선조치의 지정 확인자(r14 D-202 Q6 b — 수정만).
    """
    with step("DOC-DVU-01", "DOC", "형식 검사") as s:
        cleaned, problems = _clean_deviation(patch, partial=True)
        if not cleaned and not problems:
            problems = [validation.error("deviation", "no_changes", "바꿀 내용이 없습니다.")]
        if problems:
            s.fail(f"오류 {len(problems)}건")
            raise errors.ValidationFailed(details=problems)
    _require_deviation_write(actor_id, deviation_id, allow_checker=True)
    now = timezone.now()
    fields = {k: v for k, v in cleaned.items() if k != "checker_ids"}
    with transaction.atomic():
        with step("DOC-DVU-02", "DOC", "개선조치 수정(조건부 UPDATE)") as s:
            changed = _live_deviation(deviation_id, expected_version).update(
                **fields, updated_by_id=actor_id, updated_at=now, version=F("version") + 1
            )
            s.note(f"영향 행 {changed}")
        if changed == 0:
            _deviation_failure(deviation_id, expected_version, "DOC-DVU-02a")
        with step("DOC-DVU-03", "DOC", "staff·관련 행 확인"):
            document_id = DeviationAction.objects.values_list("document_id", flat=True).get(
                pk=deviation_id
            )
            _check_deviation_refs(document_id, cleaned)
        with step("DOC-DVU-04", "DOC", "확인자 교체") as s:
            if "checker_ids" in cleaned:
                DeviationChecker.objects.filter(deviation_id=deviation_id).delete()
                DeviationChecker.objects.bulk_create(
                    DeviationChecker(deviation_id=deviation_id, staff_id=sid)
                    for sid in cleaned["checker_ids"]
                )
            else:
                s.skip("확인자 변경 없음")
    return _deviation_detail(deviation_id)


@roles.scope()
def delete_deviation(actor_id, deviation_id, expected_version):
    """개선조치 삭제(논리, F21). 권한: ROLE-R07(r13 — 지정 확인자 예외 없음)."""
    _require_deviation_write(actor_id, deviation_id)
    now = timezone.now()
    with transaction.atomic():
        with step("DOC-DVD-02", "DOC", "삭제 표시(조건부 UPDATE)") as s:
            changed = _live_deviation(deviation_id, expected_version).update(
                deleted_at=now,
                deleted_by_id=actor_id,
                updated_by_id=actor_id,
                updated_at=now,
                version=F("version") + 1,
            )
            s.note(f"영향 행 {changed}")
        if changed == 0:
            _deviation_failure(deviation_id, expected_version, "DOC-DVD-02a")
    return None


# ---------------------------------------------------------------- N1~N3 작성 요구용 (REQ 전용)


def _clean_refs(refs, path="refs"):
    """refs 형식 검사(DB 없이). 반환: (정리된 목록, 오류)."""
    cleaned, problems = [], []
    if not isinstance(refs, list):
        return [], [validation.error(path, "invalid", "목록이어야 합니다.")]
    for i, ref in enumerate(refs):
        where = f"{path}[{i}]"
        if not isinstance(ref, dict):
            problems.append(validation.error(where, "invalid", "객체여야 합니다."))
            continue
        item = {}
        for key in ("lot_id", "production_batch_id", "item_id"):
            value = ref.get(key)
            if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
                problems.append(validation.error(f"{where}.{key}", "invalid", "정수여야 합니다."))
            item[key] = value
        for key, limit in (("process_code", 20), ("label", 100)):
            value = ref.get(key)
            if value is not None and (not isinstance(value, str) or len(value) > limit):
                problems.append(
                    validation.error(f"{where}.{key}", "invalid", f"{limit}자 이하 문자입니다.")
                )
            item[key] = value
        if all(item[key] is None for key in REF_TARGETS):
            problems.append(validation.error(where, "no_target", "대상이 하나 이상 필요합니다."))
        cleaned.append(item)
    return cleaned, problems


def _insert_refs(document_id, section_id, refs, now, path="refs"):
    """document_ref INSERT. FK 위반(없는 LOT 등)은 ValidationFailed로 바꾼다."""
    for i, ref in enumerate(refs):
        try:
            with transaction.atomic():
                DocumentRef.objects.create(
                    document_id=document_id, section_id=section_id, created_at=now, **ref
                )
        except IntegrityError as error:
            raise errors.ValidationFailed(
                details=[
                    validation.error(
                        f"{path}[{i}]", "not_found", f"참조 대상을 확인하세요: {error}"
                    )
                ]
            ) from error


def get_or_create_document(
    actor_id, template_code, record_key, work_date, refs, values=None, assignee_id=None
):
    """N1: record_key로 찾고 없으면 빈 작성중 문서를 만든다(DOC-GOC). 호출자 트랜잭션 안에서만."""
    with step("DOC-GOC-00", "DOC", "트랜잭션·입력 형식 확인") as s:
        _require_transaction()
        problems = []
        if not isinstance(record_key, str) or not record_key or len(record_key) > 200:
            problems.append(validation.error("record_key", "invalid", "1~200자 문자입니다."))
        parsed_date = validation.parse_work_date(
            work_date if isinstance(work_date, str) else _iso(work_date)
        )
        if parsed_date is None:
            problems.append(validation.error("work_date", "invalid", "YYYY-MM-DD 형식입니다."))
        clean_refs, ref_problems = _clean_refs(refs)
        problems += ref_problems
        values = values or {}
        if not isinstance(values, dict):
            problems.append(validation.error("values", "invalid", "섹션별 객체여야 합니다."))
        if problems:
            s.fail(f"오류 {len(problems)}건")
            raise errors.ValidationFailed(details=problems)
    now = timezone.now()
    with step("DOC-GOC-01", "DOC", "INSERT … ON CONFLICT(record_key) DO NOTHING") as s:
        with connection_cursor() as cursor:
            cursor.execute(
                "INSERT INTO document (template_id, work_date, record_key, created_by, "
                "assignee_id, status, created_at, updated_at, version) "
                "SELECT t.template_id, %s, %s, %s, %s, 'draft', %s, %s, 1 "
                "FROM document_template t WHERE t.type_code = %s AND t.is_active = 1 "
                "ORDER BY t.version DESC LIMIT 1 "
                "ON CONFLICT (record_key) WHERE record_key IS NOT NULL DO NOTHING",
                [
                    _db_date(parsed_date),
                    record_key,
                    actor_id,
                    assignee_id,
                    _db_datetime(now),
                    _db_datetime(now),
                    template_code,
                ],
            )
            inserted, document_id = cursor.rowcount, cursor.lastrowid
        s.note(f"영향 행 {inserted}")
    if inserted == 0:
        with step("DOC-GOC-01a", "DOC", "기존 문서 또는 양식 확인"):
            existing = (
                Document.objects.select_related("template").filter(record_key=record_key).first()
            )
            if existing is not None:
                return {"document": _full(existing), "created": False}
            if not DocumentTemplate.objects.filter(type_code=template_code).exists():
                raise errors.TemplateNotFound()
            raise errors.TemplateInactive()
    with step("DOC-GOC-02", "DOC", "초기값 검증") as s:
        document = Document.objects.select_related("template").get(pk=document_id)
        schema_sections = validation.sections_of(document.template.schema_json)
        problems, staff_pairs = [], []
        if assignee_id is not None:
            staff_pairs.append(("assignee_id", assignee_id))
        for key in values:
            section = schema_sections.get(key)
            if section is None or section["repeat"]:
                problems.append(
                    validation.error(f"values.{key}", "unknown_section", "1행 영역이 아닙니다.")
                )
                continue
            row_errors, _ = validation.check_values(section, values[key], f"values.{key}")
            problems += row_errors
            problems += validation.context_errors(
                section, values[key], f"values.{key}", document.work_date
            )
            staff_pairs += validation.staff_field_paths(section, values[key], f"values.{key}")
        _check_staff(staff_pairs, problems)
        if problems:
            s.fail(f"오류 {len(problems)}건")
            raise errors.ValidationFailed(details=problems)
    with step("DOC-GOC-03", "DOC", "1행 영역 행 만들기(P8: na_default·initial, 호출자 값 우선)"):
        DocSection.objects.bulk_create(
            DocSection(
                document_id=document_id,
                section_def=key,
                row_no=1,
                values_json=validation.with_computed(
                    section,
                    {
                        **validation.initial_values(section, document.work_date),
                        **(values.get(key) or {}),
                    },
                ),
                recorded_at=now,
                recorded_by_id=actor_id,
            )
            for key, section in schema_sections.items()
            if not section["repeat"]
        )
    with step("DOC-GOC-04", "DOC", "업무 대상 참조"):
        _insert_refs(document_id, None, clean_refs, now)
    with step("DOC-GOC-05", "DOC", "결과"):
        return {"document": _full(document), "created": True}


def add_ref_row(actor_id, document_id, section_def, values, refs, dedupe_on):
    """N2: 작성 요구 행 추가(DOC-ARR). 같은 대상 행이 있으면 추가하지 않는다.

    호출자 트랜잭션 안에서만 쓴다.
    """
    with step("DOC-ARR-00", "DOC", "트랜잭션·입력 형식 확인") as s:
        _require_transaction()
        clean_refs, problems = _clean_refs(refs)
        if dedupe_on not in REF_TARGETS:
            problems.append(
                validation.error("dedupe_on", "invalid", "대상 컬럼 이름이어야 합니다.")
            )
        elif not any(r.get(dedupe_on) is not None for r in clean_refs):
            problems.append(validation.error("refs", "invalid", f"{dedupe_on} 참조가 필요합니다."))
        if not isinstance(values, dict):
            problems.append(validation.error("values", "invalid", "객체여야 합니다."))
        if problems:
            s.fail(f"오류 {len(problems)}건")
            raise errors.ValidationFailed(details=problems)
    dedupe_value = next(r[dedupe_on] for r in clean_refs if r.get(dedupe_on) is not None)

    def existing_section():
        return (
            DocumentRef.objects.filter(
                document_id=document_id, section_id__isnull=False, **{dedupe_on: dedupe_value}
            )
            .values_list("section_id", flat=True)
            .first()
        )

    with step("DOC-ARR-01", "DOC", "잠금용 UPDATE(값·버전 변화 없음)") as s:
        locked = Document.objects.filter(
            pk=document_id, deleted_at__isnull=True, status__in=ROW_APPENDABLE
        ).update(updated_at=F("updated_at"))
        s.note(f"영향 행 {locked}")
    if locked == 0:
        with step("DOC-ARR-01a", "DOC", "판정: 문서 없음 → 기존 행 → 잠김"):
            row = Document.objects.filter(pk=document_id).values("deleted_at", "status").first()
            if row is None or row["deleted_at"] is not None:
                raise errors.DocumentNotFound()
            found = existing_section()
            if found is not None:
                return {"section_id": found, "created": False}
            raise errors.DocumentLocked(
                details=[{"path": "status", "code": row["status"], "message": row["status"]}]
            )
    with step("DOC-ARR-02", "DOC", "같은 대상 행 확인"):
        found = existing_section()
        if found is not None:
            return {"section_id": found, "created": False}
    with step("DOC-ARR-03", "DOC", "양식·행 번호 읽기") as s:
        document = Document.objects.select_related("template").get(pk=document_id)
        section = validation.sections_of(document.template.schema_json).get(section_def)
        if section is None or not section["repeat"]:
            s.fail("반복 영역 아님")
            raise errors.ValidationFailed(
                details=[
                    validation.error("section_def", "unknown_section", "반복 영역이 아닙니다.")
                ]
            )
        last = (
            DocSection.objects.filter(document_id=document_id, section_def=section_def)
            .order_by("-row_no")
            .values_list("row_no", flat=True)
            .first()
            or 0
        )
    with step("DOC-ARR-04", "DOC", "값 검증(형식, 시스템 값 허용)") as s:
        row_errors, _ = validation.check_values(section, values, "values")
        if row_errors:
            s.fail(f"오류 {len(row_errors)}건")
            raise errors.ValidationFailed(details=row_errors)
    with step("DOC-ARR-05", "DOC", "판정 계산"):
        values = validation.with_computed(section, values)
    now = timezone.now()
    with step("DOC-ARR-06", "DOC", "행·참조 INSERT, version+1"):
        row = DocSection.objects.create(
            document_id=document_id,
            section_def=section_def,
            row_no=last + 1,
            values_json=values,
            recorded_at=now,
            recorded_by_id=actor_id,
        )
        _insert_refs(document_id, row.section_id, clean_refs, now)
        Document.objects.filter(pk=document_id).update(updated_at=now, version=F("version") + 1)
    return {"section_id": row.section_id, "created": True}


def find_documents_by_ref(lot_id=None, production_batch_id=None, process_code=None, item_id=None):
    """N3: 업무 대상으로 문서 찾기(삭제 제외). 문서 단위·행 단위 모두."""
    with step("DOC-FND-01", "DOC", "참조로 문서 찾기"):
        filters = {}
        if lot_id is not None:
            filters["lot_id"] = lot_id
        if production_batch_id is not None:
            filters["production_batch_id"] = production_batch_id
            if process_code is not None:
                filters["process_code"] = process_code
        if item_id is not None:
            filters["item_id"] = item_id
        if not filters:
            raise errors.ValidationFailed(
                details=[validation.error("ref", "required", "찾을 대상이 필요합니다.")]
            )
        refs = list(DocumentRef.objects.filter(**filters).order_by("document_id", "ref_id"))
        documents = {
            d.document_id: d
            for d in Document.objects.select_related("template")
            .filter(pk__in={r.document_id for r in refs}, deleted_at__isnull=True)
            .annotate(correction_reason=Subquery(_open_correction().values("reason")[:1]))
        }
        return [
            {
                "document_id": r.document_id,
                "type_code": documents[r.document_id].template.type_code,
                "status": documents[r.document_id].status,
                "version": documents[r.document_id].version,
                "section_id": r.section_id,
                # P6-FR-14: 열린 정정 여부와 사유(REQ F03 correcting·correction_reason)
                "correcting": documents[r.document_id].correction_reason is not None,
                "correction_reason": documents[r.document_id].correction_reason,
            }
            for r in refs
            if r.document_id in documents
        ]


# ---------------------------------------------------------------- P7 (p7-s2-spec 3.2)


def _one_row_sections(schema):
    return [section for section in schema["sections"] if not section.get("repeat")]


def _verdict_section(schema):
    """1행 섹션 중 필드 verdict가 있는 첫 섹션(D03은 inspection). 없으면 None."""
    for section in _one_row_sections(schema):
        if any(f["key"] == "verdict" for f in section["fields"]):
            return section
    return None


def _verdict_of(schema, values_by_key):
    """1행 섹션 중 필드 verdict가 있는 첫 섹션의 값과 부적합 여부.

    판정 필드가 없으면 판정은 None, 부적합 여부는 1행 섹션의 nonconforming 규칙으로 계산한다
    (P8 S4 Q3 b — 점검표: X 있음 True, 다 채움 False, X 없이 빈칸 None). 규칙도 없으면 None.
    """
    for section in _one_row_sections(schema):
        if any(f["key"] == "verdict" for f in section["fields"]):
            values = values_by_key.get(section["key"]) or {}
            return values.get("verdict"), validation.is_nonconforming(section, values)
    results = [
        validation.evaluate(section["nonconforming"], values_by_key.get(section["key"]) or {})
        for section in _one_row_sections(schema)
        if section.get("nonconforming")
    ]
    if not results:
        return None, None
    if any(r is True for r in results):
        return None, True
    return None, None if any(r is None for r in results) else False


def document_type(document_id):
    """P14: 문서의 양식 유형(type_code) — 역할 판단용. SQL 1.

    쓰는 곳: WF 상신 WF-SUB-02b, DOC 정정 시작 DOC-COR-01b.

    없거나 삭제된 문서면 404 DOCUMENT_NOT_FOUND.
    """
    type_code = (
        Document.objects.filter(pk=document_id, deleted_at__isnull=True)
        .values_list("template__type_code", flat=True)
        .first()
    )
    if type_code is None:
        raise errors.DocumentNotFound()
    return type_code


SUBMITTABLE = LOCKABLE  # 상신 가능한 문서 상태(작성완료)


# ---------------------------------------------------------------- P14 r13 작성 권한(ROLE-R07·R08)
# 흐름 p14-s2-flows.md 3.13 DOC-WRT. 쓰기마다 "요청 형식" 뒤, 상태·버전 검사(트랜잭션) 앞에서
# 판단한다(404 → 403 → 409). 작성 요구 진입점·주기 만들기(get_or_create_document)는
# 거치지 않는다(R06).

_TARGET_SQL = (
    "SELECT d.document_id, t.type_code, json_extract(s.values_json, '$.inspector'), s.section_id"
    " FROM document d JOIN document_template t ON t.template_id = d.template_id"
    " LEFT JOIN doc_section s ON s.document_id = d.document_id AND s.section_def = 'info'"
)


def _write_targets(document_ids):
    """DOC-WRT-01 몸통: {document_id: (type_code, inspector_id, info_section_id)}. SQL 1.

    없거나 삭제된 문서는 빠진다(호출자가 404로).
    """
    ids = [i for i in document_ids if isinstance(i, int) and not isinstance(i, bool)]
    if not ids:
        return {}
    marks = ", ".join(["%s"] * len(ids))
    with connection_cursor() as cursor:
        cursor.execute(
            _TARGET_SQL + f" WHERE d.deleted_at IS NULL AND d.document_id IN ({marks})", ids
        )
        return {row[0]: (row[1], row[2], row[3]) for row in cursor.fetchall()}


def _check_write(actor_id, target, deviation_id=None):
    """DOC-WRT-02(·02b): ROLE-R07. 아니면 403 ROLE_REQUIRED. 반환: 통과한 역할 이름.

    deviation_id(개선조치 수정만 — r14 D-202 Q6 b): 역할·점검자가 아니어도 그 개선조치의 지정
    확인자면 통과.
    """
    type_code, inspector_id, _ = target
    with step("DOC-WRT-02", "DOC", "설정 상태 → 권한(ROLE-R07)") as s:
        role = roles.write_role(actor_id, type_code, inspector_id)
        if role is not None:
            s.note(f"{type_code}: {role}")
            return role
        if deviation_id is None:
            raise roles.RoleRequired(roles.WRITE_REQUIRED, roles.WRITE_MESSAGE)
        s.skip("역할·점검자 아님 → 지정 확인자 확인(02b)")
    with step("DOC-WRT-02b", "DOC", "개선조치 지정 확인자(r14)") as s:
        if DeviationChecker.objects.filter(deviation_id=deviation_id, staff_id=actor_id).exists():
            s.note("checker")
            return "checker"
        raise roles.RoleRequired(roles.WRITE_REQUIRED + ("checker",), roles.WRITE_MESSAGE)


def require_write(actor_id, document_id):
    """DOC-WRT-01·02: 문서 쓰기 권한(ROLE-R07). 없거나 삭제된 문서면 404. 반환: target."""
    with step("DOC-WRT-01", "DOC", "양식 유형·점검자") as s:
        target = _write_targets([document_id]).get(document_id)
        if target is None:
            raise errors.DocumentNotFound()
        s.note(f"{target[0]}, 점검자 {target[1]}")
    _check_write(actor_id, target)
    return target


def _require_deviation_write(actor_id, deviation_id, allow_checker=False):
    """DOC-WRT-01·02(·02b): 개선조치 수정·삭제 — 없거나 삭제된 개선조치·문서면 404."""
    with step("DOC-WRT-01", "DOC", "양식 유형·점검자(개선조치의 문서)") as s:
        with connection_cursor() as cursor:
            cursor.execute(
                _TARGET_SQL + " JOIN deviation_action a ON a.document_id = d.document_id"
                " WHERE a.deviation_id = %s AND a.deleted_at IS NULL AND d.deleted_at IS NULL",
                [deviation_id],
            )
            row = cursor.fetchone()
        if row is None:
            raise errors.DeviationNotFound()
        target = (row[1], row[2], row[3])
        s.note(f"{target[0]}, 점검자 {target[1]}")
    _check_write(actor_id, target, deviation_id if allow_checker else None)


def _inspector_changed(updates, target):
    """수정 본문이 info.inspector 값을 바꾸는가(같은 값이면 R08 안 봄 — ROLE-TC-45)."""
    _, current, info_section_id = target
    for item in updates:
        if not isinstance(item, dict) or item.get("section_id") != info_section_id:
            continue
        values = item.get("values")
        if isinstance(values, dict) and "inspector" in values and values["inspector"] != current:
            return True
    return False


def _require_inspector_setter(actor_id, type_code):
    """DOC-WRT-03: ROLE-R08(점검자 지정) — 설정 오류 409, 아니면 403."""
    with step("DOC-WRT-03", "DOC", "점검자 바뀜 → 권한(ROLE-R08)") as s:
        roles.require_inspector_setter(actor_id, type_code)
        s.note(type_code)


CORRECTABLE = ("approved",)


@roles.scope()
def document_roles(document, actor_id=None):
    """P14 문서 상세에 더하는 값(ROLE-FR-11, p14-s2-flows.md 3.8 DOC-GET-04·05). 저장 안 함.

    document = get_document() 결과. 반환 {owner_ids, approval_line, permissions}.
    permissions는 현재 사용자 기준(없으면 모두 False). 상신 취소 권한은 회차 정보가 필요해 APR
    회차 상세의 can_cancel로 준다(DOC는 APR을 읽지 않음).
    """
    type_code = document["template"]["type_code"]
    with step("DOC-GET-04", "DOC", "양식 담당자·결재선 미리 보기"):
        owner_ids = sorted(roles.owners(type_code))
        line = roles.approval_line(type_code)
    with step("DOC-GET-05", "DOC", "권한(현재 사용자)") as s:
        usable = actor_id is not None and roles.config_error() is None
        may_submit = usable and roles.can_submit(actor_id, type_code)  # R01 + 작성 권한자(D-198)
        may_correct = usable and (roles.is_owner(actor_id, type_code) or roles.is_leader(actor_id))
        info = next((r["values"] for r in document["sections"] if r["section_def"] == "info"), {})
        permissions = {
            "submit": may_submit and line["ok"] and document["status"] in SUBMITTABLE,
            "start_correction": may_correct and document["status"] in CORRECTABLE,  # R04
            # r13: 역할로 쓸 수 있나(상태 무관 — 버튼별 상태는 화면이). 설정 오류면 true(C07)
            "write": roles.can_write(actor_id, type_code, (info or {}).get("inspector")),
            "assign_inspector": type_code in INSPECTOR_TYPES
            and roles.can_assign_inspector(actor_id, type_code),  # R08
        }
        s.note(str(permissions))
    return {"owner_ids": owner_ids, "approval_line": line, "permissions": permissions}


def brief_documents(document_ids):
    """F26: 문서 요약 여러 건(≤50). SQL 3(문서·양식, 1행 섹션, 문서 단위 참조)
    + D-234 성적서 유무 계산 1(hint 필드가 있는 양식이 있을 때만).

    빈 목록이면 SQL 없음.
    반환 {items: [...입력 순서], missing: [없거나 삭제된 id]}.
    """
    with step("DOC-BRF-01", "DOC", "입력 확인"):
        if not isinstance(document_ids, (list, tuple)) or any(
            not isinstance(i, int) or isinstance(i, bool) or i < 1 for i in document_ids
        ):
            raise errors.InvalidFilter(
                details=[validation.error("ids", "invalid", "1 이상의 정수 목록이어야 합니다.")]
            )
        ids = list(dict.fromkeys(document_ids))
        if len(ids) > BRIEF_MAX:
            raise errors.InvalidFilter(
                details=[validation.error("ids", "max", f"최대 {BRIEF_MAX}건입니다.")]
            )
    if not ids:
        return {"items": [], "missing": []}
    with step("DOC-BRF-02", "DOC", "문서·양식"):
        documents = {
            d.document_id: d
            for d in Document.objects.select_related("template")
            .filter(pk__in=ids, deleted_at__isnull=True)
            .annotate(correcting=Exists(_open_correction()))
        }
    found = [i for i in ids if i in documents]
    with step("DOC-BRF-03", "DOC", "1행 섹션·문서 단위 참조") as s:
        values, refs, rows = {}, {i: [] for i in found}, {i: [] for i in found}
        if found:
            keys = {
                section["key"]
                for d in documents.values()
                for section in _one_row_sections(d.template.schema_json)
            }
            for document_id, key, row, section_id in DocSection.objects.filter(
                document_id__in=found, section_def__in=sorted(keys)
            ).values_list("document_id", "section_def", "values_json", "section_id"):
                values.setdefault(document_id, {})[key] = row or {}
                rows[document_id].append(_BriefRow(key, section_id))
            for ref in DocumentRef.objects.filter(
                document_id__in=found, section_id__isnull=True
            ).order_by("ref_id"):
                refs[ref.document_id].append(_ref_row(ref))
            # D-234 R3: 성적서 유무 실제 값(저장 값 없으면 계산) — 문서 단위 LOT만(1행 섹션)
            hints = _hints_many([(documents[i], rows[i], refs[i]) for i in found])
        else:
            s.skip("문서 없음")
    with step("DOC-BRF-04", "DOC", "조립"):
        items = []
        for document_id in found:
            d = documents[document_id]
            own = values.get(document_id, {})
            info = own.get("info") or {}
            verdict, nonconforming = _verdict_of(d.template.schema_json, own)
            counts = validation.check_counts(d.template.schema_json, own)  # P8 F26 변경
            judged = _verdict_section(d.template.schema_json)
            shown, derived = None, []
            if judged is not None:
                row_id = next(
                    (r.section_id for r in rows[document_id] if r.section_def == judged["key"]),
                    None,
                )
                shown, derived = _effective(
                    own.get(judged["key"]),
                    hints.get(document_id, {}).get(row_id),
                    d.status in FROZEN_STATUSES,
                )
            items.append(
                {
                    "document_id": document_id,
                    "type_code": d.template.type_code,
                    "status": d.status,
                    "version": d.version,
                    "correcting": d.correcting,
                    "target_summary": _target_summary(
                        d, refs[document_id], info.get("item_name"), info.get("supplier_name")
                    ),
                    "inspector_id": info.get("inspector"),
                    "verdict": verdict,
                    "nonconforming": nonconforming,
                    "check_counts": counts,
                    # D-232: 판정 섹션 값 전체(D03 묶음 검사 항목 열). 판정 섹션 없으면 None
                    # D-234: hint 필드(성적서 유무)는 시스템 값 — 지금 계산이면 키가 verdict_derived
                    "verdict_values": shown,
                    "verdict_derived": derived,
                }
            )
        return {"items": items, "missing": [i for i in ids if i not in documents]}


class _BriefRow:
    """F26 hint 계산용 행(section_def·section_id만)."""

    __slots__ = ("section_def", "section_id")

    def __init__(self, section_def, section_id):
        self.section_def, self.section_id = section_def, section_id


def find_documents_by_lots(lot_ids, type_codes):
    """N4: LOT 여러 개에 문서 단위로 연결된 문서(삭제 제외, 양식 유형 한정). SQL 1.

    빈 목록이면 SQL 없음.
    반환 [{lot_id, document_id, type_code}] — LOT·문서 id 순.
    """
    lots = sorted({i for i in lot_ids if isinstance(i, int) and not isinstance(i, bool)})
    types = sorted(set(type_codes))
    if not lots or not types:
        return []
    with step("DOC-FNL-01", "DOC", "LOT 여러 개로 문서 찾기"):
        lot_marks, type_marks = ", ".join(["%s"] * len(lots)), ", ".join(["%s"] * len(types))
        with connection_cursor() as cursor:
            cursor.execute(
                "SELECT r.lot_id, d.document_id, t.type_code FROM document_ref r "
                "JOIN document d ON d.document_id = r.document_id "
                "JOIN document_template t ON t.template_id = d.template_id "
                f"WHERE r.lot_id IN ({lot_marks}) AND r.section_id IS NULL "
                f"AND t.type_code IN ({type_marks}) AND d.deleted_at IS NULL "
                "ORDER BY r.lot_id, d.document_id",
                [*lots, *types],
            )
            return [
                {"lot_id": lot_id, "document_id": document_id, "type_code": type_code}
                for lot_id, document_id, type_code in cursor.fetchall()
            ]


def _inspector_failure(document_id, expected_version, inspector_id):
    """DOC-BIN-05a: 0행일 때 사유 — 404 → 상태 409 → 버전 409 → info 행 없음 409 → 같은 값(성공).

    기존 _lock_failure는 마지막에 DOCUMENT_LOCKED를 내므로 쓰지 않는다(검토 B-4).
    """
    with step("DOC-BIN-05a", "DOC", "실패·같은 값 판정") as s:
        row = (
            Document.objects.filter(pk=document_id)
            .values("status", "deleted_at", "version", "updated_at")
            .first()
        )
        if row is None or row["deleted_at"] is not None:
            raise errors.DocumentNotFound()
        if row["status"] not in EDITABLE:
            raise errors.DocumentLocked(
                details=[
                    {
                        "path": "status",
                        "code": row["status"],
                        "message": f"현재 상태: {row['status']}",
                    }
                ]
            )
        if row["version"] != expected_version:
            raise errors.VersionConflict(
                details=[
                    {
                        "path": "expected_version",
                        "code": "conflict",
                        "message": f"내가 연 버전 {expected_version}, 현재 {row['version']}",
                        "expected": expected_version,
                        "current": row["version"],
                        "updated_at": _iso(row["updated_at"]),
                    }
                ]
            )
        info = (
            DocSection.objects.filter(document_id=document_id, section_def="info")
            .values_list("values_json", flat=True)
            .first()
        )
        if info is None:
            raise errors.SectionRowNotFound(
                details=[{"path": "info", "code": "missing", "message": "기본정보 행이 없습니다."}]
            )
        if (info or {}).get("inspector") != inspector_id:  # 방어선 — 같은 트랜잭션이라 오지 않음
            raise errors.DocumentLocked()
        s.note("같은 값 — 변화 없음(버전 그대로)")
        return {"changed": False, "version": row["version"]}


def _set_inspector(actor_id, document_id, expected_version, inspector_id, now):
    """한 문서: 조건부 UPDATE(검사·잠금·같은 값 제외를 한 문장으로) → info.inspector 변경."""
    with step("DOC-BIN-05", "DOC", "문서 UPDATE(조건부)") as s:
        with connection_cursor() as cursor:
            cursor.execute(
                "UPDATE document SET version = version + 1, updated_at = %s "
                "WHERE document_id = %s AND deleted_at IS NULL "
                f"AND status IN ({', '.join(['%s'] * len(EDITABLE))}) AND version = %s "
                "AND EXISTS (SELECT 1 FROM doc_section s "
                "WHERE s.document_id = document.document_id AND s.section_def = 'info' "
                "AND json_extract(s.values_json, '$.inspector') IS NOT %s)",
                [_db_datetime(now), document_id, *EDITABLE, expected_version, inspector_id],
            )
            changed = cursor.rowcount
        s.note(f"영향 행 {changed}")
    if changed == 0:
        return _inspector_failure(document_id, expected_version, inspector_id)
    with step("DOC-BIN-06", "DOC", "info.inspector 변경"):
        with connection_cursor() as cursor:
            cursor.execute(
                "UPDATE doc_section SET values_json = json_set(values_json, '$.inspector', %s), "
                "recorded_at = %s, recorded_by = %s "
                "WHERE document_id = %s AND section_def = 'info'",
                [inspector_id, _db_datetime(now), actor_id, document_id],
            )
    return {"changed": True, "version": expected_version + 1}


@roles.scope()
def batch_set_inspector(actor_id, items, inspector_id):
    """F25: 점검자 일괄 지정(D03 info.inspector). 문서마다 세이브포인트, 같은 값은 "변화 없음".

    items: [{document_id, expected_version}] 1~50건. 입력 검사(staff·유형)는 트랜잭션 밖(G3).
    inspector_id는 정수로 바인딩한다(P7 S3 J6). 상태 전이가 아니라 신호 없음.
    """
    pairs = batch.version_items(items, "items")
    if not isinstance(inspector_id, int) or isinstance(inspector_id, bool):
        raise ApiError(
            "inspector_id(staff id)가 필요합니다.",
            [{"path": "inspector_id", "code": "invalid", "message": "정수여야 합니다."}],
        )
    with step("DOC-BIN-02", "DOC", "staff·유형 검사"):
        if not staff_services.existing_ids([inspector_id]):
            raise errors.ValidationFailed(
                details=[
                    validation.error("inspector_id", "unknown_staff", "등록되지 않은 사용자입니다.")
                ]
            )
        types = dict(
            Document.objects.filter(
                pk__in=[document_id for document_id, _ in pairs], deleted_at__isnull=True
            ).values_list("document_id", "template__type_code")
        )
        wrong = [
            f"items[{i}]"
            for i, (document_id, _) in enumerate(pairs)
            if document_id in types and types[document_id] not in INSPECTOR_TYPES
        ]
        if wrong:
            raise batch.not_batchable(
                wrong, f"점검자 일괄 지정은 {'·'.join(INSPECTOR_TYPES)} 양식만 할 수 있습니다."
            )
    now = timezone.now()

    def one(pair):
        if pair[0] in types:  # 없는 문서는 _set_inspector가 404로(404 → 403 순서)
            _require_inspector_setter(actor_id, types[pair[0]])  # ROLE-R08(r13) — 문서마다
        return _set_inspector(actor_id, pair[0], pair[1], inspector_id, now)

    with step("DOC-BIN-03", "DOC", "트랜잭션") as tx:
        with transaction.atomic():
            results = batch.run_each(
                pairs,
                one,
                ident=lambda pair: {"document_id": pair[0]},
                layer="DOC",
                item_step="DOC-BIN-04",
            )
        tx.note(f"커밋: {sum(r['ok'] for r in results)}/{len(results)}")
    with step("DOC-BIN-07", "DOC", "결과 모음"):
        return batch.summary("inspector", results)


# ---------------------------------------------------------------- P8: 작성 안 함·되돌리기·최근 값


def _clean_skip_reason(reason):
    """작성 안 함 사유: 앞뒤 공백 제거 뒤 1~200자(VR-P8-05, v7.1 CHECK와 같음)."""
    text = reason.strip() if isinstance(reason, str) else ""
    if not 1 <= len(text) <= SKIP_REASON_MAX:
        raise errors.ValidationFailed(
            details=[
                validation.error(
                    "reason", "invalid", f"사유를 1~{SKIP_REASON_MAX}자로 적으세요(공백만 불가)."
                )
            ]
        )
    return text


def _skip_failure(document_id, expected_version):
    """DOC-SKP-05a: 0행일 때 사유 — 404 → 작성 안 함 불가 양식·직접 만든 문서 → 상태 → 버전."""
    with step("DOC-SKP-05a", "DOC", "실패 사유 확인"):
        row = (
            Document.objects.filter(pk=document_id)
            .values(
                "status",
                "deleted_at",
                "version",
                "updated_at",
                "record_key",
                "template__schema_json",
            )
            .first()
        )
        if row is None or row["deleted_at"] is not None:
            raise errors.DocumentNotFound()
        if not (row["template__schema_json"] or {}).get("skippable") or not row["record_key"]:
            raise errors.DocumentNotSkippable()
        if row["status"] not in SKIPPABLE:
            raise errors.InvalidTransition(
                details=[
                    {
                        "path": "status",
                        "code": row["status"],
                        "message": f"작성중일 때만 바꿀 수 있습니다(현재 {row['status']}).",
                    }
                ]
            )
        raise errors.VersionConflict(
            details=[
                {
                    "path": "expected_version",
                    "code": "conflict",
                    "message": f"내가 연 버전 {expected_version}, 현재 {row['version']}",
                    "expected": expected_version,
                    "current": row["version"],
                    "updated_at": _iso(row["updated_at"]),
                }
            ]
        )


def _skip_one(actor_id, document_id, expected_version, reason, now, targets):
    """한 문서: 조건부 UPDATE(상태·record_key·양식 skippable·버전을 한 문장으로).

    targets(DOC-WRT-01 결과)에 있으면 ROLE-R07(r13)을 먼저 — 없는 문서는 UPDATE 실패로 404.
    """
    if document_id in targets:
        _check_write(actor_id, targets[document_id])
    with step("DOC-SKP-05", "DOC", "작성 안 함(조건부 UPDATE)") as s:
        changed = Document.objects.filter(
            pk=document_id,
            deleted_at__isnull=True,
            status__in=SKIPPABLE,
            version=expected_version,
            record_key__isnull=False,
            template__schema_json__skippable=True,
        ).update(
            status="skipped",
            skipped_at=now,
            skipped_by_id=actor_id,
            skip_reason=reason,
            updated_at=now,
            version=F("version") + 1,
        )
        s.note(f"영향 행 {changed}")
    if changed == 0:
        _skip_failure(document_id, expected_version)
    return {"status": "skipped", "version": expected_version + 1}


@roles.scope()
def skip_documents(actor_id, items, reason):
    """F27: 작성 안 함(일괄, 한 건도 items 1개). 문서마다 세이브포인트(P7 F25와 같은 결과 모양).

    값·개선조치는 그대로 둔다. 상태 전이 신호는 보내지 않는다(받는 쪽 규칙 없음).
    """
    with step("DOC-SKP-02", "DOC", "사유·항목 형식"):
        pairs = batch.version_items(items, "items")
        reason = _clean_skip_reason(reason)
    with step("DOC-WRT-01", "DOC", "양식 유형·점검자(항목 전부)") as s:
        targets = _write_targets([document_id for document_id, _ in pairs])
        s.note(f"{len(targets)}/{len(pairs)}건")
    now = timezone.now()
    with step("DOC-SKP-03", "DOC", "트랜잭션") as tx:
        with transaction.atomic():
            results = batch.run_each(
                pairs,
                lambda pair: _skip_one(actor_id, pair[0], pair[1], reason, now, targets),
                ident=lambda pair: {"document_id": pair[0]},
                layer="DOC",
                item_step="DOC-SKP-04",
            )
        tx.note(f"커밋: {sum(r['ok'] for r in results)}/{len(results)}")
    with step("DOC-SKP-06", "DOC", "결과 모음"):
        return batch.summary("skip", results)


def unskip_document(actor_id, document_id, expected_version):
    """F28: 되돌리기 skipped → draft. 작성 안 함 기록을 비우고 값은 그대로(확인 창 없음 — S1-Q5)."""
    with roles.scope():
        require_write(actor_id, document_id)  # ROLE-R07(r13)
    now = timezone.now()
    with transaction.atomic():
        with step("DOC-USK-02", "DOC", "되돌리기(조건부 UPDATE)") as s:
            changed = Document.objects.filter(
                pk=document_id,
                deleted_at__isnull=True,
                status="skipped",
                version=expected_version,
            ).update(
                status="draft",
                skipped_at=None,
                skipped_by_id=None,
                skip_reason=None,
                updated_at=now,
                version=F("version") + 1,
            )
            s.note(f"영향 행 {changed}")
        if changed == 0:
            with step("DOC-USK-02a", "DOC", "실패 사유 확인"):
                row = (
                    Document.objects.filter(pk=document_id)
                    .values("status", "deleted_at", "version", "updated_at")
                    .first()
                )
                if row is None or row["deleted_at"] is not None:
                    raise errors.DocumentNotFound()
                if row["status"] != "skipped":
                    raise errors.InvalidTransition(
                        details=[
                            {
                                "path": "status",
                                "code": row["status"],
                                "message": "작성 안 함 문서가 아닙니다.",
                            }
                        ]
                    )
                raise errors.VersionConflict(
                    details=[
                        {
                            "path": "expected_version",
                            "code": "conflict",
                            "message": f"내가 연 버전 {expected_version}, 현재 {row['version']}",
                            "expected": expected_version,
                            "current": row["version"],
                            "updated_at": _iso(row["updated_at"]),
                        }
                    ]
                )
    with step("DOC-USK-03", "DOC", "결과 조회"):
        return _detail(document_id)


def recent_values(type_code, section=None, field=None, limit=RECENT_MAX):
    """F29: 그 양식 text 필드의 최근 값(서로 다른 값, 최근 작업일 순, 삭제 문서 제외).

    section을 비우면 최신 양식 버전의 1행 섹션에서 field를 찾는다(API는 field만 받음).
    """
    with step("DOC-RCV-01", "DOC", "양식·필드 확인"):
        template = (
            DocumentTemplate.objects.filter(type_code=type_code).order_by("-version").first()
            if isinstance(type_code, str) and type_code
            else None
        )
        found = None
        if template is not None and isinstance(field, str):
            for candidate in _one_row_sections(template.schema_json):
                if section not in (None, candidate["key"]):
                    continue
                match = next((f for f in candidate["fields"] if f["key"] == field), None)
                if match is not None:
                    found = (candidate["key"], match)
                    break
        if template is None or found is None or found[1].get("type") != "text":
            raise errors.InvalidFilter(
                details=[
                    validation.error("field", "invalid", "양식의 1행 영역 text 필드가 아닙니다.")
                ]
            )
    with step("DOC-RCV-02", "DOC", "최근 값 조회"):
        path = f"$.{field}"
        with connection_cursor() as cursor:
            cursor.execute(
                "SELECT v FROM (SELECT trim(json_extract(s.values_json, %s)) AS v, "
                "MAX(d.work_date) AS last_day, MAX(d.document_id) AS last_id "
                "FROM doc_section s JOIN document d ON d.document_id = s.document_id "
                "JOIN document_template t ON t.template_id = d.template_id "
                "WHERE t.type_code = %s AND s.section_def = %s AND d.deleted_at IS NULL "
                "AND json_type(s.values_json, %s) = 'text' GROUP BY 1) "
                "WHERE v <> '' ORDER BY last_day DESC, last_id DESC LIMIT %s",
                [path, type_code, found[0], path, limit],
            )
            return {"items": [row[0] for row in cursor.fetchall()]}


def documents_on_dates(type_codes, date_from, date_to):
    """N10(P8, REQ-F06용): 양식 유형·작업일 범위의 문서(삭제 제외). SQL 1(ix_document_list).

    반환 [{document_id, type_code, work_date}] — 작업일·문서 id 순. 빈 유형이면 SQL 없음.
    """
    types = sorted(set(type_codes))
    if not types:
        return []
    with step("DOC-DAT-01", "DOC", "유형·작업일 범위로 문서 찾기"):
        rows = (
            Document.objects.filter(
                deleted_at__isnull=True,
                work_date__gte=date_from,
                work_date__lte=date_to,
                template__type_code__in=types,
            )
            .order_by("work_date", "document_id")
            .values_list("document_id", "template__type_code", "work_date")
        )
        return [{"document_id": i, "type_code": t, "work_date": _iso(day)} for i, t, day in rows]


# ---------------------------------------------------------------- P10 N7 작성 요구 문서 기간 조회

REQUIREMENT_RANGE_MAX = 62  # 양 끝 포함(p10-s2-spec 2.3)
TODO_STATUSES = ("draft", "rejected", "correcting")  # 작성 필요 상태(P10 S1a-Q4 a)
TAG_LABELS = {"weekday": "주 항목", "first_weekday_of_month": "월 항목"}


def tag_rules(schema):
    """양식 na_default에서 꼬리표 규칙(P10 A3 a — 날짜 규칙 기준). {}(연간)은 꼬리표 없음.

    반환 [{label, weekday} | {label, first_weekday_of_month}] — 같은 규칙은 한 번.
    """
    rules, seen = [], set()
    for section in (schema or {}).get("sections", []):
        for field in section.get("fields", []):
            rule = field.get("na_default")
            if not isinstance(rule, dict) or not rule:
                continue
            for key, label in TAG_LABELS.items():
                if key in rule and (key, rule[key]) not in seen:
                    seen.add((key, rule[key]))
                    rules.append({"label": label, key: rule[key]})
    return rules


def tags_for(rules, day):
    """그날 맞는 꼬리표: weekday = 그 요일, first_weekday_of_month = 그 달 첫 그 요일."""
    tags = []
    for rule in rules:
        if "weekday" in rule:
            hit = day.isoweekday() == rule["weekday"]
        else:
            hit = day.isoweekday() == rule["first_weekday_of_month"] and day.day <= 7
        if hit and rule["label"] not in tags:
            tags.append(rule["label"])
    return tags


def _as_day(value):
    from datetime import date

    if isinstance(value, date):
        return value
    if isinstance(value, str) and len(value) == 10:
        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.isoformat() == value else None
    return None


def requirement_documents(date_from, date_to, type_codes=(), count_older=False):
    """N7(P10, REQ-F10용): 작업일 기간의 작성 요구 문서(record_key 있음, 삭제 제외) — 모든 상태.

    SQL 5 이하: 문서·양식 1 · 참조 1 · info 1 · (양식 1 — type_codes) · (건수 1 — count_older).
    반환 {rows, templates, older_count?}. 쓰기 없음.
    """
    with step("DOC-RQD-01", "DOC", "입력 확인"):
        start, end = _as_day(date_from), _as_day(date_to)
        problems = []
        if start is None:
            problems.append(validation.error("date_from", "invalid", "YYYY-MM-DD 형식입니다."))
        if end is None:
            problems.append(validation.error("date_to", "invalid", "YYYY-MM-DD 형식입니다."))
        if start and end:
            if start > end:
                problems.append(validation.error("date_from", "order", "시작일이 늦습니다."))
            elif (end - start).days + 1 > REQUIREMENT_RANGE_MAX:
                problems.append(
                    validation.error(
                        "date_to", "max", f"기간은 {REQUIREMENT_RANGE_MAX}일까지입니다."
                    )
                )
        codes = sorted({c for c in type_codes if isinstance(c, str) and c})
        if problems:
            raise errors.ValidationFailed(details=problems)
    with step("DOC-RQD-02", "DOC", "기간의 작성 요구 문서·양식") as s:
        documents = list(
            Document.objects.select_related("template")
            .filter(
                deleted_at__isnull=True,
                record_key__isnull=False,
                work_date__gte=start,
                work_date__lte=end,
            )
            .order_by("work_date", "document_id")
        )
        s.note(f"{len(documents)}건")
    ids = [d.document_id for d in documents]
    with step("DOC-RQD-03", "DOC", "참조·info") as s:
        refs, info = {i: [] for i in ids}, {}
        if ids:
            for ref in DocumentRef.objects.filter(document_id__in=ids).order_by("ref_id"):
                refs[ref.document_id].append(_ref_row(ref))
            for document_id, values in DocSection.objects.filter(
                document_id__in=ids, section_def="info"
            ).values_list("document_id", "values_json"):
                info[document_id] = values or {}
        else:
            s.skip("문서 없음")
    with step("DOC-RQD-04", "DOC", "조립"):
        rules_by_template, rows = {}, []
        for d in documents:
            if d.template_id not in rules_by_template:
                rules_by_template[d.template_id] = tag_rules(d.template.schema_json)
            own = info.get(d.document_id, {})
            row = {
                "document_id": d.document_id,
                "type_code": d.template.type_code,
                "template_name": d.template.name,
                "work_date": _iso(d.work_date),
                "record_key": d.record_key,
                "status": d.status,
                "version": d.version,
                "assignee_id": d.assignee_id,
                "inspector_id": own.get("inspector"),
                "created_by": d.created_by_id,
                "updated_at": _iso(d.updated_at),
                "requirement": _requirement(d.record_key, refs[d.document_id]),
                "target_summary": _target_summary(d, refs[d.document_id], own.get("item_name")),
                "tags": tags_for(rules_by_template[d.template_id], d.work_date),
            }
            if d.template.type_code == "D03":
                row["received_date"] = own.get("received_date") or row["work_date"]
            rows.append(row)
        result = {"rows": rows, "templates": {}}
    with step("DOC-RQD-05", "DOC", "양식 이름·꼬리표 규칙") as s:
        if codes:
            latest = (
                DocumentTemplate.objects.filter(type_code=OuterRef("type_code"), is_active=True)
                .order_by("-version")
                .values("version")[:1]
            )
            for t in DocumentTemplate.objects.filter(
                type_code__in=codes, is_active=True, version=Subquery(latest)
            ):
                result["templates"][t.type_code] = {
                    "name": t.name,
                    "tag_rules": tag_rules(t.schema_json),
                }
        else:
            s.skip("양식 없음")
    with step("DOC-RQD-06", "DOC", "기간 앞 미완료 건수") as s:
        if count_older:
            result["older_count"] = Document.objects.filter(
                deleted_at__isnull=True,
                record_key__isnull=False,
                work_date__lt=start,
                status__in=TODO_STATUSES,
            ).count()
        else:
            s.skip("요청 안 함")
    return result


def connection_cursor():
    from django.db import connection

    return connection.cursor()


def _db_datetime(value):
    """원시 SQL 파라미터를 ORM과 같은 저장 형식으로(UTC, SQLite 텍스트)."""
    from django.db import connection

    return connection.ops.adapt_datetimefield_value(value)


def _db_date(value):
    from django.db import connection

    return connection.ops.adapt_datefield_value(value)


# ------------------------------------------------ P12 N9 출력용 문서 묶음 (p12-s2-spec 3.1)

PRINT_BATCH = 100  # 한 번에 읽는 문서 수 상한 — WF가 나눠 부른다(B5, ISS-021)


def documents_for_print(document_ids):
    """N9: 문서들의 상세(get_document 모양) + open_correction·skip_reason. SQL 6개(문서 수 무관)
    + D-234 성적서 유무 계산 1(hint 필드가 있는 양식이 있을 때만).

    파일은 읽지 않는다(D01·D02 출력 없음). D-234 R2: 섹션 values는 **실제 값** — hint 필드
    (성적서 유무)는 시스템 값(_assemble), hints에도 둔다. 삭제된·없는 문서는 빠진다.
    반환 {document_id: 상세}. 100건 넘으면 ValueError(호출자가 나눔).
    """
    ids = sorted({i for i in document_ids if isinstance(i, int) and not isinstance(i, bool)})
    if len(ids) > PRINT_BATCH:
        raise ValueError(f"documents_for_print는 한 번에 {PRINT_BATCH}건까지")
    if not ids:
        return {}
    with step("DOC-PRT-01", "DOC", "출력용 문서·섹션·참조·개선조치·정정 기록"):
        documents = list(
            Document.objects.select_related("template").filter(pk__in=ids, deleted_at__isnull=True)
        )
        found = [d.document_id for d in documents]
        rows = {}
        for row in DocSection.objects.filter(document_id__in=found):
            rows.setdefault(row.document_id, []).append(row)
        refs = _refs_by_document(found)
        items = list(
            DeviationAction.objects.filter(document_id__in=found, deleted_at__isnull=True).order_by(
                "deviation_id"
            )
        )
        checkers = {}
        for row in DeviationChecker.objects.filter(
            deviation_id__in=[d.deviation_id for d in items]
        ).order_by("staff_id"):
            checkers.setdefault(row.deviation_id, []).append(row.staff_id)
        deviations = {}
        for item in items:
            deviations.setdefault(item.document_id, []).append(
                _deviation_row(item, checkers.get(item.deviation_id, []))
            )
        history = {}
        for c in DocumentCorrection.objects.filter(document_id__in=found).order_by(
            "-started_at", "-correction_id"
        ):
            history.setdefault(c.document_id, []).append(c)
        hints = _hints_many(
            [(d, rows.get(d.document_id, []), refs[d.document_id]) for d in documents]
        )
    result = {}
    for document in documents:
        mine = history.get(document.document_id, [])
        current = next((c for c in mine if c.closed_at is None), None)
        corrections = (
            None if current is None else _correction_row(current, document),
            [_correction_row(c) for c in mine],
        )
        data = _assemble(
            document,
            rows.get(document.document_id, []),
            refs[document.document_id],
            None,
            deviations.get(document.document_id, []),
            hints.get(document.document_id),
            corrections,
        )
        data["open_correction"] = current is not None
        data["skip_reason"] = document.skip_reason
        data["guide"] = document.template.schema_json.get("guide", [])
        data["schema_sections"] = document.template.schema_json["sections"]
        result[document.document_id] = data
    return result


# ---------------------------------------------------------------- P11 CCP 대시보드·개선조치 확인
# (dev-notes/dashboard/p11-s2-spec.md 2.2·3장). DOC는 "CCP"를 모른다 — 측정 섹션은 양식 키
# phase_order, 이탈은 nonconforming, 확인 노출은 deviation.check_visibility로 판단한다.

VISIBLE_AFTER_COMPLETE = ("completed", "submitted", "approved", "rejected", "correcting")
PENDING_OTHER_DAYS_MAX = 10  # 다른 날 내 확인 대기 날짜 수(S1-Q1 a)
PENDING_FUTURE_IDS_MAX = 5  # 미래 작업일 묶음의 문서 [열기] 수(A2 a)
PERIOD_SCAN_DAYS = 31  # 기간 문서 후보를 읽을 범위(기준일 −31일 ~ 기준일). 지금 기간은 D11 6일


def _today():
    """오늘(Asia/Seoul). 테스트는 이 함수를 바꿔 날짜를 고정한다."""
    return timezone.localdate()


def period_days(schema):
    """기간 문서의 길이(일, G2 — P11 S4): 1행 섹션 필드 date_window.to의 최댓값, 없으면 0.

    D11은 info.checked_on date_window {from 0, to 6} → work_date(월)~+6일(일). VR-P11-01 5번의
    period_end를 컬럼 없이 계산한다(C3 S4에서 period_end 컬럼을 넣지 않음, D-162 Q2 a).
    """
    days = 0
    for section in (schema or {}).get("sections", []):
        if section.get("repeat"):
            continue
        for field in section.get("fields", []):
            window = field.get("date_window")
            if isinstance(window, dict) and isinstance(window.get("to"), int):
                days = max(days, window["to"])
    return days


def _covers(work_date, days, base):
    """문서(work_date ~ +days)가 기준일을 포함하는가."""
    from datetime import timedelta

    return work_date <= base <= work_date + timedelta(days=days)


def _expect(item):
    return {op: item[op] for op in validation.CONDITION_OPS if op in item}


def _reasons(section, values):
    """이탈 행의 어긋난 조건(N8). computed 판정 필드가 있으면 그 조건 중 거짓인 것,
    없으면 nonconforming 조건 중 참인 것. 값이 비어 판정이 안 된 조건은 뺀다."""
    labels = {f["key"]: f.get("label", f["key"]) for f in section.get("fields", [])}
    computed = next((f["computed"] for f in section.get("fields", []) if f.get("computed")), None)
    if computed:
        items = computed.get("all") or computed.get("any") or []
        wanted = False
    else:
        rule = section.get("nonconforming") or {}
        items = rule.get("all") or rule.get("any") or []
        wanted = True
    reasons = []
    for item in items:
        value = (values or {}).get(item["field"])
        if validation._compare(item, value) is wanted:
            reasons.append(
                {
                    "field": item["field"],
                    "label": labels.get(item["field"], item["field"]),
                    "value": value,
                    "expect": _expect(item),
                }
            )
    return reasons


def measurement_summary(work_date, type_codes, note_fields=None):
    """N8(P11, REQ-F11용): 작업일 문서의 측정 요약·이탈 행·개선조치. 쓰기 없음.

    SQL 6: 문서·양식 1 · 행 1 · 참조 1 · 개선조치 1 · 확인자 1 · 양식 이름 1(문서 없는 양식 카드).
    반환 {documents: [...], templates: {type_code: name}}.
    note_fields(P11 S5 r1): {type_code: {section_def: field}} — 부르는 쪽이 정한 "특이사항" 칸.
    값이 있는 행을 문서마다 notes로 돌려준다(DOC는 어느 칸이 특이사항인지 모름).
    """
    with step("DOC-MSM-01", "DOC", "입력 확인"):
        day = _as_day(work_date)
        codes = [c for c in (type_codes or []) if isinstance(c, str) and c]
        problems = []
        if day is None:
            problems.append(validation.error("work_date", "invalid", "YYYY-MM-DD 형식입니다."))
        if not codes:
            problems.append(validation.error("type_codes", "required", "양식을 지정하세요."))
        if problems:
            raise errors.ValidationFailed(details=problems)
    with step("DOC-MSM-02", "DOC", "작업일 문서·양식") as s:
        documents = list(
            Document.objects.select_related("template")
            .filter(deleted_at__isnull=True, work_date=day, template__type_code__in=codes)
            .order_by("document_id")
        )
        s.note(f"{len(documents)}건")
    ids = [d.document_id for d in documents]
    rows, labels, deviations, checkers = {i: [] for i in ids}, {}, {i: [] for i in ids}, {}
    batch_ids = {}
    with step("DOC-MSM-03", "DOC", "행·참조·개선조치·확인자") as s:
        if ids:
            for row in DocSection.objects.filter(document_id__in=ids).order_by(
                "document_id", "section_def", "row_no"
            ):
                rows[row.document_id].append(row)
            for document_id, label, batch_id in DocumentRef.objects.filter(
                document_id__in=ids, section_id__isnull=True
            ).values_list("document_id", "label", "production_batch_id"):
                labels.setdefault(document_id, label)
                if batch_id is not None:
                    batch_ids.setdefault(document_id, batch_id)
            for d in DeviationAction.objects.filter(
                document_id__in=ids, deleted_at__isnull=True
            ).order_by("deviation_id"):
                deviations[d.document_id].append(d)
            dev_ids = [d.deviation_id for items in deviations.values() for d in items]
            if dev_ids:
                for deviation_id, staff_id in (
                    DeviationChecker.objects.filter(deviation_id__in=dev_ids)
                    .order_by("staff_id")
                    .values_list("deviation_id", "staff_id")
                ):
                    checkers.setdefault(deviation_id, []).append(staff_id)
        else:
            s.skip("문서 없음")
    with step("DOC-MSM-04", "DOC", "측정 섹션·최근 측정·이탈 행"):
        out = []
        for d in documents:
            sections = validation.sections_of(d.template.schema_json)
            by_section, latest, nonconforming, info = {}, None, [], {}
            repeat_values, notes = {}, []
            wanted = ((note_fields or {}).get(d.template.type_code)) or {}
            for row in rows[d.document_id]:
                section = sections.get(row.section_def)
                if section is None:
                    continue
                values = row.values_json or {}
                if not section["repeat"]:
                    if row.section_def == "info":
                        info = values
                    continue
                order = section.get("phase_order")
                at = values.get(order["time_field"]) if order else None
                if order:
                    by_section[row.section_def] = by_section.get(row.section_def, 0) + 1
                    if at and (
                        latest is None or (at, row.row_no) > (latest["at"], latest["row_no"])
                    ):
                        latest = {
                            "section_def": row.section_def,
                            "row_no": row.row_no,
                            "at": at,
                            "phase": values.get(order["field"]),
                            "values": values,
                            "verdict": values.get("verdict"),
                        }
                else:
                    repeat_values.setdefault(row.section_def, []).append(values)
                note_key = wanted.get(row.section_def)
                text = values.get(note_key) if note_key else None
                if isinstance(text, str) and text.strip():
                    field = next((f for f in section["fields"] if f["key"] == note_key), {})
                    notes.append(
                        {
                            "section_id": row.section_id,
                            "section_def": row.section_def,
                            "section_label": section.get("label", row.section_def),
                            "field_label": field.get("label", note_key),
                            "row_no": row.row_no,
                            "at": at,
                            "text": text.strip(),
                        }
                    )
                if validation.is_nonconforming(section, values):
                    nonconforming.append(
                        {
                            "section_id": row.section_id,
                            "section_def": row.section_def,
                            "row_no": row.row_no,
                            "at": at,
                            "phase": values.get(order["field"]) if order else None,
                            "values": values,
                            "reasons": _reasons(section, values),
                        }
                    )
            for key, section in sections.items():
                if section["repeat"] and section.get("phase_order"):
                    by_section.setdefault(key, 0)
            if latest:
                latest.pop("row_no")
            out.append(
                {
                    "document_id": d.document_id,
                    "type_code": d.template.type_code,
                    "template_name": d.template.name,
                    "status": d.status,
                    "version": d.version,
                    "label": labels.get(d.document_id) or d.subject,
                    "batch_id": batch_ids.get(d.document_id),  # P11 S5 r1: 배치별 공정 순서용
                    "item_name": info.get("item_name"),
                    "rows_by_section": by_section,
                    "latest": latest,
                    "nonconforming": nonconforming,
                    "repeat_values": repeat_values,
                    "notes": notes,
                    "deviations": [
                        {
                            "deviation_id": x.deviation_id,
                            "section_id": x.section_id,
                            "checked_by": x.checked_by_id,
                            "checked_at": _iso(x.checked_at),
                            "checker_ids": checkers.get(x.deviation_id, []),
                            # P11 S5 r1: 배치 영역 이탈 표(개선조치 내용·[확인]용 version)
                            "version": x.version,
                            "description": x.description,
                            "action_result": x.action_result,
                            "actor_id": x.actor_id,
                        }
                        for x in deviations[d.document_id]
                    ],
                }
            )
    with step("DOC-MSM-05", "DOC", "양식 이름(문서 없는 양식 포함)"):
        latest_version = (
            DocumentTemplate.objects.filter(type_code=OuterRef("type_code"), is_active=True)
            .order_by("-version")
            .values("version")[:1]
        )
        templates = dict(
            DocumentTemplate.objects.filter(
                type_code__in=codes, is_active=True, version=Subquery(latest_version)
            ).values_list("type_code", "name")
        )
    return {"documents": out, "templates": templates}


def _bad_filter(path, message):
    return errors.InvalidFilter(details=[validation.error(path, "invalid", message)])


def _flag(value, name):
    if value in (None, "", "0", 0, False):
        return False
    if value in ("1", 1, True):
        return True
    raise _bad_filter(name, "0 또는 1입니다.")


def _pending_queryset():
    """VR-P11-01 1~4(확인자 조건 3은 부르는 쪽): 미삭제·미확인, 문서 살아 있음, 노출 조건."""
    from django.db.models.fields.json import KeyTextTransform, KeyTransform
    from django.db.models.functions import Coalesce

    visibility = Coalesce(
        KeyTextTransform(
            "check_visibility", KeyTransform("deviation", "document__template__schema_json")
        ),
        Value("after_complete"),
        output_field=models.TextField(),
    )
    return (
        DeviationAction.objects.filter(
            deleted_at__isnull=True, checked_at__isnull=True, document__deleted_at__isnull=True
        )
        .annotate(visibility=visibility)
        .filter(
            (Q(visibility="immediate") & ~Q(document__status="skipped"))
            | (~Q(visibility="immediate") & Q(document__status__in=VISIBLE_AFTER_COMPLETE))
        )
    )


def _mine(actor_id):
    return Exists(DeviationChecker.objects.filter(deviation_id=OuterRef("pk"), staff_id=actor_id))


def _check_leader(actor_id):
    """P14 ROLE-R05(FR-13): 팀장은 지정 확인자가 아니어도 확인한다(확인자 없는 개선조치 포함).

    역할 설정 파일 형식 오류면 팀장 예외는 쓸 수 없다(ROLE-C07 — 지정 확인자의 확인은 그대로).
    """
    return actor_id is not None and roles.config_error() is None and roles.is_leader(actor_id)


def _my_pending(queryset, actor_id, leader):
    """내가 확인할 수 있는 대기 — 팀장이면 전부, 아니면 지정 확인자인 것(R05)."""
    return queryset if leader else queryset.filter(_mine(actor_id))


@roles.scope()
def pending_deviations(actor_id, base_date=None, mine=False, summary=False):
    """F30(P11): 개선조치 확인 대기. actor_id = API가 확인한 현재 사용자 또는 None(헤더 없음).

    SQL 6 이하(역할 1 · 목록 1 · 확인자 1 · 참조 1 · info 1 · 내 것 1), summary면 2. 쓰기 없음.
    P14 R05: 팀장이면 "내 것" = 확인 대기 전부(확인자 없는 것 포함).
    """
    with step("DOC-PND-01", "DOC", "기준일·mine·summary 확인"):
        today = _today()
        if base_date in (None, ""):
            base = today
        else:
            base = _as_day(base_date)
            if base is None:
                raise _bad_filter("date", "YYYY-MM-DD 형식입니다.")
            if base > today:
                raise _bad_filter("date", "오늘 이후 날짜는 볼 수 없습니다.")
        mine, summary = _flag(mine, "mine"), _flag(summary, "summary")
        if actor_id is None and (mine or summary):
            raise staff_services.StaffHeaderMissing()
        leader = _check_leader(actor_id)  # P14 R05: 팀장이면 확인 대기 전부가 "내 것"
    pending = _pending_queryset()
    if summary:
        with step("DOC-PND-02", "DOC", "내 확인 대기 합계(배지)"):
            return {"my_total": _my_pending(pending, actor_id, leader).count()}
    from datetime import timedelta

    with step("DOC-PND-02", "DOC", "기준일 문서의 확인 대기 후보") as s:
        candidates = list(
            pending.filter(
                document__work_date__gte=base - timedelta(days=PERIOD_SCAN_DAYS),
                document__work_date__lte=base,
            )
            .select_related("document__template")
            .order_by("created_at", "deviation_id")
        )
        windows = {}
        chosen = []
        for x in candidates:
            template = x.document.template
            if template.template_id not in windows:
                windows[template.template_id] = period_days(template.schema_json)
            if _covers(x.document.work_date, windows[template.template_id], base):
                chosen.append(x)
        s.note(f"후보 {len(candidates)}, 기준일 {len(chosen)}")
    with step("DOC-PND-03", "DOC", "확인자·대상 표시") as s:
        checkers = {}
        if chosen:
            for deviation_id, staff_id in (
                DeviationChecker.objects.filter(deviation_id__in=[x.deviation_id for x in chosen])
                .order_by("staff_id")
                .values_list("deviation_id", "staff_id")
            ):
                checkers.setdefault(deviation_id, []).append(staff_id)
            doc_ids = sorted({x.document_id for x in chosen})
            refs, names = _refs_by_document(doc_ids), _item_names(doc_ids)
        else:
            refs, names = {}, {}
            s.skip("후보 없음")
    with step("DOC-PND-04", "DOC", "줄 조립"):
        rows, no_checker = [], []
        for x in chosen:
            d = x.document
            ids = checkers.get(x.deviation_id, [])
            row = {
                "deviation_id": x.deviation_id,
                "version": x.version,
                "document_id": d.document_id,
                "type_code": d.template.type_code,
                "template_name": d.template.name,
                "target_summary": _target_summary(d, refs[d.document_id], names.get(d.document_id)),
                "work_date": _iso(d.work_date),
                "description": x.description,
                "action_result": x.action_result,
                "actor_id": x.actor_id,
                "checker_ids": ids,
                "created_at": _iso(x.created_at),
                # P14 R05: 지정 확인자 또는 HACCP팀장(확인자 없는 줄도)
                "can_check": actor_id is not None and (actor_id in ids or leader),
            }
            (rows if ids else no_checker).append(row)
        result = {
            "base_date": base.isoformat(),
            "rows": [r for r in rows if r["can_check"]] if mine else rows,
            "counts": {"total": len(rows)},
            "no_checker": {"count": len(no_checker), "rows": no_checker},
        }
        if actor_id is None:
            return result
        # 팀장은 확인자 없는 줄도 셈(내가 확인할 수 있는 전체 — 화면 r7 DSH-SC)
        result["counts"]["mine"] = sum(1 for r in rows + no_checker if r["can_check"])
    with step("DOC-PND-05", "DOC", "내 확인 대기 — 다른 날·합계"):
        mine_rows = list(
            _my_pending(pending, actor_id, leader)
            .order_by("document__work_date", "deviation_id")
            .values_list(
                "deviation_id",
                "document_id",
                "document__work_date",
                "document__template_id",
                "document__template__schema_json",
            )
        )
        other, other_total = {}, 0
        for deviation_id, document_id, work_date, template_id, schema in mine_rows:
            if template_id not in windows:
                windows[template_id] = period_days(schema)
            if _covers(work_date, windows[template_id], base):
                continue
            other_total += 1
            group = other.setdefault(work_date, {"count": 0, "document_ids": []})
            group["count"] += 1
            if document_id not in group["document_ids"]:
                group["document_ids"].append(document_id)
        days = sorted(other, reverse=True)[:PENDING_OTHER_DAYS_MAX]
        result["other_days_mine"] = []
        for day in days:
            item = {
                "work_date": day.isoformat(),
                "count": other[day]["count"],
                "future": day > today,
            }
            if item["future"]:
                item["document_ids"] = other[day]["document_ids"][:PENDING_FUTURE_IDS_MAX]
            result["other_days_mine"].append(item)
        result["other_days_mine_total"] = other_total
        result["my_total"] = len(mine_rows)
    return result


@roles.scope()
def check_deviation(actor_id, deviation_id, expected_version):
    """F31(P11): 개선조치 확인. 지정 확인자 또는 HACCP팀장(P14 R05) 1명이 한 번(취소 없음, Q9 a).

    팀장 여부는 UPDATE 전에 역할로 판단해 값으로 넘긴다(p14-s2-flows 3.11 DOC-DVK-02).

    updated_by·updated_at은 바꾸지 않는다(S2-Q2 a — 확인은 내용 수정이 아님). 문서는 그대로.
    노출 조건은 보지 않는다(S2-Q3 a — 문서 상세에서는 상태와 무관하게 확인).
    """
    with step("DOC-DVK-01", "DOC", "형식 검사") as s:
        if (
            isinstance(expected_version, bool)
            or not isinstance(expected_version, int)
            or expected_version < 1
        ):
            s.fail("expected_version")
            raise errors.ValidationFailed(
                details=[
                    validation.error("expected_version", "required", "1 이상의 정수여야 합니다.")
                ]
            )
        leader = _check_leader(actor_id)  # P14 R05 — 설정 오류면 False(C07)
        s.note("HACCP팀장" if leader else "지정 확인자만")
    now = timezone.now()
    with transaction.atomic():
        with step("DOC-DVK-02", "DOC", "확인 기록(조건부 UPDATE)") as s:
            mine = DeviationChecker.objects.filter(deviation_id=OuterRef("pk"), staff_id=actor_id)
            target = _live_deviation(deviation_id, expected_version).filter(checked_at__isnull=True)
            if not leader:
                target = target.filter(Exists(mine))
            changed = target.update(
                checked_by_id=actor_id, checked_at=now, version=F("version") + 1
            )
            s.note(f"영향 행 {changed}")
        if changed == 0:
            with step("DOC-DVK-02a", "DOC", "실패 사유 확인"):
                row = (
                    DeviationAction.objects.filter(pk=deviation_id)
                    .values("deleted_at", "checked_at", "checked_by", "document__deleted_at")
                    .first()
                )
                if (
                    row is None
                    or row["deleted_at"] is not None
                    or row["document__deleted_at"] is not None
                ):
                    raise errors.DeviationNotFound()
                if row["checked_at"] is not None:
                    raise errors.AlreadyChecked(
                        details=[
                            {
                                "path": "deviation",
                                "code": "already_checked",
                                "message": "이미 확인되었습니다.",
                                "checked_by": row["checked_by"],
                                "checked_at": _iso(row["checked_at"]),
                            }
                        ]
                    )
                if (
                    not leader
                    and not DeviationChecker.objects.filter(
                        deviation_id=deviation_id, staff_id=actor_id
                    ).exists()
                ):
                    raise errors.NotChecker()
            _deviation_failure(deviation_id, expected_version, "DOC-DVK-02a")
    return _deviation_detail(deviation_id)
