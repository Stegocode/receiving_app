"""
Owns: tests for services.receive.process_scan.
Must not: import concrete adapters; must not perform real network or DB I/O.
May import: pytest, services.receive, tests.fakes.

not_measured: real network calls, real SQLite file, real result sink API,
              real USB scanner device, real Tkinter UI.

PASS:        barcode matches unclaimed PO unit → match_status='received', emit called.
NO_MATCH:    barcode matches nothing → match_status='no_match', emit called.
CLAIM_N:     N units of same model; N scans claim N distinct inventory_ids.
CLAIM_EXHAUSTED: (N+1)th scan with no unclaimed units → no_match.
SERIAL:      serial parameter is carried through to the emitted record.
BRAND_TAGS:  brand/vendor/tags from matched row are carried through to the record.
"""

from __future__ import annotations

import hashlib

from core.schema import ReceivingRecord
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


def test_process_scan_match() -> None:
    """Matching barcode → match_status='received', record saved, emit called once.

    All fields asserted to kill _build_record default-value mutations in the matched block.
    """
    repo = FakeRepository()
    sink = FakeResultSink()
    repo.upsert_items([_make_candidate("INV-001", "MODEL-A", "PO-001")])

    record = process_scan("MODEL-A", "PO-001", repo, sink)

    assert record.match_status == "received"
    assert record.purchase_order == "PO-001"
    assert record.inventory_id == "INV-001"
    assert record.model_number == "MODEL-A"
    assert record.truck == "T1"
    assert record.stop == "S1"
    assert record.sales_order == "SO-001"
    assert record.product_category == "Furniture"
    assert record.product_size == {"w": 10.0, "d": 20.0, "h": 30.0}
    assert record.quantity == 2
    assert repo.was_emitted(record.receiving_id)
    assert len(sink.emitted) == 1
    assert sink.emitted[0].receiving_id == record.receiving_id


def test_process_scan_no_match() -> None:
    """No matching candidate → match_status='no_match', routed through emit, record saved.

    model_number carries the scanned barcode; serial carries the scanned serial (empty here).
    All other default fields asserted to kill _build_record default-value mutations.
    """
    repo = FakeRepository()
    sink = FakeResultSink()
    repo.upsert_items([_make_candidate("INV-001", "MODEL-A", "PO-001")])

    record = process_scan("ZZZZZ-NOMATCH-999", "PO-001", repo, sink)

    assert record.match_status == "no_match"
    assert record.inventory_id == ""
    assert record.purchase_order == "PO-001"
    assert record.truck == ""
    assert record.stop == ""
    assert record.sales_order == ""
    assert record.model_number == "ZZZZZ-NOMATCH-999"
    assert record.product_category == ""
    assert record.product_size == {"w": 0, "d": 0, "h": 0}
    assert record.quantity == 1
    assert record.serial == ""
    assert record.brand == ""
    assert record.vendor == ""
    assert record.tags == ""
    assert repo.was_emitted(record.receiving_id)
    assert len(sink.emitted) == 1
    assert len(sink.attention) == 0


def test_process_scan_receiving_id_uses_po_inventory_and_barcode() -> None:
    """receiving_id is SHA-256(po_number + inventory_id + barcode).

    Kills recv_ps_22 (po_number→None), recv_ps_23 (inventory_id→None),
    recv_ps_24 (barcode→None): each substitution produces a different hash.
    """
    repo = FakeRepository()
    sink = FakeResultSink()
    repo.upsert_items([_make_candidate("INV-001", "MODEL-A", "PO-001")])

    record = process_scan("MODEL-A", "PO-001", repo, sink)

    expected = hashlib.sha256(b"PO-001INV-001MODEL-A").hexdigest()
    assert record.receiving_id == expected


def test_process_scan_no_match_receiving_id_uses_empty_inventory_id() -> None:
    """No-match receiving_id uses empty string for inventory_id in the hash."""
    repo = FakeRepository()
    sink = FakeResultSink()
    repo.upsert_items([_make_candidate("INV-001", "MODEL-A", "PO-001")])

    record = process_scan("ZZZZZ-NOMATCH", "PO-001", repo, sink)

    expected = hashlib.sha256(b"PO-001ZZZZZ-NOMATCH").hexdigest()
    assert record.receiving_id == expected


