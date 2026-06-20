"""
Owns: in-memory dict-based Repository fake for use in tests.
Must not: touch SQLite or any real persistence.
May import: core.ports, core.schema, core.errors.
"""
# Owns: in-memory dict-based Repository fake for use in tests.
# Must not: touch SQLite or any real persistence.
# May import: core.ports, core.schema, core.errors.

from __future__ import annotations

from core.errors import RepositoryError
from core.schema import ReceivingRecord


class FakeRepository:
    """In-memory Repository with the same observable behaviour as SQLiteRepository.

    Idempotent on receiving_id: re-saving a record preserves emitted and created_at.
    mark_emitted raises RepositoryError if the receiving_id is unknown.
    """

    def __init__(self) -> None:
        self._records: dict[str, dict] = {}  # receiving_id → record dict
        self._po_items: dict[str, dict] = {}  # inventory_id → item dict

    def get_purchase_order(self, po_number: str) -> list[dict]:
        return [
            dict(item) for item in self._po_items.values() if item["purchase_order"] == po_number
        ]

    def upsert_items(self, items: list[dict]) -> None:
        for item in items:
            self._po_items[item["inventory_id"]] = dict(item)

    def save_record(self, record: ReceivingRecord) -> None:
        existing = self._records.get(record.receiving_id)
        # Preserve emitted and created_at across re-saves (mirrors ON CONFLICT DO UPDATE).
        emitted = existing["emitted"] if existing else False
        created_at = existing["created_at"] if existing else record.timestamp
        self._records[record.receiving_id] = {
            "receiving_id": record.receiving_id,
            "purchase_order": record.purchase_order,
            "inventory_id": record.inventory_id,
            "model_number": record.model_number,
            "product_category": record.product_category,
            "truck": record.truck,
            "stop": record.stop,
            "sales_order": record.sales_order,
            "product_size": record.product_size,
            "quantity": record.quantity,
            "match_status": record.match_status,
            "timestamp": record.timestamp,
            "emitted": emitted,
            "created_at": created_at,
        }

    def get_pending(self) -> list[dict]:
        return [dict(r) for r in self._records.values() if not r["emitted"]]

    def mark_emitted(self, receiving_id: str) -> None:
        if receiving_id not in self._records:
            raise RepositoryError(
                f"mark_emitted failed — receiving_id '{receiving_id}' not found;"
                " commit the record before marking it emitted"
            )
        self._records[receiving_id]["emitted"] = True

    def was_emitted(self, receiving_id: str) -> bool:
        record = self._records.get(receiving_id)
        return bool(record["emitted"]) if record else False

    def clear_po_items(self) -> None:
        self._po_items.clear()

    def count_po_items(self) -> int:
        return len(self._po_items)
