"""
Owns: process_scan use-case — match a scanned barcode against a purchase order.
Must not: import concrete adapters; must not read environment variables or perform I/O directly.
May import: core.schema, core.matching, core.errors, core.ports.

Invariant: a crash at any step in process_scan leaves the system recoverable on
retry — save_record is durable before any sink call; was_emitted prevents
double-emission; mark_emitted is set only after the sink acknowledges.

Claiming invariant: claim() uses AND claimed_at IS NULL so a concurrent scan
cannot steal an already-claimed row. Once claimed, the inventory_id is locked
to this scan session (single-writer assumption — see boundary markers).
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime

from core.matching import find_best_match
from core.ports import Repository, ResultSink
from core.schema import ReceivingRecord, from_dict

logger = logging.getLogger(__name__)


def _make_receiving_id(po_number: str, inventory_id: str, barcode: str) -> str:
    """Deterministic SHA-256 of (po_number, inventory_id, barcode).

    For a no-match scan, pass inventory_id='' so the hash is stable across retries.
    """
    return hashlib.sha256(f"{po_number}{inventory_id}{barcode}".encode()).hexdigest()


def _build_record(
    matched: dict | None,
    best_model: str | None,
    po_number: str,
    inventory_id: str,
    receiving_id: str,
    serial: str = "",
    scanned_model: str = "",
) -> ReceivingRecord:
    """Build a ReceivingRecord from match result.

    On no-match: model_number and serial are populated from the scanned input so
    the NO_MATCH board item shows what failed to match (actionable for the team).
    On match: model_number comes from the catalog row (best_model); serial from scan.
    brand, vendor, tags are carried from the matched po_inventory row so the
    label printer and downstream sink have the full catalog fields available.
    """
    fields = {
        "truck": "",
        "stop": "",
        "sales_order": "",
        "model_number": scanned_model,
        "product_category": "",
        "product_size": {"w": 0, "d": 0, "h": 0},
        "quantity": 1,
        "receiving_id": receiving_id,
        "timestamp": datetime.now().isoformat(),
        "match_status": "no_match",
        "purchase_order": po_number,
        "inventory_id": "",
        "serial": serial,
        "brand": "",
        "vendor": "",
        "tags": "",
    }
    if matched and best_model:
        fields.update(
            {
                "truck": matched.get("truck", ""),
                "stop": matched.get("stop", ""),
                "sales_order": matched.get("sales_order", ""),
                "model_number": best_model,
                "product_category": matched.get("product_category", ""),
                "product_size": matched.get("product_size", {"w": 0, "d": 0, "h": 0}),
                "quantity": matched.get("quantity", 1),
                "match_status": "received",
                "inventory_id": inventory_id,
                "serial": serial,
                "brand": matched.get("brand") or "",
                "vendor": matched.get("vendor") or "",
                "tags": matched.get("tags") or "",
            }
        )
    return from_dict(fields)


def process_scan(
    barcode: str,
    po_number: str,
    repository: Repository,
    sink: ResultSink,
    *,
    serial: str = "",
) -> ReceivingRecord:
    """Match barcode against unclaimed PO units, claim the match, save and emit once.

    Uses unclaimed_for_po so each physical unit is only claimed once. On a match,
    claim() is called before building the record — the AND claimed_at IS NULL guard
    prevents two concurrent scans from claiming the same unit.

    No-match is an expected outcome (match_status='no_match'), not an exception.
    Step order: claim (if match) → save_record (durable) → was_emitted guard
    → sink call → mark_emitted → return.
    """
    candidates = repository.unclaimed_for_po(po_number)
    best_model, _ = find_best_match(barcode, [c["model_number"] for c in candidates])

    matched = (
        next((c for c in candidates if c["model_number"] == best_model), None)
        if best_model
        else None
    )
    inventory_id = matched["inventory_id"] if matched else ""

    if matched:
        repository.claim(inventory_id, datetime.now().isoformat())

    receiving_id = _make_receiving_id(po_number, inventory_id, barcode)
    record = _build_record(
        matched, best_model, po_number, inventory_id, receiving_id, serial, scanned_model=barcode
    )

    repository.save_record(record)

    if repository.was_emitted(record.receiving_id):
        return record

    if record.match_status == "needs_attention":
        sink.surface_attention(record)
    else:
        sink.emit(record)

    repository.mark_emitted(record.receiving_id)
    logger.info("scan_%s receiving_id=%s", record.match_status, record.receiving_id)
    return record
