"""
Owns: mutation-killing tests for the T0-2 already_scanned code paths in
services/receive.py — the _build_already_scanned_record helper and the
detection branch inside process_scan.

Must not: import concrete adapters; must not perform real network or DB I/O.
May import: pytest, services.receive, tests.fakes.

not_measured: real network calls, real SQLite file, real result sink API,
              real USB scanner device, real Tkinter UI.

ALREADY_SCANNED_DETECT:
  Re-scan of an already-claimed barcode returns match_status='already_scanned'.
  First scan of an unclaimed unit must NOT return 'already_scanned'
  (both directions asserted so inverting the guard is caught).

ALREADY_SCANNED_NO_SIDE_EFFECTS:
  The duplicate path exits before save_record / claim_and_save / sink.emit /
  mark_emitted — no board item is created, no record is written.

ALREADY_SCANNED_FIELDS_FULL:
  All catalog fields are carried from the claimed_row onto the record.
  Uses a fuzzy barcode (barcode ≠ model_number) to distinguish model_number
  key-lookup mutations from the fallback default.

ALREADY_SCANNED_FIELDS_SPARSE:
  Missing optional fields in claimed_row fall back to schema defaults.
  Verifies get(key, default) defaults are correct, not corrupted.
"""

from __future__ import annotations

import hashlib

from services.receive import process_scan
from tests.fakes.fake_db import FakeRepository
from tests.fakes.fake_sink import FakeResultSink

_TIMESTAMP = "2026-06-19T10:00:00"


def _make_candidate(
    inventory_id: str,
    model_number: str,
    po_number: str,
    brand: str = "Brand A",
    vendor: str = "Vendor A",
    tags: str = "tag1",
) -> dict:
    return {
        "inventory_id": inventory_id,
        "purchase_order": po_number,
        "model_number": model_number,
        "product_category": "Furniture",
        "truck": "T1",
        "stop": "S1",
        "sales_order": "SO-001",
        "product_size": {"w": 10.0, "d": 20.0, "h": 30.0},
        "quantity": 2,
        "brand": brand,
        "vendor": vendor,
        "tags": tags,
        "created_at": _TIMESTAMP,
    }


# ── Already-scanned detection tests (GATED — T0-2) ────────────────────────────
# ── The detection branch (if matched is None: … if claimed_best: … return) ────
# ── and _build_already_scanned_record field assignments are the T0-2 new code. ─


def test_already_scanned_fires_for_claimed_unit_not_for_unclaimed() -> None:
    """Detection fires ONLY after the unit is claimed; NOT for an unclaimed unit.

    Both directions asserted so inverting 'if matched is None:' or 'if claimed_best:'
    is caught:
      - first scan of unclaimed unit must be 'received', never 'already_scanned'
      - re-scan of same (now claimed) unit must be 'already_scanned', never 'no_match'
    Also verifies no new emit and no new record are created on the duplicate path.
    """
    repo = FakeRepository()
    sink = FakeResultSink()
    repo.upsert_items([_make_candidate("INV-001", "MODEL-A", "PO-001")])

    first = process_scan("MODEL-A", "PO-001", repo, sink)
    assert first.match_status == "received", (
        f"first scan of unclaimed unit must be 'received', got '{first.match_status}'"
    )
    assert len(sink.emitted) == 1

    second = process_scan("MODEL-A", "PO-001", repo, sink)
    assert second.match_status == "already_scanned", (
        f"re-scan of claimed unit must be 'already_scanned', got '{second.match_status}'"
    )
    # No new emit — the board must not receive a spurious no_match item.
    assert len(sink.emitted) == 1, "already_scanned path must not emit"
    # No new save — verify the duplicate path did not fall through to save_record.
    # If it did, a no_match record would be saved with receiving_id = sha256(po + "" + barcode).
    no_match_rid = hashlib.sha256(b"PO-001MODEL-A").hexdigest()
    assert not repo.was_emitted(no_match_rid), (
        "already_scanned path must not fall through and save a no_match record"
    )


