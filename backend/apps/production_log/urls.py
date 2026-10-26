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
]
