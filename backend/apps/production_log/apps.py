from django.apps import AppConfig


class ProductionLogConfig(AppConfig):
    name = "apps.production_log"
    label = "production_log"
    verbose_name = "생산일지(P15 PLG)"

    def ready(self):
        from . import logbook

        logbook.register()  # DOC 양식 확장(N12): PROD-LOG 저장·작성완료 검사, 작성완료·재개 처리
