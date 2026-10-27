from apps.core.views import (
    home,
    live,
    print_page,
    prototype_data,
    prototype_standard,
    ready,
    system_test,
)
from django.conf import settings
from django.urls import include, path

urlpatterns = [
    path("", home, name="home"),
    path("test/", system_test, name="system-test"),
    path("print/", print_page, name="print-page"),  # P12 출력
    path("prototype/data.js", prototype_data, name="prototype-data"),
    path("setup_standard/<str:filename>", prototype_standard, name="prototype-standard"),
    path("health/live/", live, name="health-live"),
    path("health/ready/", ready, name="health-ready"),
    path("api/v1/inventory/", include("apps.inventory.urls")),
]
urlpatterns += [
    path("api/v1/", include("apps.documents.urls")),
    path("api/v1/", include("apps.approvals.urls")),
    path("api/v1/", include("apps.document_workflow.urls")),
    path("api/v1/", include("apps.doc_requirements.urls")),
    path("api/v1/", include("apps.production_log.urls")),  # P15 생산 기준정보
]

# 개발 콘솔 API는 개발 설정에서 켰을 때만 등록한다. 운영 설정에서는 경로 자체가 없다.
if settings.DEBUG and getattr(settings, "HACCP_DEV_CONSOLE", False):
    from apps.devtools.views import console_page

    urlpatterns += [
        path("dev/", console_page, name="dev-console"),
        path("api/dev/", include("apps.devtools.urls")),
    ]
