"""
Owns: full DB rebuild use-case — wipe and reload all open orders from source.
Must not: import concrete adapters; must not call console prompts (entry point prompts the user).
May import: core.schema, core.errors, core.ports.
"""

from __future__ import annotations

import logging

from core.ports import PurchaseOrderSource, Repository

logger = logging.getLogger(__name__)


def refresh_all(source: PurchaseOrderSource, repository: Repository, confirmed: bool) -> None:
    """Wipe po_inventory and reload from source.

    confirmed=False is a no-op; the caller (entry point) handles the prompt.
    Logs row count before and after the wipe so the operator can verify the rebuild.
    """
    if not confirmed:
        logger.info("refresh_aborted reason=not_confirmed")
        return

    before = repository.count_po_items()
    logger.info("refresh_start items_before=%d", before)

    repository.clear_po_items()

    items = source.fetch_all_open_orders()
    repository.upsert_items(items)

    after = repository.count_po_items()
    logger.info("refresh_complete items_before=%d items_after=%d", before, after)
