from django.urls import path

from . import api

urlpatterns = [
    path("documents/<int:document_id>/submit", api.submit, name="wf-submit"),
    path("approvals/<int:approval_id>/decision", api.decision, name="wf-decision"),
    # P7 일괄 (p7-s2-spec 3.1)
    path("approvals/batch-decision", api.batch_decision, name="wf-batch-decision"),
    path("documents/batch-submit", api.batch_submit, name="wf-batch-submit"),
    path("workflow/batch-config", api.batch_config, name="wf-batch-config"),
    # P10 상신 취소(WF-F05)
    path(
        "approval-requests/<int:request_id>/cancel",
        api.cancel_submission,
        name="wf-cancel-submission",
    ),
    # P12 출력(WF-A06)
    path("print/sheet", api.print_sheet, name="wf-print-sheet"),
]
