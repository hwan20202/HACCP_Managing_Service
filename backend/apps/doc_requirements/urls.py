from django.urls import path

from . import api

urlpatterns = [
    path("lots/<int:lot_id>/documents", api.lot_documents, name="api-lot-documents"),
    path("batches/<int:batch_id>/documents", api.batch_documents, name="api-batch-documents"),
    # P7 입고일 묶음 조회(REQ-A03)
    path("incoming-inspections", api.incoming_inspections, name="api-incoming-inspections"),
    # P8 주 묶음 조회(REQ-A04)
    path("periodic-bundles", api.periodic_bundles, name="api-periodic-bundles"),
]
