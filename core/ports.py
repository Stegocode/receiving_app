"""
Owns: port (Protocol) definitions for all adapter boundaries.
Must not: import adapters or services; must not perform I/O.
May import: stdlib (typing), core.schema.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from core.schema import ReceivingRecord


@runtime_checkable
class Repository(Protocol):
    """Persistence port — the authoritative store for 'what arrived'.

    save_record and upsert_items are idempotent (INSERT OR REPLACE on primary key).
    mark_emitted raises RepositoryError if the row does not exist.
    clear_po_items wipes all rows from po_inventory (used by refresh).
    """

    def get_purchase_order(self, po_number: str) -> list[dict]: ...
    def upsert_items(self, items: list[dict]) -> None: ...
    def save_record(self, record: ReceivingRecord) -> None: ...
    def get_pending(self) -> list[dict]: ...
    def mark_emitted(self, receiving_id: str) -> None: ...
    def was_emitted(self, receiving_id: str) -> bool: ...
    def clear_po_items(self) -> None: ...
    def count_po_items(self) -> int: ...


@runtime_checkable
class PurchaseOrderSource(Protocol):
    """Source port — retrieves open purchase order line items."""

    def fetch_order(self, po_number: str) -> list[dict]: ...
    def fetch_all_open_orders(self) -> list[dict]: ...


@runtime_checkable
class ResultSink(Protocol):
    """Sink port — surfaces receiving outcomes to an external system.

    Both emit and surface_attention are idempotent on receiving_id: a repeat
    call for the same ID is a silent no-op (no API call, no log entry).
    """

    def emit(self, record: ReceivingRecord) -> None: ...
    def surface_attention(self, record: ReceivingRecord) -> None: ...
