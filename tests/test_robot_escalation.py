"""
Owns: adversarial tests for robot escalation logic (T1-4a).
Must not: import concrete DB or portal adapters; must not perform real network or DB I/O.
May import: pytest, services.receive_sync, adapters.board (FakeBoard),
            adapters.receiver (FakeReceiver), core.errors, tests.fakes.fake_db.

not_measured: live portal timing, real browser behavior, real board API mutations,
              CONSECUTIVE_FAILURE_KILL threshold tuning against live failure patterns.
              See DEBT.md [DEBT-T14-001, DEBT-T1-4a-001].

PASS:    failed == 0 and no_match == 0 — all items received.
PARTIAL: failed > 0 or no_match > 0 but consecutive_failures < 2 — loop completes.
KILL:    consecutive_failures >= CONSECUTIVE_FAILURE_KILL (2) — SyncKillError raised;
         both failing items marked needs_attention before raise.

Mutation targets (must kill):
  - counter reset: consecutive_failures = 0 must be present; removing it would cause
    fail→success→fail to reach 2 (kill incorrectly).
  - threshold: CONSECUTIVE_FAILURE_KILL == 2; changing to 3 must be caught by
    test_two_consecutive_failures_kills.
"""

from __future__ import annotations

import pytest

from adapters.board import FakeBoard
from adapters.receiver import FakeReceiver
from core.errors import SyncKillError
from services.receive_sync import CONSECUTIVE_FAILURE_KILL, receive_pending
from tests.fakes.fake_db import FakeSyncStatusStore


def _item(item_id: str, inventory_id: str, **kw: str) -> dict:
    base = {
        "item_id": item_id,
        "po_number": "PO-001",
        "inventory_id": inventory_id,
        "model": "MDL-A",
        "serial": f"SN-{item_id}",
    }
    base.update(kw)
    return base


# ── Single failure: loop continues, counter == 1 ─────────────────────────────


def test_single_failure_sets_needs_attention_loop_continues() -> None:
    """Single failure → item in needs_attention, loop continues, counter == 1 at stop.

    Kills mutation: CONSECUTIVE_FAILURE_KILL = 2 → 1 would trigger a kill here instead
    of a PARTIAL, causing SyncKillError when only one failure occurred.
    """
    board = FakeBoard(ready_items=[_item("F0", "INV-F0")])
    executor = FakeReceiver(outcomes={"INV-F0": "raise"})
    store = FakeSyncStatusStore()

    result = receive_pending(board, executor, store)  # must not raise

    assert "F0" in board.needs_attention
    assert result.failed == 1
    assert result.received == 0
    # Stopped record has consecutive_failures == 1 (not reset — no success followed)
    assert store.writes[-1].state == "stopped"
    assert store.writes[-1].consecutive_failures == 1
    assert store.writes[-1].last_outcome == "failure"


# ── THE SUBTLE CASE: fail → success → fail does NOT stop ─────────────────────


def test_fail_success_fail_no_kill() -> None:
    """F→S→F: counter goes 0→1, reset to 0, back to 1 — no kill (1 < 2).

    KILL would require TWO failures in a row with NO success between them.
    This test is the explicit adversarial check for the counter-reset path.

    Kills mutation: removing `consecutive_failures = 0` would cause the counter to
    reach 2 on the third item (F→S→F becomes 0→1→2 instead of 0→1→0→1), incorrectly
    triggering SyncKillError and making this test fail.
    """
    items = [_item("F0", "INV-F0"), _item("R0", "INV-R0"), _item("F1", "INV-F1")]
    board = FakeBoard(ready_items=items)
    executor = FakeReceiver(outcomes={"INV-F0": "raise", "INV-F1": "raise"})
    store = FakeSyncStatusStore()

    result = receive_pending(board, executor, store)  # must NOT raise SyncKillError

    assert result.failed == 2
    assert result.received == 1
    assert "F0" in board.needs_attention
    assert "F1" in board.needs_attention
    assert "R0" in board.received
    # Counter was reset to 0 after R0 success, then incremented to 1 for F1
    assert store.writes[-1].consecutive_failures == 1
    assert store.writes[-1].state == "stopped"

    # Verify success write had consecutive_failures == 0
    success_writes = [w for w in store.writes if w.last_outcome == "success"]
    assert len(success_writes) >= 1
    assert all(w.consecutive_failures == 0 for w in success_writes)


# ── Two consecutive failures → SyncKillError ─────────────────────────────────


def test_two_consecutive_failures_kills() -> None:
    """Two consecutive failures → SyncKillError; BOTH items in needs_attention.

    Both items are set to needs_attention (via board.mark_needs_attention) before
    SyncKillError is raised. This is the KILL path.

    Kills mutation: CONSECUTIVE_FAILURE_KILL = 2 → 3 would allow 2 consecutive failures
    to complete as PARTIAL instead of KILL, making this test fail.
    """
    items = [_item("F0", "INV-F0"), _item("F1", "INV-F1")]
    board = FakeBoard(ready_items=items)
    executor = FakeReceiver(outcomes={"INV-F0": "raise", "INV-F1": "raise"})
    store = FakeSyncStatusStore()

    with pytest.raises(SyncKillError, match="consecutive executor failures"):
        receive_pending(board, executor, store)

    assert "F0" in board.needs_attention
    assert "F1" in board.needs_attention
    assert board.received == []
    assert board.no_match == []

    # sync_status reflects kill
    kill_record = store.writes[-1]
    assert kill_record.state == "stopped"
    assert kill_record.last_outcome == "kill"
    assert kill_record.consecutive_failures == 2
    assert kill_record.stopped_reason != ""


