"""
Owns: in-memory fakes for Repository and SyncStatusStore ports, for use in tests.
Must not: touch SQLite or any real persistence.
May import: core.ports, core.schema, core.errors.
"""
# Owns: in-memory fakes for Repository and SyncStatusStore ports, for use in tests.
# Must not: touch SQLite or any real persistence.
# May import: core.ports, core.schema, core.errors.

from __future__ import annotations

from datetime import UTC, datetime

from core.errors import RepositoryError
from core.schema import ReceivingRecord, SyncStatusRecord


class FakeRepository:
    """In-memory Repository with the same observable behaviour as SQLiteRepository.

    Idempotent on receiving_id: re-saving a record preserves emitted and created_at.
    mark_emitted raises RepositoryError if the receiving_id is unknown.
    claim is a no-op when the row is already claimed (matches the SQL AND guard).
    """

    def __init__(self) -> None:
        self._records: dict[str, dict] = {}  # receiving_id → record dict
        self._po_items: dict[str, dict] = {}  # inventory_id → item dict
        self._barcode_map: dict[str, dict] = {}  # raw_barcode → mapping dict

    def get_purchase_order(self, po_number: str) -> list[dict]:
        return [
            dict(item) for item in self._po_items.values() if item["purchase_order"] == po_number
        ]

    def unclaimed_for_po(self, po_number: str) -> list[dict]:
        """Return unclaimed rows for the given PO (claimed_at IS NULL)."""
        return [
            dict(item)
            for item in self._po_items.values()
            if item["purchase_order"] == po_number and item.get("claimed_at") is None
        ]

    def claimed_for_po(self, po_number: str) -> list[dict]:
        """Return claimed rows for the given PO (claimed_at IS NOT NULL)."""
        return [
            dict(item)
            for item in self._po_items.values()
            if item["purchase_order"] == po_number and item.get("claimed_at") is not None
        ]

    def claim(self, inventory_id: str, claimed_at: str) -> None:
        """Atomically mark a row claimed. No-op if already claimed (matches SQL AND guard)."""
        item = self._po_items.get(inventory_id)
        if item is not None and item.get("claimed_at") is None:
            item["claimed_at"] = claimed_at

    def claim_and_save(self, inventory_id: str, claimed_at: str, record: ReceivingRecord) -> None:
        """Claim and save atomically — mirrors single-transaction SQLiteRepository behaviour."""
        item = self._po_items.get(inventory_id)
        if item is not None and item.get("claimed_at") is None:
            item["claimed_at"] = claimed_at
        existing = self._records.get(record.receiving_id)
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
            "serial": record.serial,
            "brand": record.brand,
            "vendor": record.vendor,
            "tags": record.tags,
            "emitted": emitted,
            "created_at": created_at,
        }

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
            "serial": record.serial,
            "brand": record.brand,
            "vendor": record.vendor,
            "tags": record.tags,
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

    def find_claimed_by_serial(self, po_number: str, serial: str) -> dict | None:
        """Return merged catalog+logistics row for a received unit with the given serial."""
        for rec in self._records.values():
            if (
                rec.get("purchase_order") == po_number
                and rec.get("serial") == serial
                and rec.get("match_status") == "received"
            ):
                inv_id = rec.get("inventory_id", "")
                po_item = self._po_items.get(inv_id, {})
                return {
                    "inventory_id": inv_id,
                    "receiving_id": rec["receiving_id"],
                    "model_number": rec.get("model_number", ""),
                    "truck": rec.get("truck", ""),
                    "stop": rec.get("stop", ""),
                    "sales_order": rec.get("sales_order", ""),
                    "product_category": rec.get("product_category", ""),
                    "product_size": rec.get("product_size", {"w": 0, "d": 0, "h": 0}),
                    "quantity": rec.get("quantity", 1),
                    "brand": po_item.get("brand") or "",
                    "vendor": po_item.get("vendor") or "",
                    "tags": po_item.get("tags") or "",
                }
        return None

    def clear_po_items(self) -> None:
        self._po_items.clear()

    def count_po_items(self) -> int:
        return len(self._po_items)

    def replace_po_items(self, items: list[dict]) -> None:
        self._po_items.clear()
        for item in items:
            self._po_items[item["inventory_id"]] = dict(item)

    def save_barcode_mapping(
        self, raw_barcode: str, model_number: str, fuzzy_score: float, source: str
    ) -> None:
        self._barcode_map[raw_barcode] = {
            "raw_barcode": raw_barcode,
            "model_number": model_number,
            "fuzzy_score": fuzzy_score,
            "confirmed_at": datetime.now(UTC).isoformat(),
            "source": source,
        }

    def lookup_barcode_mapping(self, raw_barcode: str) -> str | None:
        entry = self._barcode_map.get(raw_barcode)
        return entry["model_number"] if entry else None


class FakeSyncStatusStore:
    """In-memory SyncStatusStore for tests.

    write_sync_status appends to .writes and updates ._record.
    read_sync_status returns the last written record, or None before any write.
    """

    def __init__(self) -> None:
        self._record: SyncStatusRecord | None = None
        self.writes: list[SyncStatusRecord] = []

    def write_sync_status(self, record: SyncStatusRecord) -> None:
        self._record = record
        self.writes.append(record)

    def read_sync_status(self) -> SyncStatusRecord | None:
        return self._record
