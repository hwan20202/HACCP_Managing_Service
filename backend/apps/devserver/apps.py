from django.apps import AppConfig


class DevserverConfig(AppConfig):
    name = "apps.devserver"
    label = "devserver"
    verbose_name = "개발 서버 보조(개발 설정 전용)"
