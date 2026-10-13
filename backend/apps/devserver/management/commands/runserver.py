"""개발 설정 전용 runserver: 정적 파일 핸들러만 no-cache 버전으로 바꾼다.

Django는 INSTALLED_APPS에서 앞에 있는 앱의 명령을 쓴다. development.py가 이 앱을 맨 앞에 둔다.
"""

from django.contrib.staticfiles.handlers import StaticFilesHandler
from django.contrib.staticfiles.management.commands.runserver import Command as StaticRunserver

from apps.devserver.handlers import NoCacheStaticFilesHandler


class Command(StaticRunserver):
    help = StaticRunserver.help + " (개발 설정: 정적 파일에 Cache-Control: no-cache)"

    def get_handler(self, *args, **options):
        handler = super().get_handler(*args, **options)
        if isinstance(handler, StaticFilesHandler):
            return NoCacheStaticFilesHandler(handler.application)
        return handler
