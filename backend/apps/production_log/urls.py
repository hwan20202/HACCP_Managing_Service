from django.urls import path

from . import api

urlpatterns = [
    path("processes", api.processes, name="api-processes"),
    path("processes/<int:process_id>", api.process_item, name="api-process"),
    path("processes/<int:process_id>/active", api.process_active, name="api-process-active"),
    path("process-templates", api.templates, name="api-process-templates"),
    path("process-templates/<int:template_id>", api.template_item, name="api-process-template"),
    path(
        "process-templates/<int:template_id>/copy",
        api.template_copy,
        name="api-process-template-copy",
    ),
    path(
        "process-templates/<int:template_id>/active",
        api.template_active,
        name="api-process-template-active",
    ),
    path("master-history", api.master_history, name="api-master-history"),
    # S4b 생산일지(A01~A05)
    path(
        "production-logs/<int:document_id>/linked",
        api.production_log_linked,
        name="api-production-log-linked",
    ),
    path(
        "production-logs/<int:document_id>/template-rows",
        api.production_log_template_rows,
        name="api-production-log-template-rows",
    ),
    path(
        "production-logs/<int:document_id>/save-template",
        api.production_log_save_template,
        name="api-production-log-save-template",
    ),
    path(
        "production-logs/<int:document_id>/ccp-values",
        api.production_log_ccp_values,
        name="api-production-log-ccp-values",
    ),
    path(
        "production-logs/<int:document_id>/register-process",
        api.production_log_register_process,
        name="api-production-log-register-process",
    ),
]
