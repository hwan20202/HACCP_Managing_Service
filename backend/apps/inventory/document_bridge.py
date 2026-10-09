"""Outgoing notifications to the document domain (contract C3).

How these reach the document app is still open (question 5: domain_event rows vs. direct
service calls). The receiving service calls these functions inside its transaction, so
whichever way is chosen, only the bodies below change and a failure rolls the receipt back.

Payload shapes follow C3 so either transport can use them as-is.
"""

EVENT_VERSION = 1


def incoming_received_payload(receipt):
    lot = receipt.lot
    item = lot.item
    return {
        "event_version": EVENT_VERSION,
        "subject_type": "LOT",
        "subject_id": str(lot.pk),
        "lot_id": lot.pk,
        "lot_number": lot.lot_number,
        "item_code": item.item_code,
        "item_name": item.name,
        "item_type": item.item_type_id,
        "supplier_name": receipt.supplier.name,
        "supplier_lot_number": receipt.supplier_lot_number,
        "received_date": receipt.received_date.isoformat(),
        "quantity_e6": receipt.quantity_e6,
        "unit": item.base_unit,
        "manufactured_date": lot.manufactured_date and lot.manufactured_date.isoformat(),
        "expiration_date": lot.expiration_date and lot.expiration_date.isoformat(),
    }


def incoming_receipt_cancelled_payload(receipt):
    return {
        "event_version": EVENT_VERSION,
        "subject_type": "LOT",
        "subject_id": str(receipt.lot_id),
        "lot_id": receipt.lot_id,
        "reason": receipt.cancel_reason,
    }


def notify_incoming_received(receipt):
    """INCOMING_RECEIVED. Not connected yet: transport decided with the document team."""
    incoming_received_payload(receipt)


def notify_incoming_receipt_cancelled(receipt):
    """INCOMING_RECEIPT_CANCELLED. Not connected yet: transport decided with the document team."""
    incoming_receipt_cancelled_payload(receipt)
