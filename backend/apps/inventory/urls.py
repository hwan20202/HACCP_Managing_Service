from django.urls import path

from . import api, exports

app_name = "inventory"

urlpatterns = [
    path("item-types/", api.item_types, name="item-types"),
    path("movement-types/", api.movement_types, name="movement-types"),
    path("staff/", api.staff_collection, name="staff"),
    path("staff/<int:pk>/", api.staff_detail, name="staff-detail"),
    path("suppliers/", api.supplier_collection, name="suppliers"),
    path("suppliers/<int:pk>/", api.supplier_detail, name="supplier-detail"),
    path("items/", api.item_collection, name="items"),
    path("items/<int:pk>/", api.item_detail, name="item-detail"),
    path("receipts/", api.receipt_collection, name="receipts"),
    path("receipts/<int:pk>/", api.receipt_detail, name="receipt-detail"),
    path("receipts/<int:pk>/cancel/", api.receipt_cancel, name="receipt-cancel"),
    path("lots/<int:pk>/", api.lot_detail, name="lot-detail"),
    path("stock/lots/", api.stock_lots, name="stock-lots"),
    path("stock/items/", api.stock_items, name="stock-items"),
    path("ledger/", api.ledger, name="ledger"),
    path("ledger/export.csv", exports.ledger_csv, name="ledger-csv"),
    path("movements/opening-balance/", api.opening_balance, name="opening-balance"),
    path("movements/adjust/", api.adjust, name="adjust"),
    path("movements/return/", api.return_view, name="return"),
    path("movements/disposal/", api.disposal_view, name="disposal"),
    path("movements/<int:pk>/correct/", api.correct, name="correct"),
]
