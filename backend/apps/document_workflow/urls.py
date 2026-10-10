from django.urls import path

from . import api

urlpatterns = [
    path("documents/<int:document_id>/submit", api.submit, name="wf-submit"),
    path("approvals/<int:approval_id>/decision", api.decision, name="wf-decision"),
]
