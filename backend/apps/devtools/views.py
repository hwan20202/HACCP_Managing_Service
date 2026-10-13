"""개발 콘솔용 읽기 전용 API (/api/dev/). 허용 목록 테이블만, 문서 단위로 읽는다."""

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_safe

from apps.approvals.flows import FLOWS as APR_FLOWS
from apps.approvals.models import Approval, ApprovalRequest
from apps.doc_effects.flows import FLOWS as EFF_FLOWS
from apps.doc_requirements.flows import FLOWS as REQ_FLOWS
from apps.document_workflow.flows import FLOWS as WF_FLOWS
from apps.documents.flows import FLOWS as DOC_FLOWS
from apps.documents.models import (
    DeviationAction,
    DeviationChecker,
    DocSection,
    Document,
    DocumentCorrection,
    DocumentRef,
    DocumentTemplate,
)

from .middleware import recall

FLOWS = {**DOC_FLOWS, **APR_FLOWS, **WF_FLOWS, **REQ_FLOWS, **EFF_FLOWS}


def _plain(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _rows(queryset):
    return [{key: _plain(value) for key, value in row.items()} for row in queryset.values()]


def _json(data, status=200):
    return JsonResponse(data, status=status, json_dumps_params={"ensure_ascii": False})


def _sql_rows(sql, params):
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        names = [c[0] for c in cursor.description]
        return [dict(zip(names, row)) for row in cursor.fetchall()]


def _scope_snapshot(kind, target_ids, scope):
    """P5 작성 요구 ④ 패널: LOT·배치(들)에 걸린 행. 수불 임시 테이블은 devstock이 있을 때만.

    scope가 날짜면(received_date·manufactured_date) 그날의 LOT·배치 전부를 본다 — 새 LOT을 만드는
    호출은 실행 전에 LOT id가 없어서, 그날 이미 있던 D03 같은 문서를 실행 전에 찍어 두려면 날짜로
    범위를 잡아야 한다(P5 S6-39 K1).
    """
    from django.apps import apps as django_apps

    column = "lot_id" if kind == "lot" else "production_batch_id"
    refs_of_target = DocumentRef.objects.filter(**{f"{column}__in": target_ids})
    doc_ids = sorted(set(refs_of_target.values_list("document_id", flat=True)))
    tables = {
        "document": _rows(Document.objects.filter(pk__in=doc_ids).order_by("document_id")),
        "doc_section": _rows(
            DocSection.objects.filter(document_id__in=doc_ids).order_by("section_id")
        ),
        "document_ref": _rows(
            DocumentRef.objects.filter(document_id__in=doc_ids).order_by("ref_id")
        ),
    }
    if django_apps.is_installed("apps.devstock"):
        marks = ", ".join(["%s"] * len(target_ids)) or "NULL"
        if kind == "lot":
            tables["lots"] = _sql_rows(f"SELECT * FROM lots WHERE id IN ({marks})", target_ids)
            tables["dev_lot_receipts"] = _sql_rows(
                f"SELECT * FROM dev_lot_receipts WHERE lot_id IN ({marks})", target_ids
            )
        else:
            tables["production_batches"] = _sql_rows(
                f"SELECT * FROM production_batches WHERE id IN ({marks})", target_ids
            )
            tables["dev_batch_plans"] = _sql_rows(
                f"SELECT * FROM dev_batch_plans WHERE production_batch_id IN ({marks})",
                target_ids,
            )
    exists = bool(tables.get("lots") or tables.get("production_batches"))
    return _json({"scope": scope, "exists": exists, "tables": tables})


def _ids_on(kind, day):
    """그날 입고된 LOT id·그날 생산 배치 id(devstock 테이블). devstock이 없으면 빈 목록."""
    from django.apps import apps as django_apps

    if not django_apps.is_installed("apps.devstock"):
        return []
    if kind == "lot":
        sql = "SELECT lot_id FROM dev_lot_receipts WHERE received_date = %s ORDER BY lot_id"
    else:
        sql = "SELECT id FROM production_batches WHERE manufactured_date = %s ORDER BY id"
    return [row[next(iter(row))] for row in _sql_rows(sql, [day])]


def _valid_day(value):
    import datetime

    try:
        return len(value) == 10 and datetime.date.fromisoformat(value) is not None
    except ValueError:
        return False


@require_safe
def snapshot(request):
    for kind, key in (("lot", "lot_id"), ("batch", "batch_id")):
        if key in request.GET:
            value = request.GET[key]
            if not value.isdigit():
                return _json({"code": "INVALID_REQUEST", "message": f"{key}는 숫자입니다."}, 400)
            return _scope_snapshot(kind, [int(value)], {kind: int(value)})
    for kind, key in (("lot", "received_date"), ("batch", "manufactured_date")):
        if key in request.GET:
            value = request.GET[key]
            if not _valid_day(value):
                return _json(
                    {"code": "INVALID_REQUEST", "message": f"{key}는 YYYY-MM-DD입니다."}, 400
                )
            return _scope_snapshot(kind, _ids_on(kind, value), {key: value})
    raw = request.GET.get("document_id", "")
    if not raw.isdigit():
        return _json({"code": "INVALID_REQUEST", "message": "document_id가 필요합니다."}, 400)
    document_id = int(raw)
    # 논리 삭제된 문서도 포함한다(삭제 결과를 확인하기 위해).
    documents = _rows(Document.objects.filter(pk=document_id))
    if not documents:
        return _json({"document_id": document_id, "exists": False, "tables": {}})
    document = documents[0]
    sections = _rows(DocSection.objects.filter(document_id=document_id).order_by("section_id"))
    template = _rows(DocumentTemplate.objects.filter(pk=document["template_id"]))
    requests = _rows(
        ApprovalRequest.objects.filter(document_id=document_id)
        .defer("snapshot_json")
        .order_by("attempt")
    )
    for row in requests:
        row.pop("snapshot_json", None)
    slots = _rows(
        Approval.objects.filter(request__document_id=document_id).order_by("request_id", "slot_no")
    )
    # P4: 업무 대상 참조·개선조치(파일 두 테이블은 스프린트 3 기능이라 아직 비교하지 않는다)
    refs = _rows(DocumentRef.objects.filter(document_id=document_id).order_by("ref_id"))
    deviations = _rows(
        DeviationAction.objects.filter(document_id=document_id).order_by("deviation_id")
    )
    checkers = _rows(
        DeviationChecker.objects.filter(deviation__document_id=document_id).order_by(
            "deviation_id", "staff_id"
        )
    )
    # P6: 정정 기록
    corrections = _rows(
        DocumentCorrection.objects.filter(document_id=document_id).order_by("correction_id")
    )
    staff_ids = sorted(
        {
            document[k]
            for k in ("created_by_id", "assignee_id", "deleted_by_id", "completed_by_id")
            if document[k]
        }
        | {row["recorded_by_id"] for row in sections if row["recorded_by_id"]}
        | {row["requested_by_id"] for row in requests}
        | {row["approver_id"] for row in slots}
        | {
            row[k]
            for row in deviations
            for k in ("actor_id", "created_by_id", "updated_by_id", "deleted_by_id")
            if row[k]
        }
        | {row["staff_id"] for row in checkers}
        | {
            row[k]
            for row in corrections
            for k in ("started_by_id", "prev_completed_by_id")
            if row[k]
        }
    )
    tables = {
        "document": documents,
        "doc_section": sections,
        "document_template": template,
        "staff": [{"staff_id": i} for i in staff_ids],
        "approval_request": requests,
        "approval": slots,
        "document_ref": refs,
        "deviation_action": deviations,
        "deviation_checker": checkers,
        "document_correction": corrections,
    }
    # P6 S5: 참조 LOT의 상태(판정 전달 EFF 결과 확인) — 개발용 수불 테이블이 있을 때만
    from django.apps import apps as django_apps

    lot_ids = sorted({row["lot_id"] for row in refs if row["lot_id"]})
    if django_apps.is_installed("apps.devstock") and lot_ids:
        marks = ", ".join(["%s"] * len(lot_ids))
        tables["lots"] = _sql_rows(f"SELECT * FROM lots WHERE id IN ({marks})", lot_ids)
    return _json(
        {
            "document_id": document_id,
            "exists": True,
            "deleted": document["deleted_at"] is not None,
            "tables": tables,
        }
    )


@require_safe
def flows(request, flow_id=None):
    if flow_id is None:
        return _json({"flows": FLOWS})
    if flow_id not in FLOWS:
        return _json({"code": "NOT_FOUND", "message": "알 수 없는 흐름입니다."}, 404)
    return _json({"flow_id": flow_id, "steps": FLOWS[flow_id]})


@require_safe
def trace_detail(request, trace_id):
    data = recall(trace_id)
    if data is None:
        return _json({"code": "NOT_FOUND", "message": "trace가 없거나 만료되었습니다."}, 404)
    return _json(data)


@require_safe
def console_page(request):
    return render(request, "dev_console.html")
