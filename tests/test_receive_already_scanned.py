"""
Owns: mutation-killing tests for the T0-2 already_scanned code paths in
services/receive.py — the _build_already_scanned_record helper and the
detection branch inside process_scan.

Must not: import concrete adapters; must not perform real network or DB I/O.
May import: pytest, services.receive, tests.fakes.

not_measured: real network calls, real SQLite file, real result sink API,
              real USB scanner device, real Tkinter UI.

ALREADY_SCANNED_DETECT:
  Re-scan carrying the same serial as an already-received unit returns
  match_status='already_scanned'.  First scan of the same unit (unclaimed)
  must NOT return 'already_scanned' (both directions asserted so inverting
  the guard is caught).

ALREADY_SCANNED_NO_SIDE_EFFECTS:
  The duplicate path exits before save_record / claim_and_save / sink.emit /
  mark_emitted -- no board item is created, no record is written.

ALREADY_SCANNED_FIELDS_FULL:
  All catalog fields are carried from the find_claimed_by_serial row onto the
  record.  Uses a junky vendor barcode on the re-scan (barcode != model_number)
  to prove the result is barcode-independent.

ALREADY_SCANNED_FIELDS_SPARSE:
  Missing optional fields in the stored row fall back to schema defaults.

BLANK_SERIAL_GUARD:
  A scan with blank serial never triggers already_scanned.

ADJACENT_SKU_GUARD:
  A scan with a DIFFERENT serial never triggers already_scanned.
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


# -- Already-scanned detection tests (GATED -- T0-2) --------------------------


def test_already_scanned_fires_for_claimed_serial_not_for_unclaimed() -> None:
    """Detection fires ONLY when the serial matches a claimed unit; NOT for an unclaimed unit.

    Both directions asserted so mutations that invert the guard or the dup_row branch
    are caught:
      - first scan (unit unclaimed) must be 'received', never 'already_scanned'
      - re-scan with same serial (unit now claimed) must be 'already_scanned'
    Also verifies no new emit and no new record are created on the duplicate path.
    """
    repo = FakeRepository()
    sink = FakeResultSink()
    repo.upsert_items([_make_candidate("INV-001", "MODEL-A", "PO-001")])

    first = process_scan("MODEL-A", "PO-001", repo, sink, serial="SN-UNIT-1")
    assert first.match_status == "received", (
        f"first scan of unclaimed unit must be 'received', got '{first.match_status}'"
    )
    assert len(sink.emitted) == 1

    second = process_scan("MODEL-A", "PO-001", repo, sink, serial="SN-UNIT-1")
    assert second.match_status == "already_scanned", (
        f"re-scan with same serial must be 'already_scanned', got '{second.match_status}'"
    )
    assert len(sink.emitted) == 1, "already_scanned path must not emit"
    no_match_rid = hashlib.sha256(b"PO-001MODEL-A").hexdigest()
    assert not repo.was_emitted(no_match_rid), (
        "already_scanned path must not fall through and save a no_match record"
    )


def test_already_scanned_record_carries_all_fields_from_claimed_row() -> None:
    """All catalog+logistics fields are copied from the find_claimed_by_serial row.

    Uses a junky vendor barcode ('VND-JUNK-MODEL-A') on the RE-SCAN while the
    original scan used the clean catalog barcode ('MODEL-A') with the same serial.
    This proves the result is barcode-independent: model_number == 'MODEL-A' comes
    from the stored record (not the current scan barcode), so key-lookup mutations
    in _build_already_scanned_record are caught.

    Kills:
      - All _build_already_scanned_record key-lookup survivors.
      - 'and' operator mutations on brand/vendor/tags.
      - receiving_id mutations: uses claimed_row["receiving_id"] (original scan hash),
        so any mutation that recomputes the hash from the current barcode fails.
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

    # First scan with clean catalog barcode + serial -- claims INV-001.
    process_scan("MODEL-A", "PO-001", repo, sink, serial="SN-DUP-99")

    # Re-scan: junky vendor barcode + SAME serial -> serial match fires already_scanned.
    record = process_scan("VND-JUNK-MODEL-A", "PO-001", repo, sink, serial="SN-DUP-99")

    assert record.match_status == "already_scanned"
    assert record.purchase_order == "PO-001"
    assert record.model_number == "MODEL-A"  # stored value, not re-scan barcode
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
    # receiving_id = original scan's hash sha256(po + inv_id + original_barcode)
    expected_rid = hashlib.sha256(b"PO-001INV-001MODEL-A").hexdigest()
    assert record.receiving_id == expected_rid


def test_already_scanned_sparse_row_uses_field_defaults() -> None:
    """Missing optional fields in the stored row fall back to schema defaults.

    Seeds a minimal item (only inventory_id, model_number, purchase_order) so that
    every get(key, default) call in _build_already_scanned_record exercises the
    default branch.  Kills wrong-default and missing-default mutations.
    """
    repo = FakeRepository()
    sink = FakeResultSink()
    repo.upsert_items(
        [{"inventory_id": "INV-001", "purchase_order": "PO-001", "model_number": "MODEL-A"}]
    )

    process_scan("MODEL-A", "PO-001", repo, sink, serial="SN-SPARSE")
    record = process_scan("MODEL-A", "PO-001", repo, sink, serial="SN-SPARSE")

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


def test_blank_serial_falls_through_to_no_match() -> None:
    """A blank serial bypasses the duplicate check; no_match is returned instead.

    Scenario: unit received with blank serial, then re-scanned also with blank
    serial.  The 'and serial' guard in process_scan must skip find_claimed_by_serial.

    Kills the mutant that removes the 'and serial' guard: without it,
    find_claimed_by_serial("PO-001", "") finds the blank-serial record and
    returns already_scanned instead of no_match.
    """
    repo = FakeRepository()
    sink = FakeResultSink()
    repo.upsert_items([_make_candidate("INV-001", "MODEL-A", "PO-001")])

    process_scan("MODEL-A", "PO-001", repo, sink, serial="")

    record = process_scan("MODEL-A", "PO-001", repo, sink, serial="")

    assert record.match_status == "no_match", (
        f"blank serial must not trigger already_scanned, got '{record.match_status}'"
    )


def test_adjacent_sku_different_serial_is_no_match_not_already_scanned() -> None:
    """A different serial never triggers already_scanned.

    Scenario: WRF560SEHZ00 received with SN-HZ00; operator scans adjacent SKU
    WRF560SEHZ01 with serial SN-HZ01.  Physically distinct units; must produce
    no_match, not already_scanned.

    Under exact normalized matching, 'WRF560SEHZ01' does not match 'WRF560SEHZ00'
    (one-character difference prevents equality). Serial-based duplicate detection
    uses only the serial — a different serial never triggers already_scanned.
    """
    repo = FakeRepository()
    sink = FakeResultSink()
    repo.upsert_items([_make_candidate("INV-HZ00", "WRF560SEHZ00", "PO-001")])

    process_scan("WRF560SEHZ00", "PO-001", repo, sink, serial="SN-HZ00")
    assert len(sink.emitted) == 1

    record = process_scan("WRF560SEHZ01", "PO-001", repo, sink, serial="SN-HZ01")

    assert record.match_status == "no_match", (
        f"different serial must not trigger already_scanned, got '{record.match_status}'"
    )
    assert len(sink.emitted) == 2
