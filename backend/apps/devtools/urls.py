from django.urls import path

from . import views

urlpatterns = [
    path("snapshot", views.snapshot, name="dev-snapshot"),
    path("flows", views.flows, name="dev-flows"),
    path("flows/<str:flow_id>", views.flows, name="dev-flow"),
    path("traces/<str:trace_id>", views.trace_detail, name="dev-trace"),
]
