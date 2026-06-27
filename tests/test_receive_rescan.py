"""
Owns: T0-2 re-scan idempotency tests for services.receive.process_scan.
Must not: import concrete adapters; must not perform real network or DB I/O.
May import: pytest, services.receive, tests.fakes.

not_measured: real SQLite, real sink API, USB scanner device.

PASS:   received-then-rescanned (same serial) -> match_status='already_scanned', no new emit.
BULK:   same model + distinct serials -> each claims a distinct slot, none is already_scanned.
JUNKY:  junky vendor barcode + same serial as original -> already_scanned (barcode-independent).
GUARD:  genuine no_match-from-the-start still emits no_match exactly once.
GUARD:  a different serial on a different barcode gets its own no_match.
DATA:   already_scanned record carries original model_number and inventory_id.
"""

from __future__ import annotations

from services.receive import process_scan
from tests.fakes.fake_db import FakeRepository
from tests.fakes.fake_sink import FakeResultSink

_TIMESTAMP = "2026-06-19T10:00:00"


def _candidate(inventory_id: str, model_number: str, po_number: str, **extra: object) -> dict:
    base = {
        "inventory_id": inventory_id,
        "purchase_order": po_number,
        "model_number": model_number,
        "product_category": "Furniture",
        "truck": "T1",
        "stop": "S1",
        "sales_order": "SO-001",
        "product_size": {"w": 10.0, "d": 20.0, "h": 30.0},
        "quantity": 1,
        "brand": "Brand A",
        "vendor": "Vendor A",
        "tags": "tag1",
        "created_at": _TIMESTAMP,
    }
    base.update(extra)
    return base


# -- Primary regression test ---------------------------------------------------


def test_rescan_already_received_returns_already_scanned_and_does_not_emit() -> None:
    """THE MISSING TEST (T0-2): first scan receives; second scan of same serial
    must NOT emit a spurious no_match.

    Mutation kill target: removing the find_claimed_by_serial check (or removing the
    early return on already_scanned) causes the re-scan to fall into the no_match path,
    raising len(sink.emitted) to 2 and/or producing a no_match record.
    """
    repo = FakeRepository()
    sink = FakeResultSink()
    repo.upsert_items([_candidate("INV-001", "MODEL-A", "PO-001")])

    first = process_scan("MODEL-A", "PO-001", repo, sink, serial="SN-UNIT-1")
    assert first.match_status == "received"
    assert first.inventory_id == "INV-001"
    assert len(sink.emitted) == 1

    second = process_scan("MODEL-A", "PO-001", repo, sink, serial="SN-UNIT-1")

    assert second.match_status == "already_scanned", (
        f"expected 'already_scanned' on re-scan but got '{second.match_status}'"
    )
    assert second.inventory_id == "INV-001", (
        "already_scanned record must carry the original inventory_id"
    )
    assert len(sink.emitted) == 1, (
        f"expected exactly 1 emit total but got {len(sink.emitted)} -- "
        "spurious no_match was emitted on re-scan"
    )
    assert len(sink.attention) == 0


def test_bulk_same_model_different_serials_each_claim_distinct_slot() -> None:
    """N scans of the same model with DISTINCT serials each claim a distinct slot.

    Mutation kill target: serial-based duplicate detection must not fire when each
    scan carries a different serial.  If it fires incorrectly, some scans return
    already_scanned instead of received, and the set of claimed_ids shrinks below N.
    """
    N = 3
    repo = FakeRepository()
    sink = FakeResultSink()
    for i in range(1, N + 1):
        repo.upsert_items([_candidate(f"INV-{i:03d}", "MODEL-A", "PO-001")])

    serials = [f"SN-{i:03d}" for i in range(1, N + 1)]
    claimed_ids = []
    for serial in serials:
        record = process_scan("MODEL-A", "PO-001", repo, sink, serial=serial)
        assert record.match_status == "received", (
            f"expected received for serial={serial!r}, got '{record.match_status}'"
        )
        claimed_ids.append(record.inventory_id)

    assert len(set(claimed_ids)) == N, f"expected {N} distinct inventory_ids but got: {claimed_ids}"
    assert len(sink.emitted) == N


def test_rescan_junky_vendor_barcode_caught_by_serial() -> None:
    """Re-scan with a junky vendor barcode but same serial -> already_scanned.

    The duplicate check is barcode-independent: serial is the discriminator.
    A genuine re-scan of a received unit (same physical unit, different barcode
    encoding) must be detected even if the barcode does not exactly match the catalog.
    """
    repo = FakeRepository()
    sink = FakeResultSink()
    repo.upsert_items([_candidate("INV-001", "MODEL-A", "PO-001")])

    process_scan("MODEL-A", "PO-001", repo, sink, serial="SN-UNIT-1")
    assert len(sink.emitted) == 1

    second = process_scan("VND-XYZ-MODEL-A", "PO-001", repo, sink, serial="SN-UNIT-1")

    assert second.match_status == "already_scanned", (
        f"same serial + junky barcode must be already_scanned, got '{second.match_status}'"
    )
    assert len(sink.emitted) == 1


# -- Data-carrying tests -------------------------------------------------------


