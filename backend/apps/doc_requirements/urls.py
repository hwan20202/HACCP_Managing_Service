from django.urls import path

from . import api

urlpatterns = [
    path("lots/<int:lot_id>/documents", api.lot_documents, name="api-lot-documents"),
    path("batches/<int:batch_id>/documents", api.batch_documents, name="api-batch-documents"),
    # P7 입고일 묶음 조회(REQ-A03)
    path("incoming-inspections", api.incoming_inspections, name="api-incoming-inspections"),
    # P8 주 묶음 조회(REQ-A04)
    path("periodic-bundles", api.periodic_bundles, name="api-periodic-bundles"),
    # P9 주기형 작성 요구(REQ-A05~A07)
    path("periodic-runs", api.periodic_runs, name="api-periodic-runs"),
    path("periodic-documents", api.periodic_documents, name="api-periodic-documents"),
    path("periodic-rules", api.periodic_rules, name="api-periodic-rules"),
    # P10 작성 필요 목록(REQ-A08)
    path("todo", api.todo_list, name="api-todo"),
]
