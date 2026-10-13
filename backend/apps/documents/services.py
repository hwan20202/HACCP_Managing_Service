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
from apps.staff import services as staff_services

from . import errors, signals, validation
from .models import (
    STATUS_CHOICES,
    DeviationAction,
    DeviationChecker,
    DocSection,
    Document,
    DocumentCorrection,
    DocumentFile,
    DocumentRef,
    DocumentTemplate,
)

EDITABLE = ("draft", "rejected", "correcting")  # P6: 정정 중도 수정·작성완료(P6-FR-04)
COMPLETABLE = ("draft", "rejected", "correcting")
REOPENABLE = ("completed",)  # 목적지: 열린 정정이 있으면 correcting, 없으면 draft(P6-FR-05)
LOCKABLE = ("completed",)  # 상신은 작성완료 상태에서만(P4-S2-Q1, D-055)
CORRECTABLE = ("approved",)  # 정정 시작(P6-FR-01)
ROW_APPENDABLE = ("draft", "rejected")  # N2 — P4 그대로(P6a: 정정 중 문서에 행 추가 경로 없음)
CORRECTION_REASON_MAX = 200
NOTE_MAX = 200  # 작성완료 메모(판정 변경 사유) — 저장하지 않고 신호로만(D-080, P6-VR-06)
DELETABLE = (
    "draft",
)  # 그리고 submitted_at IS NULL, record_key IS NULL(작성 요구 문서 삭제 불가 C-3)
REF_TARGETS = ("lot_id", "production_batch_id", "item_id", "process_code")
DEVIATION_MAX_CHECKERS = 10
PAGE_SIZE = 20
MAX_RANGE_DAYS = 366
EDITABLE_FIELDS = ("subject", "work_date", "assignee_id", "due_at")
# P7(p7-s2-spec 3.2, Q9): DOC가 양식 코드를 직접 아는 첫 예외 — 스키마 표시로 옮기는 일은 ISS-020
LIST_BUNDLE_TYPES = ("D03",)  # 목록에서 작업일마다 묶음 줄 1개
INSPECTOR_TYPES = ("D03",)  # 점검자 일괄 지정 대상(info.inspector)
BRIEF_MAX = 50


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
    """작성 요구 출처: record_key가 없으면 None, 배치 참조가 있으면 batch, 아니면 lot (F05)."""
    if not record_key:
        return None
    if any(r["production_batch_id"] is not None for r in refs):
        return "batch"
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
    for row in data["sections"]:
        if hints and row["section_id"] in hints:
            row["hints"] = hints[row["section_id"]]
    data["files"] = files or []
    data["deviations"] = deviations or []
    data["correction"], data["corrections"] = corrections or (None, [])
    info = next((r.values_json or {} for r in rows if r.section_def == "info"), {})
    data["target_summary"] = _target_summary(  # P7 DOC-F05 변경(ISS-018)
        document, refs, info.get("item_name"), info.get("supplier_name")
    )
    return data


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


def _hints(document, rows, refs):
    """필드 hint 규칙 계산(FR-28).

    file_exists: 같은 LOT의 지정 양식(D01) 문서에 파일이 있으면 "유". 저장 값은 바꾸지 않는다.
    LOT은 반복 섹션이면 그 행의 행 단위 참조,
    반복 아닌 섹션이면 문서 단위 참조(P6a-S2 2.3 — D03 v2).
    """
    rules = []
    for section in document.template.schema_json["sections"]:
        for field in section["fields"]:
            hint = field.get("hint")
            if isinstance(hint, dict) and hint.get("kind") == "file_exists":
                rules.append((section["key"], field["key"], hint, section.get("repeat", False)))
    if not rules:
        return {}
    row_lots = {r["section_id"]: r["lot_id"] for r in refs if r["section_id"] and r["lot_id"]}
    doc_lot = next((r["lot_id"] for r in refs if r["section_id"] is None and r["lot_id"]), None)
    result = {}
    for section_key, field_key, hint, repeat in rules:
        lot_by_section = (
            row_lots
            if repeat
            else {r.section_id: doc_lot for r in rows if r.section_def == section_key and doc_lot}
        )
        lots = [lot_by_section.get(r.section_id) for r in rows if r.section_def == section_key]
        lots = [lot for lot in lots if lot is not None]
        with_files = set()
        if lots:
            has_file = DocumentFile.objects.filter(document_id=OuterRef("document_id"))
            matched = Document.objects.filter(
                pk=OuterRef("document_id"),
                deleted_at__isnull=True,
                template__type_code=hint.get("type_code"),
            )
            with_files = set(
                DocumentRef.objects.filter(lot_id__in=lots, section_id__isnull=True)
                .filter(Exists(matched), Exists(has_file))
                .values_list("lot_id", flat=True)
            )
        for row in rows:
            if row.section_def == section_key and row.section_id in lot_by_section:
                value = "유" if lot_by_section[row.section_id] in with_files else "무"
                result.setdefault(row.section_id, {})[field_key] = value
    return result


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


