"""문서 도메인 서비스 (s2-spec 4.1, 흐름은 s2-flows.md).

- 상태 판단은 EDITABLE / DELETABLE 두 집합만 본다(DOC-FR-12).
- 쓰기 기능은 트랜잭션의 첫 SQL을 조건부 UPDATE로 해서 검사와 잠금을 한 번에 한다(DOC-NFR-02).
- step("DOC-…") 단계 ID는 흐름 도식과 같다. 개발 설정에서만 기록된다.
- 이 모듈은 결재(apps.approvals)·워크플로우(apps.document_workflow)를 import하지 않는다.
"""

import json

from django.db import IntegrityError, models, transaction
from django.db.models import F, Func, OuterRef, Subquery, Value
from django.utils import timezone

from apps.core.http import ApiError
from apps.core.trace import step
from apps.staff import services as staff_services
from apps.staff.models import Staff

from . import errors, validation
from .models import STATUS_CHOICES, DocSection, Document, DocumentTemplate

EDITABLE = ("draft", "rejected")
DELETABLE = ("draft",)  # 그리고 submitted_at IS NULL (한 번도 상신하지 않은 문서)
PAGE_SIZE = 20
MAX_RANGE_DAYS = 366
EDITABLE_FIELDS = ("subject", "work_date", "assignee_id", "due_at")


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
    }


def _section_row(row):
    return {
        "section_id": row.section_id,
        "section_def": row.section_def,
        "row_no": row.row_no,
        "values": row.values_json,
        "recorded_at": _iso(row.recorded_at),
        "recorded_by": row.recorded_by_id,
    }


def _assemble(document, rows):
    order = validation.section_order(document.template.schema_json)
    rows = sorted(rows, key=lambda r: (order.get(r.section_def, len(order)), r.row_no))
    data = _document_head(document)
    data["sections"] = [_section_row(r) for r in rows]
    return data


def _detail(document_id):
    document = Document.objects.select_related("template").get(pk=document_id)
    return _assemble(document, list(DocSection.objects.filter(document_id=document_id)))


# ---------------------------------------------------------------- F01~F03 조회


def list_staff():
    with step("DOC-STF-01", "DOC", "staff 목록"):
        return list(Staff.objects.order_by("staff_id").values_list("staff_id", flat=True))


def list_templates():
    with step("DOC-TPL-01", "DOC", "최신 활성 양식 목록"):
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
        template_id = _int_filter(filters, "template_id", problems)
        author_id = _int_filter(filters, "author_id", problems)
        assignee_id = _int_filter(filters, "assignee_id", problems)
        page_number = _int_filter({"page": page}, "page", problems) or 1
        if page_number < 1 or page in (0, "0"):
            problems.append(validation.error("page", "invalid", "1 이상이어야 합니다."))
        if problems:
            raise errors.InvalidFilter(details=problems)

    queryset = Document.objects.filter(deleted_at__isnull=True)
    if date_from:
        queryset = queryset.filter(work_date__gte=date_from)
    if date_to:
        queryset = queryset.filter(work_date__lte=date_to)
    if status:
        queryset = queryset.filter(status=status)
    if template_id is not None:
        queryset = queryset.filter(template_id=template_id)
    if author_id is not None:
        queryset = queryset.filter(created_by_id=author_id)
    if assignee_id is not None:
        queryset = queryset.filter(assignee_id=assignee_id)

    with step("DOC-LST-02", "DOC", "건수"):
        total = queryset.count()
    with step("DOC-LST-03", "DOC", "페이지 조회"):
        offset = (page_number - 1) * PAGE_SIZE
        documents = list(
            queryset.select_related("template").order_by("-work_date", "-document_id")[
                offset : offset + PAGE_SIZE
            ]
        )
    with step("DOC-LST-04", "DOC", "결과 조립"):
        return {
            "items": [_document_head(d) for d in documents],
            "total": total,
            "page": page_number,
            "page_size": PAGE_SIZE,
        }


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
    with step("DOC-GET-02", "DOC", "섹션 행 조회"):
        rows = list(DocSection.objects.filter(document_id=document_id))
    with step("DOC-GET-03", "DOC", "조립"):
        return _assemble(document, rows)


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
            row_errors, _ = validation.check_values(schema_sections[key], values, f"{path}.values")
            problems += row_errors
            counts[key] += 1
            by_section[key].append((f"{path}.values", values))
            new_rows.append((key, counts[key], values))
        for key, section in schema_sections.items():
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


