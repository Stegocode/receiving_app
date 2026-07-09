"""
Owns: tests for the 2b scan flow — PROPOSE/NEEDS_MODEL state transitions,
      turnstile confirmation, scanner block, and dismiss.
Must not: open a real Tk window; no real I/O; no real DB or scanner.
May import: adapters.ui.blocking_states, adapters.ui.scan_states, threading.

Approach: fake-UI objects (plain Python, no Tk) for state-function tests.
          Service/routing tests live in test_model_routing.py.

not_measured: real Tk rendering, focus-poll timing, actual alarm hardware output,
              cross-PO resolution, off-PO board-post round-trip.

PASS thresholds (pre-declared):
  PASS:    all assertions green.
  PARTIAL: none — all behavioral contracts must be covered.
  KILL:    any assertion failure.
"""

from __future__ import annotations

import threading
from typing import Any

from adapters.ui import blocking_states, scan_states

# ── Fake UI infrastructure ─────────────────────────────────────────────────────


class _FakeWidget:
    def __init__(self) -> None:
        self._configure_calls: list[Any] = []
        self.place_forget_called = False

    def configure(self, cnf: Any = None, **kwargs: Any) -> None:
        self._configure_calls.append(cnf if cnf is not None else kwargs)

    def place(self, **kwargs: Any) -> None:
        pass

    def place_forget(self) -> None:
        self.place_forget_called = True

    def focus_force(self) -> None:
        pass


class _FakeVar:
    def __init__(self, val: str = "") -> None:
        self._val = val

    def get(self) -> str:
        return self._val

    def set(self, v: str) -> None:
        self._val = v


class _FakeRoot:
    def __init__(self) -> None:
        self.bell_count = 0
        self.after_calls: list[tuple] = []

    def bell(self) -> None:
        self.bell_count += 1

    def after(self, ms: int, fn: Any, *args: Any) -> None:
        self.after_calls.append((ms, fn, args))

    def after_cancel(self, id: Any) -> None:
        pass


class _FakeUI:
    """Minimal fake ReceivingUI for blocking_states / scan_states function tests."""

    def __init__(self, state: str = "IDLE") -> None:
        self._state = state
        self._model_scan: str | None = None
        self._pending_barcode: str | None = None
        self._proposed_model: str | None = None
        self._current_po = "PO-001"
        self._alarm_event = threading.Event()
        self._flash_after_id = None
        self._reset_btn = _FakeWidget()
        self._right = _FakeWidget()
        self._center = _FakeWidget()
        self._state_lbl = _FakeWidget()
        self._sec_lbl = _FakeWidget()
        self._needs_model_frame = _FakeWidget()
        self._needs_model_lbl = _FakeWidget()
        self._needs_model_var = _FakeVar()
        self._needs_model_entry = _FakeWidget()
        self._root = _FakeRoot()
        self._idle_called = False
        self._log_messages: list[str] = []
        self._save_calls: list[tuple] = []
        self._run_match_calls: list[tuple] = []

        # Injected callables — default to no-ops / True
        self._save_mapping: Any = lambda b, m, s: self._save_calls.append((b, m, s))
        self._check_model_on_po: Any = None

    def _set_idle(self) -> None:
        self._idle_called = True
        self._state = "IDLE"

    def _log(self, msg: str) -> None:
        self._log_messages.append(msg)

    def _run_match(self, model: str, serial: str, po: str) -> None:
        self._run_match_calls.append((model, serial, po))


def _text_in(widget: _FakeWidget, fragment: str) -> bool:
    """Return True if fragment appears in any configure call's text."""
    for call in widget._configure_calls:
        if isinstance(call, dict) and fragment in str(call.get("text", "")):
            return True
    return False


def _alarm_clear(ui: _FakeUI) -> None:
    """Pre-set the alarm event so start_alarm fires cleanly in non-Windows env."""
    ui._alarm_event.set()


# ── set_propose ───────────────────────────────────────────────────────────────


def test_set_propose_sets_state() -> None:
    """State must be PROPOSE after set_propose.

    Mutation kill: returning a different string leaves state unchanged.
    """
    ui = _FakeUI()
    blocking_states.set_propose(ui, "RAW-001", "MDL-A")
    assert ui._state == "PROPOSE"


def test_set_propose_stores_pending_barcode_and_model() -> None:
    """set_propose records the raw barcode and candidate model for the turnstile."""
    ui = _FakeUI()
    blocking_states.set_propose(ui, "RAW-001", "MDL-A")
    assert ui._pending_barcode == "RAW-001"
    assert ui._proposed_model == "MDL-A"


def test_set_propose_state_label_shows_confirm() -> None:
    """State label must display 'CONFIRM MODEL?' so operator knows to re-scan.

    Mutation kill: using 'NOT ON PO' or 'TYPE MODEL' fails the assert.
    """
    ui = _FakeUI()
    blocking_states.set_propose(ui, "RAW-001", "MDL-A")
    assert _text_in(ui._state_lbl, "CONFIRM MODEL?")


def test_set_propose_secondary_label_shows_proposed_model() -> None:
    """Secondary label must include the proposed model name."""
    ui = _FakeUI()
    blocking_states.set_propose(ui, "RAW-001", "MDL-XYZ")
    assert _text_in(ui._sec_lbl, "MDL-XYZ")


def test_set_propose_fires_alarm() -> None:
    """Entering PROPOSE fires start_alarm (same as set-aside / not-on-PO path).

    On non-Windows: bell is called once. The alarm event must be cleared
    (re-armed) before start_alarm fires.

    Mutation kill: removing the start_alarm call → bell_count stays 0.
    """
    ui = _FakeUI()
    ui._alarm_event.set()  # simulate alarm stopped
    blocking_states.set_propose(ui, "RAW-001", "MDL-A")
    assert ui._root.bell_count >= 1


