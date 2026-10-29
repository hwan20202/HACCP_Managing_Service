from django.urls import path

from . import api

urlpatterns = [
    # P16 묶음 ① 품목별 CCP(A01·A02)·변경 이력(A11)
    path("admin/item-ccp", api.item_ccp_list, name="api-admin-item-ccp"),
    path("admin/item-ccp/<int:item_id>", api.item_ccp_item, name="api-admin-item-ccp-item"),
    path("admin/history", api.history, name="api-admin-history"),
    # P16 묶음 ② 직원(A03~A06·A08)·문서 권한(A09·A10)
    path("admin/staff", api.staff_collection, name="api-admin-staff"),
    path("admin/staff/next-code", api.staff_next_code, name="api-admin-staff-next-code"),
    path("admin/staff/<int:staff_id>", api.staff_item, name="api-admin-staff-item"),
    path("admin/staff/<int:staff_id>/active", api.staff_active, name="api-admin-staff-active"),
    path("admin/roles", api.roles_view, name="api-admin-roles"),
]