def test_already_scanned_record_carries_all_fields_from_claimed_row() -> None:
    """All catalog fields are copied from the claimed row onto the already_scanned record.

    Uses a fuzzy barcode ('MODEL-AB' fuzzy-matches catalog 'MODEL-A', score ≈ 0.93
    using normalized SequenceMatcher, threshold 0.6) so that barcode ≠ model_number.
    This is required to kill the model_number key-lookup mutations: get(None, barcode)
    and get("XX…XX", barcode) both fall back to returning barcode ('MODEL-AB') instead
    of the catalog value ('MODEL-A'), so the assertion model_number == 'MODEL-A' catches
    them.

    Kills:
      - All _build_already_scanned_record key-lookup survivors: get(None,…) /
        get("XX…XX",…) / get("FIELD_NAME",…) for every catalog field.
      - 'and' operator mutations on brand/vendor/tags: non-empty value collapses to ''
        when 'or' is replaced with 'and' (e.g. "Acme" and "" → "").
      - process_scan barcode→None: changes receiving_id hash, caught by exact hash assert.
      - process_scan serial→None: collapses serial to '' via from_dict, caught by assert.
    """
    repo = FakeRepository()
    sink = FakeResultSink()
    repo.upsert_items(
        [
            _make_candidate(
                "INV-001",
                "MODEL-A",
                "PO-001",
                brand="Acme",
                vendor="Dist-Y",
                tags="a,b",
            )
        ]
    )

    # First scan with fuzzy barcode — matches MODEL-A, claims INV-001.
    process_scan("MODEL-AB", "PO-001", repo, sink)

    # Re-scan: same fuzzy barcode, unit now claimed → already_scanned.
    record = process_scan("MODEL-AB", "PO-001", repo, sink, serial="SN-DUP-99")

    assert record.match_status == "already_scanned"
    assert record.purchase_order == "PO-001"
    assert record.model_number == "MODEL-A"  # catalog value, not barcode 'MODEL-AB'
    assert record.inventory_id == "INV-001"
    assert record.truck == "T1"
    assert record.stop == "S1"
    assert record.sales_order == "SO-001"
    assert record.product_category == "Furniture"
    assert record.product_size == {"w": 10.0, "d": 20.0, "h": 30.0}
    assert record.quantity == 2
    assert record.serial == "SN-DUP-99"
    assert record.brand == "Acme"
    assert record.vendor == "Dist-Y"
    assert record.tags == "a,b"
    # receiving_id = sha256(po_number + inventory_id + barcode) — same hash as original scan.
    expected_rid = hashlib.sha256(b"PO-001INV-001MODEL-AB").hexdigest()
    assert record.receiving_id == expected_rid


def test_already_scanned_sparse_row_uses_field_defaults() -> None:
    """Missing optional fields in the claimed row fall back to schema defaults.

    Seeds a minimal item (only inventory_id, model_number, purchase_order) so that
    every get(key, default) call in _build_already_scanned_record exercises the
    default branch.  Kills:
      - get(key, ) / get(key, None): no-default or None-default causes ValidationError
        on required ReceivingRecord fields → test raises → mutant caught.
      - get(key, "XXXX"): wrong string default → field ≠ '' → assertion fails.
      - get(key, 2): wrong int default → quantity ≠ 1 → assertion fails.
      - get(key, {"w": 1, …}): wrong product_size default → assertion fails.
      - get("brand") or "XXXX": returns "XXXX" when brand absent → brand ≠ '' fails.
      (Same logic applies to vendor and tags.)
    """
    repo = FakeRepository()
    sink = FakeResultSink()
    repo.upsert_items(
        [{"inventory_id": "INV-001", "purchase_order": "PO-001", "model_number": "MODEL-A"}]
    )

    process_scan("MODEL-A", "PO-001", repo, sink)
    record = process_scan("MODEL-A", "PO-001", repo, sink)

    assert record.match_status == "already_scanned"
    assert record.truck == ""
    assert record.stop == ""
    assert record.sales_order == ""
    assert record.product_category == ""
    assert record.product_size == {"w": 0, "d": 0, "h": 0}
    assert record.quantity == 1
    assert record.brand == ""
    assert record.vendor == ""
    assert record.tags == ""
