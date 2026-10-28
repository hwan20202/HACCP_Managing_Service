from django.urls import path

from . import api

urlpatterns = [
    # P16 묶음 ① 품목별 CCP(A01·A02)·변경 이력(A11)
    path("admin/item-ccp", api.item_ccp_list, name="api-admin-item-ccp"),
    path("admin/item-ccp/<int:item_id>", api.item_ccp_item, name="api-admin-item-ccp-item"),
    path("admin/history", api.history, name="api-admin-history"),
]
