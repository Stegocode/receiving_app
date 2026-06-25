"""
Owns: tests for adapters.ui.scan_states state-machine transitions.
Must not: import adapters.db, adapters.sink, adapters.source, sqlite3, or real Tk widgets.
May import: adapters.ui.scan_states, core.schema, threading, datetime.

Approach: fake-UI objects (plain Python classes, no tkinter) stub only the attributes
each function under test actually touches, so test breakage pinpoints the cause.

not_measured: real Tkinter rendering, real winsound/bell hardware output,
              flash timing accuracy (after() delays are recorded but not executed).

PASS: set_already_scanned → state == ALREADY_SCANNED, distinct from NO_MATCH/MATCH_FOUND.
PASS: set_already_scanned → bell called once, auto-dismiss scheduled at 3000 ms.
PASS: set_already_scanned → state label text contains "ALREADY SCANNED".
PASS: dismiss_no_match clears ALREADY_SCANNED (parallel to NO_MATCH / PRINT_FAILED).
"""

from __future__ import annotations

import threading
from datetime import datetime

from adapters.ui import scan_states
from core.schema import from_dict

# ── Fake UI infrastructure ────────────────────────────────────────────────────


class _FakeWidget:
    def __init__(self) -> None:
        self._configure_calls: list[dict] = []
        self.place_forget_called = False

    def configure(self, **kwargs: object) -> None:
        self._configure_calls.append(kwargs)

    def place(self, **kwargs: object) -> None:
        pass

    def place_forget(self) -> None:
        self.place_forget_called = True


class _FakeRoot:
    def __init__(self) -> None:
        self.bell_count = 0
        self.after_calls: list[tuple] = []

    def bell(self) -> None:
        self.bell_count += 1

    def after(self, ms: int, fn: object, *args: object) -> None:
        self.after_calls.append((ms, fn, args))

    def after_cancel(self, id: object) -> None:
        pass


class _FakeUI:
    def __init__(self) -> None:
        self._state = "MATCHING"
        self._model_scan: str | None = "MODEL-A"
        self._alarm_event = threading.Event()
        self._flash_after_id = None
        self._reset_btn = _FakeWidget()
        self._right = _FakeWidget()
        self._center = _FakeWidget()
        self._state_lbl = _FakeWidget()
        self._sec_lbl = _FakeWidget()
        self._root = _FakeRoot()
        self._idle_called = False

    def _set_idle(self) -> None:
        self._idle_called = True


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_record(status: str) -> object:
    return from_dict(
        {
            "receiving_id": "scan-states-test-001",
            "purchase_order": "PO-TEST",
            "inventory_id": "INV-42" if status == "received" else "",
            "model_number": "MODEL-X",
            "product_category": "",
            "truck": "",
            "stop": "",
            "sales_order": "",
            "product_size": {"w": 0, "d": 0, "h": 0},
            "quantity": 1,
            "match_status": status,
            "timestamp": datetime.now().isoformat(),
        }
    )


# ── Tests: set_already_scanned ────────────────────────────────────────────────


def test_set_already_scanned_sets_state_distinct_from_no_match_and_received():
    """State must be ALREADY_SCANNED — not NO_MATCH, not MATCH_FOUND.

    Mutation kill target: changing ALREADY_SCANNED literal to NO_MATCH or any other
    state would fail the positive assert and reveal the collapse.
    """
    ui = _FakeUI()
    scan_states.set_already_scanned(ui, _make_record("already_scanned"))

    assert ui._state == "ALREADY_SCANNED"
    assert ui._state != "NO_MATCH"
    assert ui._state != "MATCH_FOUND"
    assert ui._state != "PRINT_FAILED"


def test_set_already_scanned_calls_bell_once_and_schedules_auto_dismiss():
    """A single bell is issued and auto-dismiss is scheduled at 3000 ms.

    Mutation kill target 1: removing ui._root.bell() → bell_count stays 0.
    Mutation kill target 2: removing ui._root.after() → after_calls stays empty,
    or changing 3000 → 2000 → second assert fails.
    """
    ui = _FakeUI()
    scan_states.set_already_scanned(ui, _make_record("already_scanned"))

    assert ui._root.bell_count == 1
    assert len(ui._root.after_calls) == 1
    delay_ms, _, _ = ui._root.after_calls[0]
    assert delay_ms == 3000


def test_set_already_scanned_state_label_shows_already_scanned():
    """The state label must be configured with the text 'ALREADY SCANNED'.

    This verifies the operator sees a distinct signal, not the no_match 'NOT ON PO'
    text or the matched 'MATCHED' text.

    Mutation kill target: substituting 'NOT ON PO' or empty string fails the assert.
    """
    ui = _FakeUI()
    record = _make_record("already_scanned")
    scan_states.set_already_scanned(ui, record)

    texts = [str(call.get("text", "")) for call in ui._state_lbl._configure_calls if "text" in call]
    assert any("ALREADY SCANNED" in t for t in texts), (
        f"Expected 'ALREADY SCANNED' in state_lbl configure calls; got {texts}"
    )
    assert not any("NOT ON PO" in t for t in texts)
    assert not any("MATCHED" in t for t in texts)


def test_dismiss_no_match_clears_already_scanned_state():
    """dismiss_no_match must call _set_idle() when state is ALREADY_SCANNED.

    Parallel to the existing NO_MATCH and PRINT_FAILED paths.  If ALREADY_SCANNED
    is omitted from the guard, the operator cannot clear the banner with Esc.

    Mutation kill target: removing ALREADY_SCANNED from the tuple → _idle_called
    remains False, failing the assert.
    """
    ui = _FakeUI()
    ui._state = "ALREADY_SCANNED"

    scan_states.dismiss_no_match(ui)

    assert ui._idle_called is True


def test_dismiss_no_match_leaves_other_states_unchanged():
    """dismiss_no_match must not clear states it does not own (e.g. MATCHING)."""
    ui = _FakeUI()
    ui._state = "MATCHING"

    scan_states.dismiss_no_match(ui)

    assert ui._idle_called is False
    assert ui._state == "MATCHING"
