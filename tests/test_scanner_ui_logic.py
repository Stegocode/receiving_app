"""
Owns: tests for adapters.ui.scanner_ui module-level logic (_note_poll_error,
      _populate_and_queue).
Must not: construct Tk widgets; must not import tkinter; must not perform real I/O.
May import: adapters.ui.scanner_ui, pytest.

Approach: call module-level pure functions directly with lightweight stubs
(lists as accumulators, plain callables) — same pattern as test_scan_states.py.

not_measured: Tk focus behaviour, UI rendering, real populate side-effects,
              50 ms timer accuracy.

PASS: _note_poll_error logs first exception; suppresses all repeats.
PASS: _populate_and_queue queues PO on success.
PASS: _populate_and_queue does NOT queue PO on failure; logs error instead.
PASS: normal populate-success path (no regression).
"""

from __future__ import annotations

from adapters.ui.scanner_ui import _note_poll_error, _populate_and_queue

# ── _note_poll_error ──────────────────────────────────────────────────────────


def test_note_poll_error_logs_first_exception():
    """First exception is forwarded to log_fn exactly once.

    Mutation kill target: removing the `if not logged[0]` guard causes every call
    to log, breaking test_note_poll_error_suppresses_repeats; removing the log_fn
    call keeps logged empty, failing this test.
    """
    logged: list[str] = []
    _note_poll_error(ValueError("boom"), [False], logged.append)
    assert len(logged) == 1
    assert "boom" in logged[0]


def test_note_poll_error_suppresses_repeats():
    """Three calls with the same logged flag produce exactly one log entry.

    Mutation kill target: flipping the `if not logged[0]` guard to `if logged[0]`
    would suppress the first call and log the second, breaking the previous test
    and making len(logged) == 2 here.
    """
    logged: list[str] = []
    logged_flag: list[bool] = [False]
    exc = RuntimeError("recurring fault")
    _note_poll_error(exc, logged_flag, logged.append)
    _note_poll_error(exc, logged_flag, logged.append)
    _note_poll_error(exc, logged_flag, logged.append)
    assert len(logged) == 1


# ── _populate_and_queue ───────────────────────────────────────────────────────


def test_populate_success_queues_po():
    """Successful populate → queue_fn called with the PO.

    Mutation kill target: moving queue_fn(po) inside the except branch causes
    it to be called only on failure, leaving queued empty here.
    """
    queued: list[str] = []

    def populate(po: str) -> None:
        pass

    _populate_and_queue(populate, "11782", lambda _msg: None, queued.append)
    assert queued == ["11782"]


def test_populate_failure_does_not_queue_po():
    """Failed populate → queue_fn NOT called; error is surfaced via log_fn.

    Mutation kill target: placing queue_fn(po) outside the try block (the original
    bug) would add the PO to queued even on failure, causing this assertion to fail.
    """
    queued: list[str] = []
    logged: list[str] = []

    def populate(po: str) -> None:
        raise RuntimeError("database unavailable")

    _populate_and_queue(populate, "11783", logged.append, queued.append)
    assert queued == []
    assert any("error" in msg.lower() for msg in logged)


def test_populate_failure_logs_the_po_number():
    """Error log message contains the PO number so the operator can identify the failure."""
    logged: list[str] = []

    def populate(po: str) -> None:
        raise OSError("network timeout")

    _populate_and_queue(populate, "99001", logged.append, lambda _: None)
    assert any("99001" in msg for msg in logged)
