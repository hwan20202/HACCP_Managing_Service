from django.urls import path

from . import api

urlpatterns = [
    path("staff", api.staff_list, name="api-staff-list"),
    path("templates", api.template_list, name="api-template-list"),
    path("templates/<int:template_id>", api.template_detail, name="api-template-detail"),
    path("documents", api.document_collection, name="api-document-collection"),
    path("documents/<int:document_id>", api.document_item, name="api-document-item"),
]
