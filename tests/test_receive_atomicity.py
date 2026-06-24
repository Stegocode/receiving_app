"""
Owns: T0-1 atomicity tests for services.receive.process_scan / claim_and_save.
Must not: import concrete adapters; must not perform real network or DB I/O.
May import: pytest, services.receive, core.errors, tests.fakes.

not_measured: real SQLite transaction rollback (covered in test_db.py integration
              tests); concurrent writer races (single-writer assumption documented).

PASS:  crash during claim_and_save → unit still unclaimed, no record saved.
RETRY: after crash, a fresh scan of the same unit succeeds.
GUARD: claim_and_save AND claimed_at IS NULL guard prevents double-claiming.
"""

from __future__ import annotations

import pytest

from core.errors import RepositoryError
from core.schema import ReceivingRecord
from services.receive import process_scan
from tests.fakes.fake_db import FakeRepository
from tests.fakes.fake_sink import FakeResultSink

_TIMESTAMP = "2026-06-19T10:00:00"


def _make_candidate(
    inventory_id: str,
    model_number: str,
    po_number: str,
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
        "quantity": 1,
        "brand": "Brand A",
        "vendor": "Vendor A",
        "tags": "tag1",
        "created_at": _TIMESTAMP,
    }


class _CrashDuringClaimAndSave(FakeRepository):
    """Raises RepositoryError inside claim_and_save before persisting anything.

    Models a process crash / transaction rollback: neither the claim write nor
    the record write reaches storage.  Used to prove the system is recoverable.
    """

    def claim_and_save(self, inventory_id: str, claimed_at: str, record: ReceivingRecord) -> None:
        raise RepositoryError("simulated crash in claim_and_save — transaction rolled back")


def test_crash_in_claim_and_save_leaves_unit_unclaimed_and_no_record() -> None:
    """T0-1 crash simulation: exception during claim_and_save → unit still unclaimed.

    Mutation kill target: any mutation that splits claim_and_save into a separate
    claim() then save_record() would leave the unit claimed-but-unsaved after the
    crash, causing unclaimed_for_po to return an empty list and failing this test.

    With true atomicity (single transaction): the exception rolls back both writes,
    so the unit remains in unclaimed_for_po and no receiving record exists.
    """
    repo = _CrashDuringClaimAndSave()
    sink = FakeResultSink()
    repo.upsert_items([_make_candidate("INV-001", "MODEL-A", "PO-001")])

    with pytest.raises(RepositoryError, match="simulated crash"):
        process_scan("MODEL-A", "PO-001", repo, sink)

    # Unit must remain unclaimed — not orphaned
    unclaimed = repo.unclaimed_for_po("PO-001")
    assert len(unclaimed) == 1, (
        "unit must still appear in unclaimed_for_po after crash — "
        "orphaned claim (claimed but no record) would leave this empty"
    )
    assert unclaimed[0]["inventory_id"] == "INV-001"
    assert unclaimed[0].get("claimed_at") is None, "claimed_at must be None after crash"

    # No receiving record must have been saved
    assert not repo.was_emitted("any-id"), "no record should exist after crash"
    assert len(sink.emitted) == 0


def test_crash_in_claim_and_save_is_recoverable_on_retry() -> None:
    """After a crash, a fresh scan of the same barcode succeeds (unit still unclaimed).

    Verifies the 'recoverable on retry' half of the invariant: the unit is not lost,
    so the operator can re-scan and the system processes it correctly.
    """
    crash_repo = _CrashDuringClaimAndSave()
    crash_repo.upsert_items([_make_candidate("INV-001", "MODEL-A", "PO-001")])
    with pytest.raises(RepositoryError):
        process_scan("MODEL-A", "PO-001", crash_repo, FakeResultSink())

    # Retry with a normal repo seeded with the same (still-unclaimed) inventory
    retry_repo = FakeRepository()
    retry_repo.upsert_items([_make_candidate("INV-001", "MODEL-A", "PO-001")])
    retry_sink = FakeResultSink()

    record = process_scan("MODEL-A", "PO-001", retry_repo, retry_sink)

    assert record.match_status == "received"
    assert record.inventory_id == "INV-001"
    assert retry_repo.was_emitted(record.receiving_id)
    assert len(retry_sink.emitted) == 1


def test_concurrent_claim_guard_preserved_via_claim_and_save() -> None:
    """claim_and_save AND claimed_at IS NULL guard prevents double-claiming.

    Two sequential scans of the same model with two available units:
    each must claim a DISTINCT inventory_id — the guard on claim_and_save
    must exclude already-claimed rows from unclaimed_for_po on the second call.

    Mutation kill target: removing the AND claimed_at IS NULL guard inside
    claim_and_save causes both scans to claim INV-001, making claimed_ids
    contain two identical values and failing the set-length assertion.
    """
    repo = FakeRepository()
    sink = FakeResultSink()
    repo.upsert_items(
        [
            _make_candidate("INV-001", "MODEL-A", "PO-001"),
            _make_candidate("INV-002", "MODEL-A", "PO-001"),
        ]
    )

    rec1 = process_scan("MODEL-A", "PO-001", repo, sink)
    rec2 = process_scan("MODEL-A", "PO-001", repo, sink)

    assert rec1.match_status == "received"
    assert rec2.match_status == "received"
    claimed_ids = {rec1.inventory_id, rec2.inventory_id}
    assert claimed_ids == {"INV-001", "INV-002"}, (
        f"expected two distinct inventory_ids but got: {[rec1.inventory_id, rec2.inventory_id]}"
    )
