"""테스트 전용 URLConf: 개발 콘솔이 켜진 상태를 흉내 낸다."""

from config.urls import urlpatterns as base_patterns
from django.urls import include, path

urlpatterns = [*base_patterns, path("api/dev/", include("apps.devtools.urls"))]
