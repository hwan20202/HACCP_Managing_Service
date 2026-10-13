from django.apps import AppConfig


class DocumentWorkflowConfig(AppConfig):
    name = "apps.document_workflow"
    label = "document_workflow"
    verbose_name = "문서 워크플로우"

    def ready(self):
        from . import checks  # noqa: F401 — 시스템 점검 등록(P7-NFR-06)
