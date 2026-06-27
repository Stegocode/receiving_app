"""
Owns: tests for services.receive_sync PASS/PARTIAL outcome paths and ascending-id ordering.
Must not: import concrete portal or board adapters; must not perform real network I/O.
May import: pytest, services.receive_sync, adapters.board (FakeBoard),
            adapters.receiver (FakeReceiver), core.errors, tests.fakes.fake_db.

not_measured: live portal wizard execution, real board API mutations, real browser
              timing, escalation threshold tuning against live failure patterns.
              See DEBT.md [DEBT-T14-001, DEBT-T1-4a-001].

PASS:    failed == 0 and no_match == 0 — all items received.
PARTIAL: failed > 0 or no_match > 0, no kill — completes with warnings.
KILL:    consecutive_failures >= CONSECUTIVE_FAILURE_KILL — tested in test_robot_escalation.py.

Sort PASS:  executor receives items in numeric inventory_id ascending order.
Sort KILL:  a mutant removing the sort or reversing it fails test_ascending_id_order_reverse_input.
"""

from __future__ import annotations

import logging

import pytest

from adapters.board import FakeBoard
from adapters.receiver import FakeReceiver
from services.receive_sync import ReceiveResult, receive_pending
from tests.fakes.fake_db import FakeSyncStatusStore


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


def _store() -> FakeSyncStatusStore:
    return FakeSyncStatusStore()


# ── PASS: all received ────────────────────────────────────────────────────────


def test_all_received() -> None:
    """PASS: 3 valid items, executor returns 'received' for all.

    PASS criterion: failed == 0 and no_match == 0.
    Kills rsync_39 (po_number→None), rsync_41 (model→None), rsync_42 (serial→None):
    executor.calls[i] must contain the actual po/model/serial values.
    """
    items = [_item(f"I{i}", str(100 + i)) for i in range(3)]
    board = FakeBoard(ready_items=items)
    executor = FakeReceiver()

    result = receive_pending(board, executor, _store())

    assert board.received == ["I0", "I1", "I2"]
    assert board.no_match == []
    assert result == ReceiveResult(received=3, no_match=0, failed=0, skipped=0)
    assert executor.closed is False  # lifecycle owned by runner, not service
    assert executor.calls[0] == ("PO-001", "100", "MDL-A", "SN-I0")
    assert executor.calls[1] == ("PO-001", "101", "MDL-A", "SN-I1")
    assert executor.calls[2] == ("PO-001", "102", "MDL-A", "SN-I2")


# ── PARTIAL: mixed outcomes ───────────────────────────────────────────────────


def test_mixed_outcomes() -> None:
    """PARTIAL: received / not_found / finalize_error routed to correct board destinations."""
    items = [_item("I0", "200"), _item("I1", "201"), _item("I2", "202")]
    board = FakeBoard(ready_items=items)
    executor = FakeReceiver(
        outcomes={"200": "received", "201": "not_found", "202": "finalize_error"}
    )

    result = receive_pending(board, executor, _store())

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
        _item("VALID", "300"),
        _item("NO-MODEL", "301", model=""),
        _item("NO-SERIAL", "302", serial=""),
    ]
    board = FakeBoard(ready_items=items)
    executor = FakeReceiver()

    result = receive_pending(board, executor, _store())

    assert "VALID" in board.received
    assert "NO-MODEL" in board.no_match
    assert "NO-SERIAL" in board.no_match
    assert result.skipped == 2
    assert result.received == 1
    assert result.failed == 0
    inv_ids_called = [call[1] for call in executor.calls]
    assert "300" in inv_ids_called
    assert "301" not in inv_ids_called
    assert "302" not in inv_ids_called


# ── PARTIAL: ExecutorError sets needs_attention ───────────────────────────────


