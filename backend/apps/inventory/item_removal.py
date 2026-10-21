"""Remove unused items and receipt-only history, never production or shared documents."""

from django.db import connection, transaction
from django.db.models import Q
from django.db.models.deletion import Collector, ProtectedError

from apps.documents.models import Document, DocumentRef

from .bom_management import delete_bom, integer
from .errors import InventoryError
from .models import (
    AuditLog,
    Bom,
    BomLine,
    BomLineAlternative,
    Hold,
    IncomingReceipt,
    Item,
    Lot,
    ProductionBatch,
    ProductionMaterialUsage,
    ProductionOutput,
    StockMovement,
)
from .movements import _staff


def inspect_item(item):
    lots = list(Lot.objects.filter(item=item).values_list("pk", flat=True))
    if (
        ProductionBatch.objects.filter(item=item).exists()
        or ProductionMaterialUsage.objects.filter(lot_id__in=lots).exists()
        or ProductionOutput.objects.filter(lot_id__in=lots).exists()
        or BomLine.objects.filter(component_item=item).exclude(bom__item=item).exists()
        or BomLineAlternative.objects.filter(item=item).exists()
        or Hold.objects.filter(lot_id__in=lots).exists()
        or StockMovement.objects.filter(lot_id__in=lots)
        .exclude(movement_type_id__in=["RECEIPT", "CORRECTION_IN", "CORRECTION_OUT"])
        .exists()
        or Lot.objects.filter(pk__in=lots).exclude(lot_kind="INCOMING").exists()
    ):
        raise InventoryError("생산·BOM·보류 또는 다른 재고 업무에 사용된 품목입니다.")
    refs = DocumentRef.objects.filter(Q(lot_id__in=lots) | Q(item_id=item.pk))
    doc_ids = list(refs.values_list("document_id", flat=True).distinct())
    documents = Document.objects.filter(pk__in=doc_ids)
    if documents.exclude(status__in=["draft", "completed"]).exists():
        raise InventoryError("결재·정정 등에 사용된 문서가 있어 삭제할 수 없습니다.")
    # A document linking any other item/LOT/batch belongs to another business record.
    for ref in DocumentRef.objects.filter(document_id__in=doc_ids):
        if (
            ref.production_batch_id
            or ref.lot_id
            and ref.lot_id not in lots
            or ref.item_id
            and ref.item_id != item.pk
        ):
            raise InventoryError("다른 업무와 공유하는 문서가 있어 삭제할 수 없습니다.")
    try:
        collector = Collector(using=connection.alias)
        collector.collect(documents)
    except ProtectedError as error:
        raise InventoryError("문서 첨부·결재·개선조치 등 연결 기록을 먼저 확인하세요.") from error
    return {
        "id": item.pk,
        "item_code": item.item_code,
        "name": item.name,
        "lots": len(lots),
        "receipts": IncomingReceipt.objects.filter(lot_id__in=lots).count(),
        "movements": StockMovement.objects.filter(lot_id__in=lots).count(),
        "documents": len(doc_ids),
        "lot_ids": lots,
        "document_ids": doc_ids,
    }


@transaction.atomic
def remove_items(data):
    staff = _staff(integer(data.get("staff_id"), "담당자"))
    ids = data.get("item_ids")
    if not isinstance(ids, list) or not 1 <= len(ids) <= 500:
        raise InventoryError("삭제할 품목을 1~500개 선택하세요.")
    ids = [integer(value, "품목") for value in ids]
    if len(set(ids)) != len(ids):
        raise InventoryError("중복된 품목입니다.")
    dry_run = data.get("dry_run", True)
    if not isinstance(dry_run, bool):
        raise InventoryError("미리보기 여부를 확인하세요.")
    if not dry_run and data.get("confirmation") != "DELETE_UNUSED_ITEMS":
        raise InventoryError("삭제 미리보기 후 최종 확인이 필요합니다.")
    plans, blocked = [], []
    for pk in ids:
        item = Item.objects.filter(pk=pk).first()
        if item is None:
            blocked.append({"id": pk, "reason": "품목이 없습니다."})
            continue
        try:
            plans.append(inspect_item(item))
        except InventoryError as error:
            blocked.append({"id": pk, "name": item.name, "reason": str(error)})
    if blocked and not dry_run:
        raise InventoryError("삭제 불가 품목이 포함되어 있습니다. 미리보기에서 확인하세요.")
    if not dry_run:
        for plan in plans:
            doc_ids, lots = plan["document_ids"], plan["lot_ids"]
            DocumentRef.objects.filter(document_id__in=doc_ids).delete()
            Document.objects.filter(pk__in=doc_ids).delete()
            for bom_id in list(Bom.objects.filter(item_id=plan["id"]).values_list("pk", flat=True)):
                delete_bom(bom_id, {"staff_id": staff.pk})
            IncomingReceipt.objects.filter(lot_id__in=lots).delete()
            # SQL deletion is allowed only inside this transaction's scope. Ordinary ORM/API
            # movement deletion remains append-only, and DB triggers still reject used LOTs.
            with connection.cursor() as cursor:
                for lot_id in lots:
                    cursor.execute(
                        "INSERT INTO inventory_purge_scope(lot_id) VALUES (%s)", [lot_id]
                    )
                    cursor.execute(
                        "DELETE FROM stock_movements WHERE lot_id = %s "
                        "AND corrects_movement_id IS NOT NULL",
                        [lot_id],
                    )
                    cursor.execute("DELETE FROM stock_movements WHERE lot_id = %s", [lot_id])
                    cursor.execute("DELETE FROM inventory WHERE lot_id = %s", [lot_id])
                    cursor.execute("DELETE FROM inventory_purge_scope WHERE lot_id = %s", [lot_id])
                    cursor.execute("DELETE FROM lots WHERE id = %s", [lot_id])
                cursor.execute("DELETE FROM items WHERE id = %s", [plan["id"]])
            AuditLog.objects.create(
                table_name="items",
                record_id=str(plan["id"]),
                action="DELETE",
                before_json=plan,
                staff=staff,
                reason=str(data.get("reason") or "미사용 품목 및 입고 이력 삭제"),
            )
    public = [{k: v for k, v in p.items() if k not in ("lot_ids", "document_ids")} for p in plans]
    return {"dry_run": dry_run, "removable": public, "blocked": blocked}
