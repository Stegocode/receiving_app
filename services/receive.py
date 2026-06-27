"""
Owns: process_scan use-case — match a scanned barcode against a purchase order.
Must not: import concrete adapters; must not read environment variables or perform I/O directly.
May import: core.schema, core.matching, core.errors, core.ports.

Invariant: a crash at any step in process_scan leaves the system recoverable on
retry — claim and save_record commit atomically via claim_and_save so a crash
cannot leave a unit claimed without a corresponding record; was_emitted prevents
double-emission; mark_emitted is set only after the sink acknowledges.

Claiming invariant: claim_and_save uses AND claimed_at IS NULL so a concurrent
scan cannot steal an already-claimed row. Once claimed, the inventory_id is locked
to this scan session (single-writer assumption — see boundary markers).

Duplicate-scan invariant (T0-2): a scan whose serial exactly matches an already-claimed
receiving record on this PO returns match_status='already_scanned' without saving or
emitting. Serial is the unique physical-unit discriminator; barcode/model matching is
NOT used here. Blank serial → no duplicate check → no_match (defense in depth: the
scanner flow enforces serial, but the service must not rely on that).
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime

from core.matching import resolve_exact
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


def _build_already_scanned_record(
    po_number: str,
    claimed_row: dict,
    serial: str,
) -> ReceivingRecord:
    """Build a sentinel record for a duplicate scan of an already-claimed unit.

    Not saved and not emitted — returned so the caller (scanner UI) can present a
    distinct 'already scanned' signal without creating a no_match board item.
    receiving_id is taken from the original scan's persisted record for traceability.
    claimed_row must be the dict returned by find_claimed_by_serial, which includes
    receiving_id and catalog fields from both po_inventory and receiving_items.
    """
    return from_dict(
        {
            "truck": claimed_row.get("truck", ""),
            "stop": claimed_row.get("stop", ""),
            "sales_order": claimed_row.get("sales_order", ""),
            "model_number": claimed_row.get("model_number", ""),
            "product_category": claimed_row.get("product_category", ""),
            "product_size": claimed_row.get("product_size", {"w": 0, "d": 0, "h": 0}),
            "quantity": claimed_row.get("quantity", 1),
            "receiving_id": claimed_row["receiving_id"],
            "timestamp": datetime.now().isoformat(),
            "match_status": "already_scanned",
            "purchase_order": po_number,
            "inventory_id": claimed_row["inventory_id"],
            "serial": serial,
            "brand": claimed_row.get("brand") or "",
            "vendor": claimed_row.get("vendor") or "",
            "tags": claimed_row.get("tags") or "",
        }
    )


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
    claim_and_save commits both the claim and the record in a single transaction —
    a crash cannot leave a unit claimed without a corresponding record (T0-1).

    Duplicate-scan path (T0-2): if no unclaimed candidate matches and the scan carries
    a non-blank serial that exactly matches a claimed unit's receiving record on this PO,
    it is a re-scan of that specific physical unit. Returns match_status='already_scanned'
    without saving or emitting. Blank serial → skip duplicate check → no_match (defense
    in depth). Serial is the discriminator; barcode/model are NOT used here.

    No-match is an expected outcome (match_status='no_match'), not an exception.
    Step order: claim_and_save (match) or save_record (no-match) → was_emitted
    guard → sink call → mark_emitted → return.
    Duplicate path exits early: no save, no emit, no mark_emitted.
    """
    candidates = repository.unclaimed_for_po(po_number)
    # Deduplicate model strings: multiple unclaimed units may share one model number.
    # resolve_exact returns None on two-or-more distinct matches; passing unique models
    # ensures the guard fires only when different models collide, not on repeated slots.
    best_model = resolve_exact(barcode, list(dict.fromkeys(c["model_number"] for c in candidates)))

    matched = (
        next((c for c in candidates if c["model_number"] == best_model), None)
        if best_model
        else None
    )

    if matched is None and serial:
        dup_row = repository.find_claimed_by_serial(po_number, serial)
        if dup_row:
            logger.info(
                "scan_duplicate serial=%s po_number=%s inventory_id=%s",
                serial,
                po_number,
                dup_row["inventory_id"],
            )
            return _build_already_scanned_record(po_number, dup_row, serial)

    inventory_id = matched["inventory_id"] if matched else ""
    claimed_at = datetime.now().isoformat()

    receiving_id = _make_receiving_id(po_number, inventory_id, barcode)
    record = _build_record(
        matched, best_model, po_number, inventory_id, receiving_id, serial, scanned_model=barcode
    )

    if matched:
        repository.claim_and_save(inventory_id, claimed_at, record)
    else:
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