def test_executor_error_sets_needs_attention() -> None:
    """ExecutorError → item moved to needs_attention; failed counter incremented.

    The item must NOT be in received or no_match — it goes to needs_attention only.
    A single failure does not kill the loop (consecutive_failures == 1 < 2).
    """
    board = FakeBoard(ready_items=[_item("I0", "400")])
    executor = FakeReceiver(outcomes={"400": "raise"})

    result = receive_pending(board, executor, _store())

    assert result.failed == 1
    assert result.received == 0
    assert "I0" in board.needs_attention
    assert "I0" not in board.received
    assert "I0" not in board.no_match
    assert executor.closed is False  # lifecycle owned by runner, not service


# ── PASS: sync_status written at start and end ────────────────────────────────


def test_sync_status_start_and_stop_written() -> None:
    """receive_pending writes state=running at start and state=stopped at end."""
    board = FakeBoard(ready_items=[_item("I0", "500")])
    executor = FakeReceiver()
    store = FakeSyncStatusStore()

    receive_pending(board, executor, store)

    assert store.writes[0].state == "running"
    assert store.writes[0].last_outcome == "none"
    assert store.writes[-1].state == "stopped"


def test_sync_status_no_raise_on_pass() -> None:
    """SyncKillError is NOT raised when all items succeed."""
    board = FakeBoard(ready_items=[_item("I0", "501")])
    executor = FakeReceiver()

    result = receive_pending(board, executor, _store())  # must not raise

    assert result.received == 1
    assert result.failed == 0


# ── Sort: ascending by numeric inventory_id ────────────────────────────────────


def test_ascending_id_order_reverse_input() -> None:
    """Realistic board order (newest-on-top ≈ reverse) sorts ascending.

    PASS criterion: executor receives inventory_ids in numeric ascending order.
    Kills sort-removal mutant (no sort → reverse order unchanged) and
    descending-sort mutant (descending result ≠ ascending assertion).
    not_measured: live board API ordering guarantees.
    """
    # The board returns newest (highest ID) first — opposite of the receiving system's order.
    ids = ["18985", "18983", "18977", "18976"]
    items = [_item(f"I{iid}", iid) for iid in ids]
    board = FakeBoard(ready_items=items)
    executor = FakeReceiver()

    receive_pending(board, executor, _store())

    inv_ids_called = [call[1] for call in executor.calls]
    assert inv_ids_called == ["18976", "18977", "18983", "18985"]


def test_ascending_id_order_scrambled() -> None:
    """Scrambled inventory_id input arrives at executor in numeric ascending order."""
    ids = ["300", "100", "500", "200", "400"]
    items = [_item(f"I{iid}", iid) for iid in ids]
    board = FakeBoard(ready_items=items)
    executor = FakeReceiver()

    receive_pending(board, executor, _store())

    inv_ids_called = [call[1] for call in executor.calls]
    assert inv_ids_called == ["100", "200", "300", "400", "500"]


def test_ascending_id_order_single_item() -> None:
    """Single-item batch is unaffected by the sort — item still processed."""
    board = FakeBoard(ready_items=[_item("I0", "42000")])
    executor = FakeReceiver()

    result = receive_pending(board, executor, _store())

    assert result.received == 1
    assert executor.calls[0][1] == "42000"


def test_non_numeric_inventory_id_sorts_after_numeric(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Non-numeric inventory_id logs a warning and sorts after all numeric items.

    The item still enters the main loop (not pre-filtered) so the batch does not
    crash.  Numeric items process before it regardless of input order.

    not_measured: log destination; test captures call order and log record.
    """
    items = [
        _item("BAD", "NOT-A-NUMBER"),
        _item("NUMERIC", "18976"),
    ]
    board = FakeBoard(ready_items=items)
    executor = FakeReceiver()

    with caplog.at_level(logging.WARNING, logger="services.receive_sync"):
        receive_pending(board, executor, _store())

    inv_ids_called = [call[1] for call in executor.calls]
    # Numeric item must arrive at executor before the non-numeric one.
    assert inv_ids_called.index("18976") < inv_ids_called.index("NOT-A-NUMBER")
    # Warning must name the bad inventory_id so it is diagnosable.
    assert any("NOT-A-NUMBER" in r.message for r in caplog.records)