def _lock_failure(document_id, step_id, *, deletable=False, expected_version=None):
    """조건부 UPDATE가 0행일 때 이유를 구분한다: 404 → 409 상태 → 409 버전 순서."""
    with step(step_id, "DOC", "잠금 실패 사유 확인"):
        row = (
            Document.objects.filter(pk=document_id)
            .values("status", "deleted_at", "submitted_at", "version", "updated_at")
            .first()
        )
        if row is None or row["deleted_at"] is not None:
            raise errors.DocumentNotFound()
        if deletable:
            raise errors.DocumentNotDeletable()
        if row["status"] in EDITABLE and expected_version is not None:
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
                staff_pairs = []
                if basic.get("assignee_id") is not None:
                    staff_pairs.append(("document.assignee_id", basic["assignee_id"]))
                final = {
                    sid: (f"section_id:{sid}", r.section_def, r.values_json)
                    for sid, r in current.items()
                }
                for sid in deletes:
                    key = current[sid].section_def
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
                    values = item.get("values", {})
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


def lock_for_review(document_id, expected_version=None):
    """상신 잠금: draft/rejected → submitted. WF 트랜잭션 안에서만 호출한다.

    expected_version을 주면 화면이 본 버전과 같을 때만 잠근다(WF 변경 요청 C-1).
    """
    with step("DOC-LCK-00", "DOC", "트랜잭션 확인"):
        _require_transaction()
    now = timezone.now()
    with step("DOC-LCK-01", "DOC", "상신 잠금(조건부 UPDATE)") as s:
        filters = {"pk": document_id, "deleted_at__isnull": True, "status__in": EDITABLE}
        if expected_version is not None:
            filters["version"] = expected_version
        changed = Document.objects.filter(**filters).update(
            status="submitted", submitted_at=now, updated_at=now, version=F("version") + 1
        )
        s.note(f"영향 행 {changed}")
    if changed == 0:
        _lock_failure(document_id, "DOC-LCK-01a", expected_version=expected_version)
    with step("DOC-LCK-02", "DOC", "결과"):
        return _lifecycle_result(document_id)


def mark_approved(document_id):
    """승인 확정: submitted → approved. WF 트랜잭션 안에서만 호출한다."""
    _require_transaction()
    with step("DOC-APV-01", "DOC", "승인 확정(조건부 UPDATE)") as s:
        changed = Document.objects.filter(
            pk=document_id, deleted_at__isnull=True, status="submitted"
        ).update(status="approved", updated_at=timezone.now(), version=F("version") + 1)
        s.note(f"영향 행 {changed}")
    if changed == 0:
        _transition_failure(document_id, "DOC-APV-01a")
    with step("DOC-APV-02", "DOC", "결과"):
        return _lifecycle_result(document_id)


def mark_rejected(document_id):
    """반려: submitted → rejected. WF 트랜잭션 안에서만 호출한다."""
    _require_transaction()
    with step("DOC-RJT-01", "DOC", "반려(조건부 UPDATE)") as s:
        changed = Document.objects.filter(
            pk=document_id, deleted_at__isnull=True, status="submitted"
        ).update(status="rejected", updated_at=timezone.now(), version=F("version") + 1)
        s.note(f"영향 행 {changed}")
    if changed == 0:
        _transition_failure(document_id, "DOC-RJT-01a")
    with step("DOC-RJT-02", "DOC", "결과"):
        return _lifecycle_result(document_id)
