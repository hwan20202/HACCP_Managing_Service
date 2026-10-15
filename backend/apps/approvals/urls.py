from django.urls import path

from . import api

urlpatterns = [
    path("approval-inbox", api.approval_inbox, name="api-approval-inbox"),
    path("approval-requests/<int:request_id>", api.request_detail, name="api-approval-request"),
    path(
        "documents/<int:document_id>/approval-requests",
        api.document_requests,
        name="api-document-approval-requests",
    ),
]
