"""
Owns: T0-2 re-scan idempotency tests for services.receive.process_scan.
Must not: import concrete adapters; must not perform real network or DB I/O.
May import: pytest, services.receive, tests.fakes.

not_measured: real SQLite, real sink API, USB scanner device.

PASS:   received-then-rescanned → match_status='already_scanned', no new board emit.
GUARD:  genuine no_match-from-the-start still emits no_match exactly once.
GUARD:  a different barcode that genuinely doesn't match gets its own no_match.
DATA:   already_scanned record carries the original model_number and inventory_id.
MUTATION kill target: removing the claimed_for_po / already_scanned check causes
    the re-scan to fall through to the no_match path and emit a spurious no_match,
    failing the emit-count and match_status assertions in the primary test.
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


# ── Primary regression test (the case the prior suite missed) ─────────────────


def test_rescan_already_received_returns_already_scanned_and_does_not_emit() -> None:
    """THE MISSING TEST (T0-2): first scan receives; second scan of same barcode
    must NOT emit a spurious no_match.

    Mutation kill target: removing the claimed_for_po check (or removing the early
    return on already_scanned) causes the re-scan to fall into the no_match path.
    The genuine no_match has a different receiving_id (SHA256 with inventory_id=""),
    was_emitted() returns False, and sink.emit() is called a second time.
    That raises len(sink.emitted) to 2 and/or produces a no_match record, failing
    both the emit-count assertion and the match_status assertion.
    """
    repo = FakeRepository()
    sink = FakeResultSink()
    repo.upsert_items([_candidate("INV-001", "MODEL-A", "PO-001")])

    # First scan — successful receive
    first = process_scan("MODEL-A", "PO-001", repo, sink)
    assert first.match_status == "received"
    assert first.inventory_id == "INV-001"
    assert len(sink.emitted) == 1

    # Second scan of the SAME barcode — unit is now claimed
    second = process_scan("MODEL-A", "PO-001", repo, sink)

    assert second.match_status == "already_scanned", (
        f"expected 'already_scanned' on re-scan but got '{second.match_status}'"
    )
    assert second.inventory_id == "INV-001", (
        "already_scanned record must carry the original inventory_id"
    )
    # Critically: no new emit — board is not polluted with a spurious no_match
    assert len(sink.emitted) == 1, (
        f"expected exactly 1 emit total but got {len(sink.emitted)} — "
        "spurious no_match was emitted on re-scan"
    )
    assert len(sink.attention) == 0


def test_rescan_already_received_record_carries_original_model_and_inventory_id() -> None:
    """already_scanned record preserves model_number and inventory_id from the claimed row.

    The scanner UI needs these to show the operator which unit was already scanned.
    Mutation kill target: a mutation that returns a blank/default already_scanned record
    (wrong model_number or empty inventory_id) fails both assertions.
    """
    repo = FakeRepository()
    sink = FakeResultSink()
    repo.upsert_items(
        [_candidate("INV-XYZ", "MODEL-FRIDGE-42", "PO-999", brand="Whirlpool", tags="appliance")]
    )

    process_scan("MODEL-FRIDGE-42", "PO-999", repo, sink)
    second = process_scan("MODEL-FRIDGE-42", "PO-999", repo, sink)

    assert second.match_status == "already_scanned"
    assert second.model_number == "MODEL-FRIDGE-42"
    assert second.inventory_id == "INV-XYZ"
    assert second.purchase_order == "PO-999"


def test_rescan_does_not_save_a_new_record_to_the_repository() -> None:
    """Re-scanning does not add a second receiving record — no board churn.

    After two scans (one real, one duplicate), there is exactly one record
    in the repository and it is already emitted.
    """
    repo = FakeRepository()
    sink = FakeResultSink()
    repo.upsert_items([_candidate("INV-001", "MODEL-A", "PO-001")])

    first = process_scan("MODEL-A", "PO-001", repo, sink)
    process_scan("MODEL-A", "PO-001", repo, sink)  # duplicate

    # Only the original record exists and is emitted
    assert repo.was_emitted(first.receiving_id)
    pending = repo.get_pending()
    assert len(pending) == 0, "re-scan must not leave an unemitted no_match record"


def test_rescan_receiving_id_matches_original_scan() -> None:
    """already_scanned record uses the same receiving_id as the original scan.

    SHA256(po + inventory_id + barcode) is stable across scans of the same unit,
    letting the UI or a log query link the duplicate scan back to the original record.
    """
    repo = FakeRepository()
    sink = FakeResultSink()
    repo.upsert_items([_candidate("INV-001", "MODEL-A", "PO-001")])

    first = process_scan("MODEL-A", "PO-001", repo, sink)
    second = process_scan("MODEL-A", "PO-001", repo, sink)

    assert second.receiving_id == first.receiving_id


# ── Regression: genuine no_match path must not be suppressed ──────────────────


def test_genuine_no_match_from_start_still_emits_no_match() -> None:
    """A barcode that never matched anything still produces a no_match emit.

    Regression guard: the duplicate-scan check must only fire when a claimed row
    matches the barcode; a genuinely unknown barcode must still go to no_match.
    Mutation kill target: a mutation that unconditionally returns already_scanned
    (or suppresses the no_match emit) causes this assertion to fail.
    """
    repo = FakeRepository()
    sink = FakeResultSink()
    repo.upsert_items([_candidate("INV-001", "MODEL-A", "PO-001")])

    record = process_scan("TOTALLY-UNKNOWN-9999", "PO-001", repo, sink)

    assert record.match_status == "no_match"
    assert len(sink.emitted) == 1
    assert sink.emitted[0].match_status == "no_match"


def test_different_barcode_no_match_is_independent_of_claimed_unit() -> None:
    """After one unit is received, a scan of a DIFFERENT unknown barcode is a
    distinct no_match — not suppressed by the already-claimed unit.

    Regression guard: the claimed_for_po match must be barcode-specific; an
    unrelated barcode on the same PO still produces no_match.
    """
    repo = FakeRepository()
    sink = FakeResultSink()
    repo.upsert_items([_candidate("INV-001", "MODEL-A", "PO-001")])

    # Claim MODEL-A
    process_scan("MODEL-A", "PO-001", repo, sink)
    assert len(sink.emitted) == 1

    # Different barcode — genuinely unknown
    record = process_scan("MODEL-COMPLETELY-DIFFERENT", "PO-001", repo, sink)

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
    """Serial passed to re-scan appears on the already_scanned record.

    The operator may scan a serial on the second pass; the returned record
    should carry it even though no new record is written.
    """
    repo = FakeRepository()
    sink = FakeResultSink()
    repo.upsert_items([_candidate("INV-001", "MODEL-A", "PO-001")])

    process_scan("MODEL-A", "PO-001", repo, sink)
    second = process_scan("MODEL-A", "PO-001", repo, sink, serial="SN-DUPLICATE-99")

    assert second.match_status == "already_scanned"
    assert second.serial == "SN-DUPLICATE-99"