def test_rescan_already_received_record_carries_original_model_and_inventory_id() -> None:
    """already_scanned record preserves model_number and inventory_id from the stored row.

    The scanner UI needs these to show the operator which unit was already scanned.
    """
    repo = FakeRepository()
    sink = FakeResultSink()
    repo.upsert_items(
        [_candidate("INV-XYZ", "MODEL-FRIDGE-42", "PO-999", brand="Whirlpool", tags="appliance")]
    )

    process_scan("MODEL-FRIDGE-42", "PO-999", repo, sink, serial="SN-UNIT-1")
    second = process_scan("MODEL-FRIDGE-42", "PO-999", repo, sink, serial="SN-UNIT-1")

    assert second.match_status == "already_scanned"
    assert second.model_number == "MODEL-FRIDGE-42"
    assert second.inventory_id == "INV-XYZ"
    assert second.purchase_order == "PO-999"


def test_rescan_does_not_save_a_new_record_to_the_repository() -> None:
    """Re-scanning does not add a second receiving record -- no board churn.

    After two scans (one real, one duplicate), there is exactly one record
    in the repository and it is already emitted.
    """
    repo = FakeRepository()
    sink = FakeResultSink()
    repo.upsert_items([_candidate("INV-001", "MODEL-A", "PO-001")])

    first = process_scan("MODEL-A", "PO-001", repo, sink, serial="SN-001")
    process_scan("MODEL-A", "PO-001", repo, sink, serial="SN-001")  # duplicate

    assert repo.was_emitted(first.receiving_id)
    pending = repo.get_pending()
    assert len(pending) == 0, "re-scan must not leave an unemitted no_match record"


def test_rescan_receiving_id_matches_original_scan() -> None:
    """already_scanned record uses the same receiving_id as the original scan.

    _build_already_scanned_record takes claimed_row["receiving_id"] directly from
    the stored record, letting the UI or log query link the duplicate scan back
    to the original.
    """
    repo = FakeRepository()
    sink = FakeResultSink()
    repo.upsert_items([_candidate("INV-001", "MODEL-A", "PO-001")])

    first = process_scan("MODEL-A", "PO-001", repo, sink, serial="SN-001")
    second = process_scan("MODEL-A", "PO-001", repo, sink, serial="SN-001")

    assert second.receiving_id == first.receiving_id


# -- Regression: genuine no_match path must not be suppressed -----------------


def test_genuine_no_match_from_start_still_emits_no_match() -> None:
    """A barcode+serial that never matched anything still produces a no_match emit.

    Regression guard: the duplicate-scan check must only fire when a claimed row
    with that exact serial exists; a genuinely unknown serial still goes to no_match.
    """
    repo = FakeRepository()
    sink = FakeResultSink()
    repo.upsert_items([_candidate("INV-001", "MODEL-A", "PO-001")])

    record = process_scan("TOTALLY-UNKNOWN-9999", "PO-001", repo, sink, serial="SN-UNKNOWN")

    assert record.match_status == "no_match"
    assert len(sink.emitted) == 1
    assert sink.emitted[0].match_status == "no_match"


def test_different_barcode_no_match_is_independent_of_claimed_unit() -> None:
    """After one unit is received, a scan of a different unknown barcode is a
    distinct no_match -- not suppressed by the already-claimed unit.
    """
    repo = FakeRepository()
    sink = FakeResultSink()
    repo.upsert_items([_candidate("INV-001", "MODEL-A", "PO-001")])

    process_scan("MODEL-A", "PO-001", repo, sink, serial="SN-UNIT-1")
    assert len(sink.emitted) == 1

    record = process_scan("MODEL-COMPLETELY-DIFFERENT", "PO-001", repo, sink, serial="SN-OTHER")

    assert record.match_status == "no_match"
    assert len(sink.emitted) == 2
    assert sink.emitted[1].match_status == "no_match"


def test_no_match_idempotency_still_works_after_rescan_fix() -> None:
    """Two no_match scans of the SAME unknown barcode still emit only once.

    Regression guard: the was_emitted idempotency guard on the no_match path
    must still function after the duplicate-scan check is added.
    """
    repo = FakeRepository()

    class _CountingSink:
        def __init__(self) -> None:
            self.count = 0

        def emit(self, record: object) -> None:
            self.count += 1

        def surface_attention(self, record: object) -> None:
            self.count += 1

    sink = _CountingSink()
    process_scan("NOMATCH-XYZ", "PO-001", repo, sink)
    process_scan("NOMATCH-XYZ", "PO-001", repo, sink)

    assert sink.count == 1, "was_emitted guard must block second no_match emit"


def test_rescan_with_serial_carries_serial_on_already_scanned_record() -> None:
    """Serial from the re-scan appears on the already_scanned record.

    The already_scanned record reflects the serial provided on the duplicate
    scan (same as the original, since serial-based detection requires exact match).
    """
    repo = FakeRepository()
    sink = FakeResultSink()
    repo.upsert_items([_candidate("INV-001", "MODEL-A", "PO-001")])

    process_scan("MODEL-A", "PO-001", repo, sink, serial="SN-DUPLICATE-99")
    second = process_scan("MODEL-A", "PO-001", repo, sink, serial="SN-DUPLICATE-99")

    assert second.match_status == "already_scanned"
    assert second.serial == "SN-DUPLICATE-99"
