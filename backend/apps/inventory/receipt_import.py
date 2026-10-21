"""Atomic receipt import. Preview runs the same validations in a rolled-back transaction."""

from django.db import transaction

from . import serializers
from .bom_management import integer, quantity
from .errors import InventoryError
from .models import Item, Supplier
from .quantity import from_e6


def import_receipts(data):
    from .api import create_receipt

    rows = data.get("rows")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 500:
        raise InventoryError("입고 내역은 한 번에 1~500건 업로드하세요.")
    staff_id = integer(data.get("staff_id"), "담당자")
    key = str(data.get("idempotency_key") or "")
    if not key or len(key) > 100:
        raise InventoryError("업로드 요청 키가 필요합니다.")
    dry_run = data.get("dry_run", True)
    if not isinstance(dry_run, bool):
        raise InventoryError("미리보기 여부를 확인하세요.")
    results = []
    with transaction.atomic():
        for index, row in enumerate(rows, 2):
            if not isinstance(row, dict):
                raise InventoryError(f"{index}행: 입고 형식을 확인하세요.")
            item = Item.objects.filter(item_code=str(row.get("item_code") or "").strip()).first()
            supplier = Supplier.objects.filter(
                supplier_code=str(row.get("supplier_code") or "").strip()
            ).first()
            if item is None or supplier is None:
                raise InventoryError(f"{index}행: 등록된 품목코드·공급처코드를 입력하세요.")
            try:
                amount = quantity(
                    row.get("quantity"), row.get("unit") or item.base_unit, item.base_unit
                )
                payload = {
                    **row,
                    "item_id": item.pk,
                    "supplier_id": supplier.pk,
                    "staff_id": staff_id,
                    "quantity": str(from_e6(amount)),
                    "idempotency_key": f"{key}:{index}",
                    "judgment": row.get("judgment") or "PASS",
                }
                receipt = create_receipt(payload)
                if (
                    receipt.supplier_id != supplier.pk
                    or str(receipt.received_date) != str(payload.get("received_date"))
                    or str(receipt.lot.expiration_date or "")
                    != str(payload.get("expiration_date") or "")
                ):
                    raise InventoryError("같은 업로드 요청 키의 입고 내용이 변경되었습니다.")
                results.append(serializers.receipt(receipt))
            except (InventoryError, ValueError, TypeError) as error:
                raise InventoryError(f"{index}행: {error}") from error
        if dry_run:
            transaction.set_rollback(True)
    return {"dry_run": dry_run, "count": len(results), "results": results}
