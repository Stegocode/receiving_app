"""
Owns: tests for manual model+serial entry and PO-label print call via scan_states.
Must not: open a real Tk window or call real hardware.
May import: adapters.ui.scan_states, tests.fakes, pytest, unittest.mock, stdlib.

not_measured: real Tk widget lifecycle, real printer spool, real DB writes.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import adapters.ui.scan_states as scan_states
from tests.fakes.fake_printer import FakePrinter

# ── on_manual_submit ──────────────────────────────────────────────────────────


def _make_ui(state: str = "IDLE", current_po: str = "10001") -> MagicMock:
    """Return a mock ReceivingUI pre-configured for manual entry tests."""
    ui = MagicMock()
    ui._state = state
    ui._current_po = current_po
    ui._manual_model_var.get.return_value = "MDL-TYPED"
    ui._manual_serial_var.get.return_value = "SN-TYPED"
    return ui


def _capture_thread_start(monkeypatch) -> list[tuple]:
    """Monkeypatch threading.Thread so .start() records (target, args) instead of running."""
    started: list[tuple] = []

    class FakeThread:
        def __init__(self, target, args, daemon=False):
            self._target = target
            self._args = args

        def start(self):
            started.append((self._target, self._args))

    monkeypatch.setattr(scan_states.threading, "Thread", FakeThread)
    return started


def test_on_manual_submit_starts_run_match_with_typed_values(monkeypatch):
    """on_manual_submit routes typed model+serial through ui._run_match."""
    started = _capture_thread_start(monkeypatch)
    ui = _make_ui()

    scan_states.on_manual_submit(ui)

    assert len(started) == 1
    target, args = started[0]
    assert target == ui._run_match
    assert args == ("MDL-TYPED", "SN-TYPED", "10001")


def test_on_manual_submit_strips_whitespace(monkeypatch):
    """Leading/trailing whitespace in typed fields is stripped before routing."""
    started = _capture_thread_start(monkeypatch)
    ui = _make_ui()
    ui._manual_model_var.get.return_value = "  MDL-X  "
    ui._manual_serial_var.get.return_value = "  SN-001  "

    scan_states.on_manual_submit(ui)

    _, args = started[0]
    assert args[0] == "MDL-X"
    assert args[1] == "SN-001"


def test_on_manual_submit_requires_model(monkeypatch):
    """on_manual_submit logs and returns early when model is blank."""
    started = _capture_thread_start(monkeypatch)
    ui = _make_ui()
    ui._manual_model_var.get.return_value = "   "

    scan_states.on_manual_submit(ui)

    assert len(started) == 0
    ui._log.assert_called_once()


def test_on_manual_submit_requires_po(monkeypatch):
    """on_manual_submit logs and returns early when no PO is set."""
    started = _capture_thread_start(monkeypatch)
    ui = _make_ui(current_po="")

    scan_states.on_manual_submit(ui)

    assert len(started) == 0
    ui._log.assert_called_once()


def test_on_manual_submit_sets_state_to_matching(monkeypatch):
    """on_manual_submit sets ui._state = 'MATCHING' before starting the thread."""
    _capture_thread_start(monkeypatch)
    ui = _make_ui()

    scan_states.on_manual_submit(ui)

    assert ui._state == "MATCHING"


def test_on_manual_submit_hides_manual_entry(monkeypatch):
    """on_manual_submit calls hide_manual_entry (collapses the form) before routing."""
    _capture_thread_start(monkeypatch)
    ui = _make_ui()

    scan_states.on_manual_submit(ui)

    ui._manual_frame.place_forget.assert_called()


# ── show / hide manual entry ──────────────────────────────────────────────────


def test_show_manual_entry_blocked_when_state_is_matching():
    """show_manual_entry is a no-op when state is MATCHING (scan in progress)."""
    ui = _make_ui(state="MATCHING")

    scan_states.show_manual_entry(ui)

    ui._manual_frame.place.assert_not_called()


def test_show_manual_entry_blocked_when_no_po():
    """show_manual_entry logs and returns early when no PO is locked."""
    ui = _make_ui(current_po="")

    scan_states.show_manual_entry(ui)

    ui._log.assert_called_once()
    ui._manual_frame.place.assert_not_called()


def test_show_manual_entry_places_frame_when_idle():
    """show_manual_entry places the overlay when state is IDLE and PO is set."""
    ui = _make_ui(state="IDLE")

    scan_states.show_manual_entry(ui)

    ui._manual_frame.place.assert_called_once()


# ── PO label printing via FakePrinter ─────────────────────────────────────────


def test_fake_printer_records_po_label():
    """FakePrinter.print_po_label appends to printed_po_labels."""
    printer = FakePrinter()
    printer.print_po_label("99999")
    assert printer.printed_po_labels == ["99999"]


def test_fake_printer_fail_raises_on_po_label():
    """FakePrinter(fail=True).print_po_label raises PrinterError."""
    from core.errors import PrinterError

    with pytest.raises(PrinterError):
        FakePrinter(fail=True).print_po_label("1")