# ── set_needs_model ───────────────────────────────────────────────────────────


def test_set_needs_model_sets_state() -> None:
    """State must be NEEDS_MODEL after set_needs_model.

    Mutation kill: returning PROPOSE or IDLE fails this assert.
    """
    ui = _FakeUI()
    blocking_states.set_needs_model(ui, "RAW-002")
    assert ui._state == "NEEDS_MODEL"


def test_set_needs_model_stores_pending_barcode() -> None:
    """set_needs_model records the raw barcode for mapping save on submit."""
    ui = _FakeUI()
    blocking_states.set_needs_model(ui, "RAW-002")
    assert ui._pending_barcode == "RAW-002"


def test_set_needs_model_state_label_shows_type_model() -> None:
    """State label must show 'TYPE MODEL' — distinct from PROPOSE and NO_MATCH.

    Mutation kill: 'CONFIRM MODEL?' or 'NOT ON PO' fails the fragment check.
    """
    ui = _FakeUI()
    blocking_states.set_needs_model(ui, "RAW-002")
    assert _text_in(ui._state_lbl, "TYPE MODEL")
    assert not _text_in(ui._state_lbl, "CONFIRM MODEL?")
    assert not _text_in(ui._state_lbl, "NOT ON PO")


def test_set_needs_model_fires_alarm() -> None:
    """Entering NEEDS_MODEL fires the set-aside alarm (same as not-on-PO path).

    Mutation kill: removing start_alarm call → bell_count stays 0.
    """
    ui = _FakeUI()
    ui._alarm_event.set()
    blocking_states.set_needs_model(ui, "RAW-002")
    assert ui._root.bell_count >= 1


# ── Turnstile: handle_propose_scan ────────────────────────────────────────────


def test_handle_propose_scan_same_barcode_confirms_and_sets_mid_scan() -> None:
    """Same barcode as pending → confirmed; _model_scan set; state → MID_SCAN.

    Mutation kill: using != instead of == would confirm wrong barcodes.
    """
    ui = _FakeUI(state="PROPOSE")
    ui._pending_barcode = "BARCODE-A"
    ui._proposed_model = "MDL-PROPOSED"
    # scan_states.set_mid_scan needs these widgets present (already in _FakeUI)

    blocking_states.handle_propose_scan(ui, "BARCODE-A")

    assert ui._state == "MID_SCAN"
    assert ui._model_scan == "MDL-PROPOSED"


def test_handle_propose_scan_different_barcode_re_alerts_and_stays_blocked() -> None:
    """Different barcode → re-alert; state stays PROPOSE; model_scan unchanged.

    Mutation kill: branching on any barcode (removing the equality check) would
    confirm all scans, defeating the turnstile.
    """
    ui = _FakeUI(state="PROPOSE")
    ui._pending_barcode = "BARCODE-A"
    ui._proposed_model = "MDL-PROPOSED"
    ui._alarm_event.set()

    blocking_states.handle_propose_scan(ui, "BARCODE-B")

    assert ui._state == "PROPOSE"
    assert ui._model_scan is None
    assert ui._root.bell_count >= 1


def test_handle_propose_scan_empty_barcode_re_alerts() -> None:
    """Empty string is not equal to a real pending barcode → re-alert."""
    ui = _FakeUI(state="PROPOSE")
    ui._pending_barcode = "BARCODE-A"
    ui._proposed_model = "MDL-PROPOSED"
    ui._alarm_event.set()

    blocking_states.handle_propose_scan(ui, "")

    assert ui._state == "PROPOSE"


# ── Block: handle_needs_model_scan ────────────────────────────────────────────


def test_handle_needs_model_scan_always_re_alerts() -> None:
    """Any scan while NEEDS_MODEL → re-alert; state unchanged.

    Mutation kill: not calling start_alarm → bell_count stays 0.
    """
    ui = _FakeUI(state="NEEDS_MODEL")
    ui._alarm_event.set()

    blocking_states.handle_needs_model_scan(ui)

    assert ui._root.bell_count >= 1
    assert ui._state == "NEEDS_MODEL"


def test_handle_needs_model_scan_multiple_scans_keep_blocking() -> None:
    """Three scans in NEEDS_MODEL → three bell events; never advances."""
    ui = _FakeUI(state="NEEDS_MODEL")
    for _ in range(3):
        ui._alarm_event.set()
        blocking_states.handle_needs_model_scan(ui)

    assert ui._root.bell_count >= 3
    assert ui._state == "NEEDS_MODEL"


# ── Dismiss via Esc ───────────────────────────────────────────────────────────


def test_dismiss_no_match_clears_propose() -> None:
    """Esc must call _set_idle when state is PROPOSE.

    Mutation kill: removing PROPOSE from the guard → _idle_called stays False.
    """
    ui = _FakeUI(state="PROPOSE")
    scan_states.dismiss_no_match(ui)
    assert ui._idle_called is True


def test_dismiss_no_match_clears_needs_model() -> None:
    """Esc must call _set_idle when state is NEEDS_MODEL.

    Mutation kill: removing NEEDS_MODEL from the guard → _idle_called stays False.
    """
    ui = _FakeUI(state="NEEDS_MODEL")
    scan_states.dismiss_no_match(ui)
    assert ui._idle_called is True


def test_dismiss_no_match_leaves_matching_unchanged() -> None:
    """Esc must not clear MATCHING (in-flight scan)."""
    ui = _FakeUI(state="MATCHING")
    scan_states.dismiss_no_match(ui)
    assert ui._idle_called is False
    assert ui._state == "MATCHING"
