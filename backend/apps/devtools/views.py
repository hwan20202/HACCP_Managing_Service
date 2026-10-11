"""개발 콘솔용 읽기 전용 API (/api/dev/). 허용 목록 테이블만, 문서 단위로 읽는다."""

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_safe

from apps.approvals.flows import FLOWS as APR_FLOWS
from apps.approvals.models import Approval, ApprovalRequest
from apps.doc_requirements.flows import FLOWS as REQ_FLOWS
from apps.document_workflow.flows import FLOWS as WF_FLOWS
from apps.documents.flows import FLOWS as DOC_FLOWS
from apps.documents.models import (
    DeviationAction,
    DeviationChecker,
    DocSection,
    Document,
    DocumentRef,
    DocumentTemplate,
)

from .middleware import recall

FLOWS = {**DOC_FLOWS, **APR_FLOWS, **WF_FLOWS, **REQ_FLOWS}


def _plain(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _rows(queryset):
    return [{key: _plain(value) for key, value in row.items()} for row in queryset.values()]


def _json(data, status=200):
    return JsonResponse(data, status=status, json_dumps_params={"ensure_ascii": False})


@require_safe
def snapshot(request):
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
    )
    return _json(
        {
            "document_id": document_id,
            "exists": True,
            "deleted": document["deleted_at"] is not None,
            "tables": {
                "document": documents,
                "doc_section": sections,
                "document_template": template,
                "staff": [{"staff_id": i} for i in staff_ids],
                "approval_request": requests,
                "approval": slots,
                "document_ref": refs,
                "deviation_action": deviations,
                "deviation_checker": checkers,
            },
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