def test_process_scan_match_with_sparse_candidate_uses_defaults() -> None:
    """Matched candidate missing optional fields falls back to _build_record defaults."""
    repo = FakeRepository()
    sink = FakeResultSink()
    repo.upsert_items(
        [{"inventory_id": "INV-S", "purchase_order": "PO-001", "model_number": "MODEL-A"}]
    )

    record = process_scan("MODEL-A", "PO-001", repo, sink)

    assert record.match_status == "received"
    assert record.truck == ""
    assert record.stop == ""
    assert record.sales_order == ""
    assert record.product_category == ""
    assert record.product_size == {"w": 0, "d": 0, "h": 0}
    assert record.quantity == 1
    assert record.brand == ""
    assert record.vendor == ""
    assert record.tags == ""


# ── Claiming tests (GATED — these tests MUST fail on a mutation that ──────────
# ── drops the claim, uses get_purchase_order instead of unclaimed_for_po, ─────
# ── or removes the AND claimed_at IS NULL guard in the Repository). ────────────


def test_claiming_n_units_same_model_returns_n_distinct_inventory_ids() -> None:
    """Seed N units of the same model; N scans must claim N DISTINCT inventory_ids.

    Mutation kill target: any mutation that:
      - drops the claim() call → all scans return the same inventory_id (first match)
      - uses get_purchase_order instead of unclaimed_for_po → all scans return INV-001
      - removes the AND claimed_at IS NULL guard → re-claims the same row each time
    All of these mutations cause the set of claimed IDs to have fewer than N members,
    failing the len(claimed_ids) == N assertion.
    """
    N = 3
    repo = FakeRepository()
    sink = FakeResultSink()
    for i in range(1, N + 1):
        repo.upsert_items([_make_candidate(f"INV-{i:03d}", "MODEL-A", "PO-001")])

    claimed_ids = []
    for _ in range(N):
        record = process_scan("MODEL-A", "PO-001", repo, sink)
        assert record.match_status == "received", "expected a match while units remain unclaimed"
        claimed_ids.append(record.inventory_id)

    assert len(claimed_ids) == N
    assert len(set(claimed_ids)) == N, f"expected {N} distinct inventory_ids but got: {claimed_ids}"
    assert len(sink.emitted) == N


def test_claiming_n_plus_one_scan_finds_nothing() -> None:
    """After N claims exhaust the catalog, the (N+1)th scan is a no_match.

    Mutation kill target: any mutation that uses get_purchase_order (which returns ALL rows
    including claimed ones) instead of unclaimed_for_po → the (N+1)th scan finds a match
    and this assertion fails.
    """
    N = 2
    repo = FakeRepository()
    sink = FakeResultSink()
    for i in range(1, N + 1):
        repo.upsert_items([_make_candidate(f"INV-{i:03d}", "MODEL-A", "PO-001")])

    for _ in range(N):
        process_scan("MODEL-A", "PO-001", repo, sink)

    # (N+1)th scan — all units claimed
    record = process_scan("MODEL-A", "PO-001", repo, sink)
    assert record.match_status == "no_match", (
        "expected no_match when all units are claimed, but got a match"
    )


def test_claiming_does_not_affect_other_models_on_same_po() -> None:
    """Claiming MODEL-A does not prevent MODEL-B from being claimed on the same PO.

    Kills any mutation that accidentally marks all rows claimed instead of just the matched one.
    """
    repo = FakeRepository()
    sink = FakeResultSink()
    repo.upsert_items(
        [
            _make_candidate("INV-A", "MODEL-A", "PO-001"),
            _make_candidate("INV-B", "MODEL-B", "PO-001"),
        ]
    )

    rec_a = process_scan("MODEL-A", "PO-001", repo, sink)
    rec_b = process_scan("MODEL-B", "PO-001", repo, sink)

    assert rec_a.match_status == "received"
    assert rec_a.inventory_id == "INV-A"
    assert rec_b.match_status == "received"
    assert rec_b.inventory_id == "INV-B"
    assert rec_a.inventory_id != rec_b.inventory_id


# ── Serial / label field tests (GATED) ────────────────────────────────────────