def list_staff():
    with step("DOC-STF-01", "DOC", "staff 목록"):
        return staff_services.active_ids()


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
        assignee_id = _int_filter(filters, "assignee_id", problems)
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
        assignee_id=assignee_id,
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
                f"{_list_union(where, bundle_in)} ORDER BY 2 DESC, 1, 4 DESC LIMIT %s OFFSET %s",
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
            with connection_cursor() as cursor:
                cursor.execute(
                    "SELECT d.work_date, t.type_code, d.status, "
                    f"{_OPEN_CORRECTION_SQL} AS correcting, COUNT(*) "
                    "FROM document d JOIN document_template t ON t.template_id = d.template_id "
                    f"WHERE {where} AND t.type_code IN ({bundle_in}) AND d.work_date IN ({marks}) "
                    "GROUP BY 1, 2, 3, 4",
                    [*params, *bundle, *days],
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
            with connection_cursor() as cursor:
                cursor.execute(
                    "SELECT d.work_date, t.type_code, COUNT(*) FROM document d "
                    "JOIN document_template t ON t.template_id = d.template_id "
                    f"WHERE d.deleted_at IS NULL AND t.type_code IN ({bundle_in}) "
                    f"AND d.work_date IN ({marks}) GROUP BY 1, 2",
                    [*bundle, *days],
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
            items.append(
                {
                    "kind": "bundle",
                    "type_code": row[2],
                    "template_name": row[_COL_NAME],
                    "work_date": key[0],
                    "count": agg["count"],
                    "total": totals.get(key, agg["count"]) if filtered else agg["count"],
                    "status_counts": {k: v for k, v in agg["status"].items() if v},
                    "correcting_count": agg["correcting"],
                    "requirement": "lot",
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
        ("d.assignee_id", "assignee_id"),
    ):
        if f[key] is not None:
            where.append(f"{column} = %s")
            params.append(f[key])
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
    """문서 줄(kind 1)과 묶음 줄(kind 0, 작업일·양식 유형마다 1줄)의 UNION ALL."""
    columns = ["NULL"] if count_only else list(_LIST_COLUMNS)
    nulls = ["NULL"] * len(columns)
    if not count_only:
        nulls[_LIST_COLUMNS.index("t.name")] = "MAX(t.name)"
    source = "FROM document d JOIN document_template t ON t.template_id = d.template_id"
    return (
        f"SELECT 1 AS kind, d.work_date, t.type_code, d.document_id, {', '.join(columns)} "
        f"{source} WHERE {where} AND t.type_code NOT IN ({bundle_in}) "
        f"UNION ALL SELECT 0, d.work_date, t.type_code, MIN(d.document_id), {', '.join(nulls)} "
        f"{source} WHERE {where} AND t.type_code IN ({bundle_in}) "
        "GROUP BY t.type_code, d.work_date"
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


def create_document(actor_id, data):
    now = timezone.now()
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
    document_id, step_id, *, deletable=False, expected_version=None, allowed=EDITABLE
):
    """조건부 UPDATE가 0행일 때 이유를 구분한다: 404 → 409 상태 → 409 버전 순서.

    allowed: 그 기능이 허용하는 상태 집합(수정·작성완료는 EDITABLE, 상신 잠금은 LOCKABLE).
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
            if row["record_key"] is not None:
                reason, message = "requirement", "작성 요구로 만들어진 문서는 삭제할 수 없습니다."
            elif row["status"] not in DELETABLE:
                reason, message = "status", f"현재 상태: {row['status']}"
            else:
                reason, message = "submitted", "상신 이력이 있는 문서입니다."
            raise errors.DocumentNotDeletable(
                details=[{"path": "document", "code": reason, "reason": reason, "message": message}]
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


def delete_document(actor_id, document_id):
    now = timezone.now()
    with transaction.atomic():
        with step("DOC-DEL-02", "DOC", "삭제 표시(조건부 UPDATE)") as s:
            marked = Document.objects.filter(
                pk=document_id,
                deleted_at__isnull=True,
                status__in=DELETABLE,
                submitted_at__isnull=True,
                record_key__isnull=True,
            ).update(
                deleted_at=now, deleted_by_id=actor_id, updated_at=now, version=F("version") + 1
            )
            s.note(f"영향 행 {marked}")
        if marked == 0:
            _lock_failure(document_id, "DOC-DEL-02a", deletable=True)
    with step("DOC-DEL-03", "DOC", "완료"):
        return None


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
                document_id, "DOC-CMP-02a", expected_version=expected_version, allowed=COMPLETABLE
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


def create_deviation(actor_id, document_id, data):
    """개선조치 쓰기(F19). 문서 상태와 무관하다(D-054). 문서 버전은 바뀌지 않는다."""
    with step("DOC-DVC-01", "DOC", "형식 검사") as s:
        cleaned, problems = _clean_deviation(data, partial=False)
        if problems:
            s.fail(f"오류 {len(problems)}건")
            raise errors.ValidationFailed(details=problems)
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
    return _deviation_detail(deviation_id)


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


def update_deviation(actor_id, deviation_id, expected_version, patch):
    """개선조치 수정(F20). 문서를 잠그지 않고 개선조치 자기 version으로 충돌을 감지한다."""
    with step("DOC-DVU-01", "DOC", "형식 검사") as s:
        cleaned, problems = _clean_deviation(patch, partial=True)
        if not cleaned and not problems:
            problems = [validation.error("deviation", "no_changes", "바꿀 내용이 없습니다.")]
        if problems:
            s.fail(f"오류 {len(problems)}건")
            raise errors.ValidationFailed(details=problems)
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


def delete_deviation(actor_id, deviation_id, expected_version):
    """개선조치 삭제(논리, F21)."""
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
            staff_pairs += validation.staff_field_paths(section, values[key], f"values.{key}")
        _check_staff(staff_pairs, problems)
        if problems:
            s.fail(f"오류 {len(problems)}건")
            raise errors.ValidationFailed(details=problems)
    with step("DOC-GOC-03", "DOC", "1행 영역 행 만들기"):
        DocSection.objects.bulk_create(
            DocSection(
                document_id=document_id,
                section_def=key,
                row_no=1,
                values_json=validation.with_computed(section, values.get(key) or {}),
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


def _verdict_of(schema, values_by_key):
    """1행 섹션 중 필드 verdict가 있는 첫 섹션의 값과 부적합 여부. 없으면 (None, None)."""
    for section in _one_row_sections(schema):
        if any(f["key"] == "verdict" for f in section["fields"]):
            values = values_by_key.get(section["key"]) or {}
            return values.get("verdict"), validation.is_nonconforming(section, values)
    return None, None


def brief_documents(document_ids):
    """F26: 문서 요약 여러 건(≤50). SQL 3(문서·양식, 1행 섹션, 문서 단위 참조).

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
        values, refs = {}, {i: [] for i in found}
        if found:
            keys = {
                section["key"]
                for d in documents.values()
                for section in _one_row_sections(d.template.schema_json)
            }
            for document_id, key, row in DocSection.objects.filter(
                document_id__in=found, section_def__in=sorted(keys)
            ).values_list("document_id", "section_def", "values_json"):
                values.setdefault(document_id, {})[key] = row or {}
            for ref in DocumentRef.objects.filter(
                document_id__in=found, section_id__isnull=True
            ).order_by("ref_id"):
                refs[ref.document_id].append(_ref_row(ref))
        else:
            s.skip("문서 없음")
    with step("DOC-BRF-04", "DOC", "조립"):
        items = []
        for document_id in found:
            d = documents[document_id]
            own = values.get(document_id, {})
            info = own.get("info") or {}
            verdict, nonconforming = _verdict_of(d.template.schema_json, own)
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
                }
            )
        return {"items": items, "missing": [i for i in ids if i not in documents]}


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
            raise batch.not_batchable(wrong, "점검자 일괄 지정은 육안검사(D03)만 할 수 있습니다.")
    now = timezone.now()
    with step("DOC-BIN-03", "DOC", "트랜잭션") as tx:
        with transaction.atomic():
            results = batch.run_each(
                pairs,
                lambda pair: _set_inspector(actor_id, pair[0], pair[1], inspector_id, now),
                ident=lambda pair: {"document_id": pair[0]},
                layer="DOC",
                item_step="DOC-BIN-04",
            )
        tx.note(f"커밋: {sum(r['ok'] for r in results)}/{len(results)}")
    with step("DOC-BIN-07", "DOC", "결과 모음"):
        return batch.summary("inspector", results)


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
