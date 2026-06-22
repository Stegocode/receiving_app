"""
Owns: tests for services.sync PASS/PARTIAL/KILL outcome paths.
Must not: import concrete adapters; must not perform real network or DB I/O.
May import: pytest, services.sync, tests.fakes.

not_measured: real network calls, real SQLite file, real result sink API,
              real USB scanner device, real Tkinter UI.

KILL_THRESHOLD = 0.5 (mirrors services/sync.py)
PASS:    100% of pending items succeed — no exception, errors == 0.
PARTIAL: success rate >= KILL_THRESHOLD and < 100% — no exception, errors > 0.
KILL:    success rate < KILL_THRESHOLD — SyncKillError raised.
"""

from __future__ import annotations

import pytest

from core.errors import SinkError, SyncKillError
from core.schema import ReceivingRecord, from_dict
from services.sync import SyncResult, sync_pending
from tests.fakes.fake_db import FakeRepository
from tests.fakes.fake_sink import FakeResultSink

_TIMESTAMP = "2026-06-19T10:00:00"


def _make_record(receiving_id: str, match_status: str = "received") -> ReceivingRecord:
    """Build a ReceivingRecord suitable for seeding FakeRepository via save_record."""
    return from_dict(
        {
            "receiving_id": receiving_id,
            "purchase_order": "PO-001",
            "inventory_id": "INV-001",
            "model_number": "MODEL-A",
            "product_category": "Furniture",
            "truck": "T1",
            "stop": "S1",
            "sales_order": "SO-001",
            "product_size": {"w": 10.0, "d": 20.0, "h": 30.0},
            "quantity": 1,
            "match_status": match_status,
            "timestamp": _TIMESTAMP,
        }
    )


class _FailOnIdSink:
    """Raises SinkError for any record whose receiving_id is in the fail set."""

    def __init__(self, fail_ids: set[str]) -> None:
        self._fail_ids = fail_ids

    def emit(self, record: ReceivingRecord) -> None:
        if record.receiving_id in self._fail_ids:
            raise SinkError("test-induced sink failure")

    def surface_attention(self, record: ReceivingRecord) -> None:
        if record.receiving_id in self._fail_ids:
            raise SinkError("test-induced sink failure")


def test_sync_pass() -> None:
    """PASS: 5 of 5 pending succeed → SyncResult with errors == 0, received + no_match == 5.

    PASS criterion: success rate == 1.0 (all items processed without error).
    """
    repo = FakeRepository()
    sink = FakeResultSink()
    for i in range(5):
        repo.save_record(_make_record(f"REC-{i:03d}"))

    result = sync_pending(repo, sink)

    assert isinstance(result, SyncResult)
    assert result.errors == 0
    assert result.processed == 5
    assert result.received + result.no_match == 5


def test_sync_partial() -> None:
    """PARTIAL: 1 of 5 errors → SyncResult returned (no exception), errors == 1.

    PARTIAL criterion: success rate 4/5 = 0.80 ≥ KILL_THRESHOLD 0.50 and < 1.0.
    """
    repo = FakeRepository()
    fail_ids = {"REC-004"}
    sink = _FailOnIdSink(fail_ids)
    for i in range(5):
        repo.save_record(_make_record(f"REC-{i:03d}"))

    result = sync_pending(repo, sink)

    assert result.errors == 1
    assert result.processed == 5
    assert result.received + result.no_match == 4  # 4 succeeded


def test_sync_kill() -> None:
    """KILL: 3 of 5 errors → SyncKillError raised with a non-None message.

    KILL criterion: success rate 2/5 = 0.40 < KILL_THRESHOLD 0.50.
    Kills mutmut_70: SyncKillError(None) — match= fails on None str().
    """
    repo = FakeRepository()
    fail_ids = {"REC-002", "REC-003", "REC-004"}
    sink = _FailOnIdSink(fail_ids)
    for i in range(5):
        repo.save_record(_make_record(f"REC-{i:03d}"))

    with pytest.raises(SyncKillError, match="sync aborted"):
        sync_pending(repo, sink)


def test_sync_boundary_exactly_half() -> None:
    """BOUNDARY: 1 error of 2 → success_rate exactly 0.50 → PARTIAL, NOT KILL.

    PARTIAL criterion: success rate 1/2 = 0.50 >= KILL_THRESHOLD 0.50 and < 1.0.
    Pins that the boundary value 0.50 lands in PARTIAL, not KILL.
    """
    repo = FakeRepository()
    fail_ids = {"REC-001"}
    sink = _FailOnIdSink(fail_ids)
    repo.save_record(_make_record("REC-000"))
    repo.save_record(_make_record("REC-001"))

    result = sync_pending(repo, sink)  # must NOT raise SyncKillError

    assert result.processed == 2
    assert result.errors == 1
    assert result.received + result.no_match == 1


def test_sync_no_match_counted_separately() -> None:
    """no_match records counted in result.no_match; received in result.received.

    Uses 1 received + 2 no_match (asymmetric) to kill two related mutants:
      - mutmut_17: `== "received"` → `!= "received"` — swaps counters, giving 2/1 not 1/2.
      - mutmut_23: `no_match += 1` → `no_match = 1` — second no_match stays at 1, not 2.
    """
    repo = FakeRepository()
    sink = FakeResultSink()
    repo.save_record(_make_record("REC-000", match_status="received"))
    repo.save_record(_make_record("REC-001", match_status="no_match"))
    repo.save_record(_make_record("REC-002", match_status="no_match"))

    result = sync_pending(repo, sink)

    assert result.received == 1
    assert result.no_match == 2
    assert result.errors == 0
    assert result.processed == 3


def test_sync_empty_pending_returns_zero_result() -> None:
    """PASS with zero pending items returns a zero SyncResult without dividing by zero.

    Kills mutmut_49: `processed > 0` → `processed >= 0` would attempt (0-0)/0 → ZeroDivisionError.
    """
    repo = FakeRepository()  # no records seeded
    sink = FakeResultSink()

    result = sync_pending(repo, sink)

    assert result.processed == 0
    assert result.received == 0
    assert result.no_match == 0
    assert result.errors == 0


def test_sync_single_failure_triggers_kill() -> None:
    """KILL: 1 of 1 fails → success_rate = 0/1 = 0.0 < KILL_THRESHOLD → SyncKillError.

    Kills mutmut_50: `processed > 0` → `processed > 1` would skip the rate check when
    processed == 1, using else 1.0 → no kill.
    """
    repo = FakeRepository()
    sink = _FailOnIdSink({"REC-000"})
    repo.save_record(_make_record("REC-000"))

    with pytest.raises(SyncKillError):
        sync_pending(repo, sink)


def test_sync_needs_attention_calls_surface_attention() -> None:
    """needs_attention records route to sink.surface_attention, not sink.emit.

    Covers L46 (sink.surface_attention) — the third valid match_status branch.
    """
    repo = FakeRepository()
    sink = FakeResultSink()
    repo.save_record(_make_record("REC-000", match_status="needs_attention"))

    result = sync_pending(repo, sink)

    assert result.processed == 1
    assert result.errors == 0
    assert len(sink.attention) == 1
    assert len(sink.emitted) == 0
    assert sink.attention[0].receiving_id == "REC-000"