def test_two_consecutive_failures_third_item_not_attempted() -> None:
    """Kill fires on the 2nd consecutive failure — 3rd item is never processed."""
    items = [_item("F0", "INV-F0"), _item("F1", "INV-F1"), _item("R0", "INV-R0")]
    board = FakeBoard(ready_items=items)
    executor = FakeReceiver(outcomes={"INV-F0": "raise", "INV-F1": "raise"})
    store = FakeSyncStatusStore()

    with pytest.raises(SyncKillError):
        receive_pending(board, executor, store)

    # R0 was never attempted — executor called exactly twice
    assert len(executor.calls) == 2
    inv_ids_called = [call[1] for call in executor.calls]
    assert "INV-R0" not in inv_ids_called


# ── Success resets the counter ────────────────────────────────────────────────


def test_success_resets_consecutive_failures_to_zero() -> None:
    """Any non-error outcome (received, not_found, finalize_error) resets the counter.

    Kills mutation: removing `consecutive_failures = 0` would leave counter at 1 after
    R0 success, then increment to 2 on F1 (incorrect kill).
    """
    items = [_item("F0", "INV-F0"), _item("R0", "INV-R0")]
    board = FakeBoard(ready_items=items)
    executor = FakeReceiver(outcomes={"INV-F0": "raise"})
    store = FakeSyncStatusStore()

    result = receive_pending(board, executor, store)  # must not raise

    assert result.failed == 1
    assert result.received == 1
    # Final stopped record: counter was reset by R0 success, so consecutive_failures == 0
    assert store.writes[-1].consecutive_failures == 0


def test_not_found_also_resets_counter() -> None:
    """not_found outcome (no_match path) resets the consecutive_failures counter."""
    items = [_item("F0", "INV-F0"), _item("NF0", "INV-NF0"), _item("F1", "INV-F1")]
    board = FakeBoard(ready_items=items)
    executor = FakeReceiver(outcomes={"INV-F0": "raise", "INV-NF0": "not_found", "INV-F1": "raise"})
    store = FakeSyncStatusStore()

    result = receive_pending(board, executor, store)  # must NOT raise

    assert result.failed == 2
    assert result.no_match == 1
    assert store.writes[-1].consecutive_failures == 1  # reset by NF0, then +1 for F1


# ── No auto-retry ─────────────────────────────────────────────────────────────


def test_no_item_auto_retried() -> None:
    """Each item is passed to executor exactly once regardless of outcome."""
    items = [_item("F0", "INV-F0"), _item("R0", "INV-R0"), _item("F1", "INV-F1")]
    board = FakeBoard(ready_items=items)
    executor = FakeReceiver(outcomes={"INV-F0": "raise", "INV-F1": "raise"})
    store = FakeSyncStatusStore()

    receive_pending(board, executor, store)

    # Each inventory_id appears exactly once in executor.calls
    inv_ids = [call[1] for call in executor.calls]
    assert inv_ids.count("INV-F0") == 1
    assert inv_ids.count("INV-R0") == 1
    assert inv_ids.count("INV-F1") == 1
    assert len(inv_ids) == 3


# ── sync_status reflects transitions ─────────────────────────────────────────


def test_sync_status_transitions_on_kill() -> None:
    """sync_status write sequence for the KILL path: start→failure→kill(stopped)."""
    items = [_item("F0", "INV-F0"), _item("F1", "INV-F1")]
    board = FakeBoard(ready_items=items)
    executor = FakeReceiver(outcomes={"INV-F0": "raise", "INV-F1": "raise"})
    store = FakeSyncStatusStore()

    with pytest.raises(SyncKillError):
        receive_pending(board, executor, store)

    outcomes = [w.last_outcome for w in store.writes]
    assert outcomes[0] == "none"  # run start
    assert "failure" in outcomes  # per-item failure write
    assert outcomes[-1] == "kill"  # final stopped record

    states = [w.state for w in store.writes]
    assert states[0] == "running"
    assert states[-1] == "stopped"


def test_sync_status_transitions_on_partial() -> None:
    """sync_status write sequence for PARTIAL: start → success/failure → stopped/failure."""
    items = [_item("F0", "INV-F0"), _item("R0", "INV-R0")]
    board = FakeBoard(ready_items=items)
    executor = FakeReceiver(outcomes={"INV-F0": "raise"})
    store = FakeSyncStatusStore()

    receive_pending(board, executor, store)

    outcomes = [w.last_outcome for w in store.writes]
    assert outcomes[0] == "none"
    assert "failure" in outcomes
    assert "success" in outcomes
    assert outcomes[-1] == "failure"  # final record reflects partial failure
    assert store.writes[-1].state == "stopped"


# ── CONSECUTIVE_FAILURE_KILL constant ────────────────────────────────────────


def test_consecutive_failure_kill_constant_is_two() -> None:
    """CONSECUTIVE_FAILURE_KILL must be 2 — the mutation gate.

    A change to 3 would be caught by test_two_consecutive_failures_kills above,
    but this test explicitly anchors the constant value so a rename doesn't obscure it.
    """
    assert CONSECUTIVE_FAILURE_KILL == 2
