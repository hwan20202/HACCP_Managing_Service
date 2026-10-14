"""Calls from inventory into the document app (agreed: direct service calls, ids only).

Contract: docs/document-inventory-interface.md (document side) and
docs/inventory-document-interface.md (inventory side). The document app reads the data itself,
so these hooks pass identifiers, not payloads:
    incoming LOT     -> v_doc_incoming_lot by lot_id
    production batch -> v_doc_batch by production_batch_id
    stock ledger     -> apps.inventory.ledger.stock_ledger(...) by item + period

The hooks run inside the inventory transaction, after inventory has written its own rows:
if the document side raises (an ApiError), the inventory change rolls back too.

    receipt registered  -> doc_requirements.require_for_lot    (D01 · D02 · D03 per LOT)
    receipt cancelling  -> doc_requirements.docs_for_lot       (refused once a LOT document is
                                                                in approval — document side 4)
    receipt cancelled   -> nothing yet (document side has not decided; no-op hook)
    batch started       -> doc_requirements.require_for_batch  (CCP 일지 for MANUFACTURE)

The document functions are imported inside each hook so importing inventory does not load the
document apps.

domain_event (document app) is an outbox for external notification APIs, not a channel
between the two apps; inventory does not write to it.
"""

# Document states from which a receipt may no longer be cancelled (document side 4).
LOCKED_DOCUMENT_STATUSES = frozenset({"submitted", "approved", "correcting"})


def incoming_received(*, lot_id, staff_id, inspection=None):
    """A receipt (and its LOT) was registered: create the LOT's documents (draft).

    inspection: visual inspection values entered with the receipt (keys appearance, packaging,
    labeling, verdict, has_coa — document side 2.1). Only fills a newly created D03.
    """
    from apps.doc_requirements import services

    return services.require_for_lot(staff_id, lot_id, inspection=inspection)


def receipt_cancel_blockers(*, lot_id):
    """LOT documents that stop a receipt cancellation (in approval, approved or being
    corrected) as [(type_code, status)]. Empty: the cancellation may go ahead."""
    from apps.doc_requirements import services

    return [
        (doc["type_code"], doc["status"])
        for doc in services.docs_for_lot(lot_id)["documents"]
        if doc["status"] in LOCKED_DOCUMENT_STATUSES or doc.get("correcting")
    ]


def incoming_receipt_cancelled(*, lot_id, reason, staff_id):
    """A receipt was cancelled. Document side: not decided yet (document side 4) — no-op."""


def batch_started(*, batch_id, staff_id):
    """A production batch started (IN_PROGRESS, or completed without a start): create the
    CCP 일지 of a manufacturing batch (ERD v7 ③)."""
    from apps.doc_requirements import services

    return services.require_for_batch(staff_id, batch_id)
