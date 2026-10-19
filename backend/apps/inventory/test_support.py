"""Shared test setup for inventory tests.

Receipts and batch starts call the document app (document_bridge): require_for_lot creates the
LOT's D01·D02·D03 and require_for_batch the CCP 일지, so their form templates must exist.
In a real database they are loaded with the document forms; tests load the same definitions.
"""


def seed_document_forms():
    from apps.documents.seed import ensure_p4_templates

    ensure_p4_templates()
