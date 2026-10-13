"""Calls from inventory into the document app (agreed: direct service calls, ids only).

The document app reads the data itself, so these hooks pass identifiers, not payloads:
    incoming LOT     -> v_doc_incoming_lot by lot_id
    production batch -> v_doc_batch by production_batch_id
    stock ledger     -> apps.inventory.ledger.stock_ledger(...) by item + period

The hooks run inside the inventory transaction: if the document side raises, the inventory
change rolls back too. They are no-ops until the document app provides its functions.

domain_event (document app) is an outbox for external notification APIs, not a channel
between the two apps; inventory does not write to it.
"""


def incoming_received(*, lot_id):
    """A receipt (and its LOT) was registered. Document side: nothing yet.

    With the combined receipt + visual inspection screen, the inspection record is created
    through the document app's create_incoming_inspection(...) instead (pending its interface).
    """


def incoming_receipt_cancelled(*, lot_id, reason, staff_id):
    """A receipt was cancelled. Document side decides what happens to the inspection record."""


def batch_started(*, batch_id, staff_id):
    """A production batch started (IN_PROGRESS). Document side: require_for_batch(...) creates
    the CCP 일지 for a manufacturing batch (ERD v7 ③). Connected after the document app merges."""