def test_serial_is_carried_through_to_matched_record() -> None:
    """Scanned serial appears on the matched ReceivingRecord.

    Kills any mutation that drops the serial parameter from _build_record or
    that fails to thread serial through process_scan.
    """
    repo = FakeRepository()
    sink = FakeResultSink()
    repo.upsert_items([_make_candidate("INV-001", "MODEL-A", "PO-001")])

    record = process_scan("MODEL-A", "PO-001", repo, sink, serial="SN-ABCD-1234")

    assert record.serial == "SN-ABCD-1234"
    assert sink.emitted[0].serial == "SN-ABCD-1234"


def test_serial_not_set_defaults_to_empty_string() -> None:
    """When no serial is passed, record.serial is an empty string (not None)."""
    repo = FakeRepository()
    sink = FakeResultSink()
    repo.upsert_items([_make_candidate("INV-001", "MODEL-A", "PO-001")])

    record = process_scan("MODEL-A", "PO-001", repo, sink)

    assert record.serial == ""


def test_no_match_carries_scanned_model_and_serial() -> None:
    """No-match record carries scanned model + serial so the board item is actionable.

    Kills any mutation that leaves model_number or serial blank on the no-match path:
      - model_number must equal the raw barcode input, not the empty default.
      - serial must equal the scanned serial, not the empty default.
    The emitted record in the fake sink must also carry both fields.
    """
    repo = FakeRepository()
    sink = FakeResultSink()
    repo.upsert_items([_make_candidate("INV-001", "MODEL-A", "PO-001")])

    record = process_scan("UNKNOWN-XYZ", "PO-001", repo, sink, serial="SN-NO-MATCH-99")

    assert record.match_status == "no_match"
    assert record.model_number == "UNKNOWN-XYZ", (
        f"expected scanned barcode 'UNKNOWN-XYZ' but got {record.model_number!r}"
    )
    assert record.serial == "SN-NO-MATCH-99", (
        f"expected scanned serial 'SN-NO-MATCH-99' but got {record.serial!r}"
    )
    assert sink.emitted[0].model_number == "UNKNOWN-XYZ"
    assert sink.emitted[0].serial == "SN-NO-MATCH-99"


def test_brand_vendor_tags_are_carried_from_matched_row() -> None:
    """brand, vendor, tags from the po_inventory row appear on the matched record.

    Kills any mutation that drops the brand/vendor/tags fields from _build_record
    or that fails to pull them from the matched candidate dict.
    """
    repo = FakeRepository()
    sink = FakeResultSink()
    repo.upsert_items(
        [
            _make_candidate(
                "INV-001",
                "MODEL-A",
                "PO-001",
                brand="Whirlpool",
                vendor="Distributor X",
                tags="appliance,washer",
            )
        ]
    )

    record = process_scan("MODEL-A", "PO-001", repo, sink, serial="SN-9999")

    assert record.brand == "Whirlpool"
    assert record.vendor == "Distributor X"
    assert record.tags == "appliance,washer"
    assert sink.emitted[0].brand == "Whirlpool"
    assert sink.emitted[0].vendor == "Distributor X"
    assert sink.emitted[0].tags == "appliance,washer"


def test_no_match_scan_does_not_set_idempotent_no_match_records_for_same_barcode() -> None:
    """Two no-match scans of the same barcode on the same PO produce the same receiving_id.

    was_emitted guard blocks the second emit; only 1 emit call total.
    This verifies that the no-match idempotency path still works correctly
    (inventory_id='' → same hash → same receiving_id → was_emitted guard fires).
    """
    repo = FakeRepository()

    class _CountingSink:
        def __init__(self) -> None:
            self.emit_count = 0

        def emit(self, record: ReceivingRecord) -> None:
            self.emit_count += 1

        def surface_attention(self, record: ReceivingRecord) -> None:
            self.emit_count += 1

    sink = _CountingSink()
    # No candidates — all scans will be no_match
    record1 = process_scan("NOMATCH-XYZ", "PO-001", repo, sink)
    record2 = process_scan("NOMATCH-XYZ", "PO-001", repo, sink)

    assert record1.receiving_id == record2.receiving_id
    assert sink.emit_count == 1  # was_emitted guard blocked second emit
