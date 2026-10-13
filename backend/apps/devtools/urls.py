from django.apps import apps
from django.urls import path

from . import views

urlpatterns = [
    path("snapshot", views.snapshot, name="dev-snapshot"),
    path("flows", views.flows, name="dev-flows"),
    path("flows/<str:flow_id>", views.flows, name="dev-flow"),
    path("traces/<str:trace_id>", views.trace_detail, name="dev-trace"),
]

# P5 작성 요구 테스트(REQ-D01~D07): devstock(개발용 수불 임시 테이블)이 있을 때만
if apps.is_installed("apps.devstock"):
    from . import fixtures, req_api

    urlpatterns += [
        path("req/lots", req_api.lot_collection, name="dev-req-lots"),
        path("req/batches", req_api.batch_collection, name="dev-req-batches"),
        path("req/items", req_api.item_list, name="dev-req-items"),
        path("req/lots/<int:lot_id>/require", req_api.lot_require, name="dev-req-lot-require"),
        path(
            "req/batches/<int:batch_id>/require",
            req_api.batch_require,
            name="dev-req-batch-require",
        ),
        # P6 S5: 프리셋 사전 조건(ISS-019)
        path("fixtures/d03", fixtures.d03_fixture, name="dev-fixture-d03"),
    ]
