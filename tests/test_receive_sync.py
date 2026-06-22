"""
Owns: tests for services.receive_sync PASS/PARTIAL/KILL outcome paths.
Must not: import concrete portal or board adapters; must not perform real network I/O.
May import: pytest, services.receive_sync, adapters.board (FakeBoard),
            adapters.receiver (FakeReceiver), core.errors.

not_measured: live portal wizard execution, real board API mutations, real browser
              timing, breaker threshold tuning against live failure patterns.
              See DEBT.md [DEBT-T14-001].

RECEIVE_KILL_THRESHOLD = 0.5 (mirrors services/receive_sync.py)
MIN_ATTEMPTS_BEFORE_KILL = 5 (mirrors services/receive_sync.py)

PASS:    failed == 0 and no_match == 0 — all items received.
PARTIAL: failed > 0 or no_match > 0, no kill — completes with warnings.
KILL:    received / attempted < 0.5 after >= 5 attempts — SyncKillError raised.
"""

from __future__ import annotations

import pytest

from adapters.board import FakeBoard
from adapters.receiver import FakeReceiver
from core.errors import SyncKillError
from services.receive_sync import ReceiveResult, receive_pending


def _item(item_id: str, inventory_id: str, **overrides: str) -> dict:
    """Build a valid board item dict; override any field via kwargs."""
    base = {
        "item_id": item_id,
        "po_number": "PO-001",
        "inventory_id": inventory_id,
        "model": "MDL-A",
        "serial": f"SN-{item_id}",
    }
    base.update(overrides)
    return base


# ── PASS: all received ────────────────────────────────────────────────────────


def test_all_received() -> None:
    """PASS: 3 valid items, executor returns 'received' for all.

    PASS criterion: failed == 0 and no_match == 0.
    Kills rsync_39 (po_number→None), rsync_41 (model→None), rsync_42 (serial→None):
    executor.calls[i] must contain the actual po/model/serial values.
    """
    items = [_item(f"I{i}", f"INV-{i}") for i in range(3)]
    board = FakeBoard(ready_items=items)
    executor = FakeReceiver()

    result = receive_pending(board, executor)

    assert board.received == ["I0", "I1", "I2"]
    assert board.no_match == []
    assert result == ReceiveResult(received=3, no_match=0, failed=0, skipped=0)
    assert executor.closed is True
    # Each call must carry the real field values from the item dict.
    assert executor.calls[0] == ("PO-001", "INV-0", "MDL-A", "SN-I0")
    assert executor.calls[1] == ("PO-001", "INV-1", "MDL-A", "SN-I1")
    assert executor.calls[2] == ("PO-001", "INV-2", "MDL-A", "SN-I2")


# ── PARTIAL: mixed outcomes ───────────────────────────────────────────────────


def test_mixed_outcomes() -> None:
    """PARTIAL: received / not_found / finalize_error routed to correct board destinations."""
    items = [
        _item("I0", "INV-0"),
        _item("I1", "INV-1"),
        _item("I2", "INV-2"),
    ]
    board = FakeBoard(ready_items=items)
    executor = FakeReceiver(
        outcomes={"INV-0": "received", "INV-1": "not_found", "INV-2": "finalize_error"}
    )

    result = receive_pending(board, executor)

    assert "I0" in board.received
    assert "I1" in board.no_match
    assert "I2" in board.no_match
    assert result.received == 1
    assert result.no_match == 2
    assert result.failed == 0
    assert result.skipped == 0


# ── PARTIAL: invalid items skipped ───────────────────────────────────────────


def test_invalid_items_skipped() -> None:
    """Items missing required fields are skipped; executor is never invoked for them."""
    items = [
        _item("VALID", "INV-VALID"),
        _item("NO-MODEL", "INV-NM", model=""),
        _item("NO-SERIAL", "INV-NS", serial=""),
    ]
    board = FakeBoard(ready_items=items)
    executor = FakeReceiver()

    result = receive_pending(board, executor)

    assert "VALID" in board.received
    assert "NO-MODEL" in board.no_match
    assert "NO-SERIAL" in board.no_match
    assert result.skipped == 2
    assert result.received == 1
    assert result.failed == 0
    inv_ids_called = [call[1] for call in executor.calls]
    assert "INV-VALID" in inv_ids_called
    assert "INV-NM" not in inv_ids_called
    assert "INV-NS" not in inv_ids_called


# ── PARTIAL: ExecutorError leaves item in READY ───────────────────────────────


