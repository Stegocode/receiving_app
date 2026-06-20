"""
Owns: populate use-case — load purchase order line items from the source adapter.
Must not: import concrete adapters; must not read environment variables or call console prompts.
May import: core.schema, core.errors, core.ports.
"""

from __future__ import annotations

import logging

from core.ports import PurchaseOrderSource, Repository

logger = logging.getLogger(__name__)


def populate_po(po_number: str, repository: Repository, source: PurchaseOrderSource) -> None:
    """Load PO line items from source into the repository if not already present.

    Idempotent: if the PO already has rows in the repository, source is not called.
    """
    existing = repository.get_purchase_order(po_number)
    if existing:
        logger.info("populate_skipped po=%s existing_rows=%d", po_number, len(existing))
        return

    items = source.fetch_order(po_number)
    repository.upsert_items(items)
    logger.info("populate_complete po=%s rows=%d", po_number, len(items))
