"""
Owns: port (Protocol) definitions for all adapter boundaries.
Must not: import adapters or services; must not perform I/O.
May import: stdlib (typing, collections.abc), core.schema.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal, Protocol, runtime_checkable

from core.schema import ReceivingRecord

ReceiveOutcome = Literal["received", "not_found", "finalize_error"]


@runtime_checkable
class Repository(Protocol):
    """Persistence port — the authoritative store for 'what arrived'.

    save_record and upsert_items are idempotent (INSERT OR REPLACE on primary key).
    mark_emitted raises RepositoryError if the row does not exist.
    clear_po_items wipes all rows from po_inventory (used by refresh).
    unclaimed_for_po returns only rows without a claimed_at timestamp.
    claim atomically sets claimed_at on one row; the AND claimed_at IS NULL guard
    prevents double-claiming under concurrent access.
    """

    def get_purchase_order(self, po_number: str) -> list[dict]: ...
    def upsert_items(self, items: list[dict]) -> None: ...
    def save_record(self, record: ReceivingRecord) -> None: ...
    def get_pending(self) -> list[dict]: ...
    def mark_emitted(self, receiving_id: str) -> None: ...
    def was_emitted(self, receiving_id: str) -> bool: ...
    def clear_po_items(self) -> None: ...
    def count_po_items(self) -> int: ...
    def replace_po_items(self, items: list[dict]) -> None: ...
    def unclaimed_for_po(self, po_number: str) -> list[dict]: ...
    def claim(self, inventory_id: str, claimed_at: str) -> None: ...


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


@runtime_checkable
class Scanner(Protocol):
    """Hardware seam for barcode scanner devices.

    start() begins listening and delivers each scanned string to on_scan.
    stop() releases the device and must be safe to call more than once.
    """

    def start(self, on_scan: Callable[[str], None]) -> None: ...
    def stop(self) -> None: ...


@runtime_checkable
class Printer(Protocol):
    """Hardware seam for label printers.

    print_label() renders and outputs a receiving label. Raises PrinterError
    on failure — the record is already saved and can be re-printed.
    """

    def print_label(self, record: ReceivingRecord) -> None: ...
    def print_po_label(self, po_number: str) -> None: ...


@runtime_checkable
class ReceivingExecutor(Protocol):
    """Executor port — drives the portal receiving wizard for one inventory unit.

    receive_item returns exactly one of:
        "received"       — wizard completed; item is now received in the portal.
        "not_found"      — PO not reachable, model row absent, or serial input missing.
        "finalize_error" — portal reported an error on the finalize step.

    `model` is required because the portal receiving grid contains no inventory IDs;
    rows are matched by model string. Any UNEXPECTED failure raises ExecutorError so
    callers can count it and may trip a kill threshold; the expected three outcomes are
    returned, never raised.

    close() releases the browser session. Safe to call when no session was started.
    """

    def receive_item(
        self, po_number: str, inventory_id: str, model: str, serial: str
    ) -> ReceiveOutcome: ...

    def close(self) -> None: ...


@runtime_checkable
class ReceivingBoard(Protocol):
    """Board port — bidirectional interface to the receiving status board.

    poll_ready() returns all items in the READY group. Each dict contains:
        item_id:      str — board item identifier
        po_number:    str — purchase order number (the item's name field)
        inventory_id: str — inventory system identifier
        model:        str — model number or description
        serial:       str — serial number or barcode

    mark_received(item_id) moves the item to the RECEIVED group and sets
    the status column value to RECEIVED.

    mark_no_match(item_id) moves the item to the NO MATCH group.

    Any network, parse, or API failure raises BoardError.
    """

    def poll_ready(self) -> list[dict]: ...
    def mark_received(self, item_id: str) -> None: ...
    def mark_no_match(self, item_id: str) -> None: ...
