from django.urls import path

from . import api

urlpatterns = [
    path("lots/<int:lot_id>/documents", api.lot_documents, name="api-lot-documents"),
    path("batches/<int:batch_id>/documents", api.batch_documents, name="api-batch-documents"),
]
