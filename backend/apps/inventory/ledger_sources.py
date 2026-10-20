"""Read-only navigation context for ledger rows; quantities remain owned by ledger.py."""

from .models import IncomingReceipt, ProductionMaterialUsage, ProductionOutput


def attach_sources(items):
    lines = [line for item in items for lot in item["lots"] for line in lot["lines"]]
    roots = {line["corrects_movement_id"] or line["movement_id"] for line in lines}
    lot_ids = {lot["lot_id"] for item in items for lot in item["lots"]}
    receipts = {row.lot_id: row for row in IncomingReceipt.objects.filter(lot_id__in=lot_ids)}
    batches = {}
    for model in (ProductionMaterialUsage, ProductionOutput):
        for row in model.objects.filter(stock_movement_id__in=roots).select_related("batch"):
            batches[row.stock_movement_id] = {"id": row.batch_id, "number": row.batch.batch_number}
    for item in items:
        for lot in item["lots"]:
            for line in lot["lines"]:
                root = line["corrects_movement_id"] or line["movement_id"]
                line["source"] = {
                    "receipt_id": receipts[lot["lot_id"]].pk if lot["lot_id"] in receipts else None,
                    "receipt_status": receipts[lot["lot_id"]].receipt_status
                    if lot["lot_id"] in receipts
                    else None,
                    "batch": batches.get(root),
                }
    return items
