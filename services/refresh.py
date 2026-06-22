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
    """Fetch-then-replace po_inventory from source.

    Safety contract:
      - confirmed=False  → no-op; caller (entry point) owns the prompt.
      - fetch raises     → exception propagates; DB is never touched.
      - fetch returns [] → safety-stop logged; DB is never touched.
      - non-empty fetch  → replace_po_items() wipes and reloads atomically.

    PASS criterion: after a successful call, count_po_items() == len(fetched rows).
    KILL criterion: a fetch failure must never leave the catalog empty.
    not_measured: real portal network calls; concurrent writers; very large catalogs.
    """
    if not confirmed:
        logger.info("refresh_aborted reason=not_confirmed")
        return

    items = source.fetch_all_open_orders()

    if not items:
        logger.warning(
            "refresh_aborted reason=empty_fetch — source returned no rows; DB not modified"
        )
        return

    before = repository.count_po_items()
    logger.info("refresh_start items_before=%d", before)

    repository.replace_po_items(items)

    after = repository.count_po_items()
    logger.info("refresh_complete items_before=%d items_after=%d", before, after)