def test_executor_error_leaves_item_ready() -> None:
    """ExecutorError → failed counter incremented; item NOT moved to received or no_match."""
    board = FakeBoard(ready_items=[_item("I0", "INV-ERR")])
    executor = FakeReceiver(outcomes={"INV-ERR": "raise"})

    result = receive_pending(board, executor)

    assert result.failed == 1
    assert result.received == 0
    assert "I0" not in board.received
    assert "I0" not in board.no_match
    assert executor.closed is True


# ── KILL: circuit breaker mid-loop ───────────────────────────────────────────


def test_kill_trips_when_no_match_inflates_attempted() -> None:
    """KILL: 3 received + 4 no_match → attempted = 7, ratio = 3/7 ≈ 0.43 < 0.5 → KILL.

    Kills mutmut_79: `attempted = received + no_match + failed` → `received - no_match + failed`
    would compute -1, never reaching MIN_ATTEMPTS_BEFORE_KILL, so no kill fires.
    """
    items_r = [_item(f"R{i}", f"INV-R{i}") for i in range(3)]
    items_nm = [_item(f"NM{i}", f"INV-NM{i}") for i in range(4)]
    board = FakeBoard(ready_items=items_r + items_nm)
    outcomes: dict[str, str] = {f"INV-R{i}": "received" for i in range(3)}
    outcomes.update({f"INV-NM{i}": "not_found" for i in range(4)})
    executor = FakeReceiver(outcomes=outcomes)

    with pytest.raises(SyncKillError, match="receive aborted"):
        receive_pending(board, executor)


def test_kill_trips_with_some_received_majority_failed() -> None:
    """KILL: 1 received + 4 failed → ratio = 1/5 = 0.2 < 0.5 → KILL.

    Kills mutmut_82: `received / attempted` → `received * attempted` would compute
    1 * 5 = 5, which is NOT < 0.5, so the kill never fires.
    """
    items = [_item("R0", "INV-R0")] + [_item(f"F{i}", f"INV-F{i}") for i in range(4)]
    board = FakeBoard(ready_items=items)
    executor = FakeReceiver(outcomes={f"INV-F{i}": "raise" for i in range(4)})

    with pytest.raises(SyncKillError, match="receive aborted"):
        receive_pending(board, executor)


def test_boundary_exactly_half_received_not_killed() -> None:
    """BOUNDARY: 3 received + 3 failed → ratio = 3/6 = 0.5, NOT < 0.5 → no kill.

    Kills mutmut_83: `< RECEIVE_KILL_THRESHOLD` → `<=` would incorrectly kill
    when ratio is exactly 0.5 (boundary belongs to PARTIAL, not KILL).

    Items ordered so attempted first reaches 5 at ratio 0.6 (no kill), then 6 at 0.5
    (boundary — must not kill).
    """
    items = [
        _item("R0", "INV-R0"),
        _item("R1", "INV-R1"),
        _item("F0", "INV-F0"),
        _item("F1", "INV-F1"),
        _item("R2", "INV-R2"),
        _item("F2", "INV-F2"),
    ]
    board = FakeBoard(ready_items=items)
    executor = FakeReceiver(
        outcomes={
            "INV-R0": "received",
            "INV-R1": "received",
            "INV-R2": "received",
            "INV-F0": "raise",
            "INV-F1": "raise",
            "INV-F2": "raise",
        }
    )

    result = receive_pending(board, executor)  # must NOT raise

    assert result.received == 3
    assert result.failed == 3
    assert result.no_match == 0


def test_kill_trips_mid_loop_and_aborts() -> None:
    """KILL: 5 failing items trip the breaker; remaining 3 items not attempted.

    KILL criterion: received/attempted = 0/5 = 0.0 < 0.5 after MIN_ATTEMPTS_BEFORE_KILL.
    Verifies the mid-loop check — remaining items are untouched (still READY).
    """
    failing = [_item(f"F{i}", f"INV-F{i}") for i in range(5)]
    extra = [_item(f"M{i}", f"INV-M{i}") for i in range(3)]
    board = FakeBoard(ready_items=failing + extra)
    executor = FakeReceiver(outcomes={f"INV-F{i}": "raise" for i in range(5)})

    with pytest.raises(SyncKillError, match="receive aborted"):
        receive_pending(board, executor)

    assert len(executor.calls) == 5
    assert len(executor.calls) < len(failing) + len(extra)
    assert executor.closed is True
