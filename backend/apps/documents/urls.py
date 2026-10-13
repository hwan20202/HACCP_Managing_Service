from django.urls import path

from . import api

urlpatterns = [
    path("staff", api.staff_list, name="api-staff-list"),
    path("templates", api.template_list, name="api-template-list"),
    path("templates/<int:template_id>", api.template_detail, name="api-template-detail"),
    path("documents", api.document_collection, name="api-document-collection"),
    # P7: 고정 경로(정수 경로와 겹치지 않음)
    path("documents/batch-inspector", api.batch_inspector, name="api-document-batch-inspector"),
    path("documents/brief", api.document_brief, name="api-document-brief"),
    path("documents/<int:document_id>", api.document_item, name="api-document-item"),
    path(
        "documents/<int:document_id>/complete", api.document_complete, name="api-document-complete"
    ),
    path("documents/<int:document_id>/reopen", api.document_reopen, name="api-document-reopen"),
    path(
        "documents/<int:document_id>/correction",
        api.document_correction,
        name="api-document-correction",
    ),
    path(
        "documents/<int:document_id>/correction/cancel",
        api.document_correction_cancel,
        name="api-document-correction-cancel",
    ),
    path(
        "documents/<int:document_id>/deviations",
        api.deviation_collection,
        name="api-deviation-collection",
    ),
    path("deviations/<int:deviation_id>", api.deviation_item, name="api-deviation-item"),
]
