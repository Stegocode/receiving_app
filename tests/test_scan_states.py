"""
Owns: tests for adapters.ui.scan_states state-machine transitions.
Must not: import adapters.db, adapters.sink, adapters.source, sqlite3, or real Tk widgets.
May import: adapters.ui.scan_states, core.schema, threading, datetime.

Approach: fake-UI objects (plain Python classes, no tkinter) stub only the attributes
each function under test actually touches, so test breakage pinpoints the cause.

not_measured: real Tkinter rendering, real winsound/bell hardware output,
              flash timing accuracy (after() delays are recorded but not executed),
              live cross-process sync_status polling.

PASS: set_already_scanned → state == ALREADY_SCANNED, distinct from NO_MATCH/MATCH_FOUND.
PASS: set_already_scanned → bell called once, auto-dismiss scheduled at 3000 ms.
PASS: set_already_scanned → state label text contains "ALREADY SCANNED".
PASS: dismiss_no_match clears ALREADY_SCANNED (parallel to NO_MATCH / PRINT_FAILED).
PASS: should_alert_sync_stopped — stopped & not dismissed → True.
PASS: should_alert_sync_stopped — running → False.
PASS: should_alert_sync_stopped — None → False.
PASS: should_alert_sync_stopped — same updated_at dismissed → False.
PASS: should_alert_sync_stopped — new stop (different updated_at) → True.
PASS: set_sync_stopped → state == SYNC_STOPPED, label contains "SYNC STOPPED".
PASS: set_sync_stopped with reason → reason shown in secondary label.
PASS: set_sync_stopped without reason → default message shown.
PASS: dismiss_no_match clears SYNC_STOPPED and records dismissed updated_at.
PASS: dismiss_no_match leaves MATCHING unchanged (no side-effects on non-dismissible states).
"""

from __future__ import annotations

import threading
from datetime import datetime

from adapters.ui import scan_states
from core.schema import SyncStatusRecord, from_dict

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
        self._needs_model_frame = _FakeWidget()
        self._root = _FakeRoot()
        self._idle_called = False
        self._last_sync_stop_at: str | None = None
        self._dismissed_sync_stop_at: str | None = None

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


# ── Tests: should_alert_sync_stopped ─────────────────────────────────────────

_STOP_AT = "2026-06-25T10:00:00+00:00"
_STOP_AT_NEW = "2026-06-25T11:00:00+00:00"


def _stopped(
    updated_at: str = _STOP_AT, reason: str = "2 consecutive failures"
) -> SyncStatusRecord:
    return SyncStatusRecord(
        state="stopped",
        last_outcome="kill",
        consecutive_failures=2,
        stopped_reason=reason,
        updated_at=updated_at,
    )


def _running() -> SyncStatusRecord:
    return SyncStatusRecord(
        state="running",
        last_outcome="success",
        consecutive_failures=0,
        stopped_reason="",
        updated_at=_STOP_AT,
    )


def test_should_alert_when_stopped_and_not_dismissed():
    """state==stopped and no dismissed event → True.

    Mutation kill target: removing the state check returns True for running, breaking
    test_should_not_alert_when_running; removing the return True makes this fail.
    """
    assert scan_states.should_alert_sync_stopped(_stopped(), dismissed_updated_at=None) is True


def test_should_not_alert_when_running():
    """state==running → False regardless of dismissed_updated_at."""
    assert scan_states.should_alert_sync_stopped(_running(), dismissed_updated_at=None) is False


def test_should_not_alert_when_status_none():
    """None status → False (no record yet written by robot)."""
    assert scan_states.should_alert_sync_stopped(None, dismissed_updated_at=None) is False


def test_should_not_alert_when_same_event_dismissed():
    """Same updated_at as dismissed_updated_at → False (already seen this stop).

    Mutation kill target: removing the dismissed guard re-alerts on every poll,
    making an un-dismissable loop.
    """
    assert (
        scan_states.should_alert_sync_stopped(_stopped(_STOP_AT), dismissed_updated_at=_STOP_AT)
        is False
    )


def test_should_alert_when_new_stop_event():
    """Different (newer) updated_at → True even if prior stop was dismissed.

    Mutation kill target: comparing updated_at with == instead of != would suppress
    the new event and keep this returning False.
    """
    assert (
        scan_states.should_alert_sync_stopped(_stopped(_STOP_AT_NEW), dismissed_updated_at=_STOP_AT)
        is True
    )


# ── Tests: set_sync_stopped ───────────────────────────────────────────────────


def test_set_sync_stopped_sets_state():
    """set_sync_stopped must set state to SYNC_STOPPED, not NO_MATCH or any other value."""
    ui = _FakeUI()
    scan_states.set_sync_stopped(ui, "2 consecutive failures")
    assert ui._state == "SYNC_STOPPED"


def test_set_sync_stopped_state_label_contains_sync_stopped():
    """State label must display 'SYNC STOPPED' so the operator sees a distinct signal."""
    ui = _FakeUI()
    scan_states.set_sync_stopped(ui, "")
    texts = [str(c.get("text", "")) for c in ui._state_lbl._configure_calls if "text" in c]
    assert any("SYNC STOPPED" in t for t in texts)


def test_set_sync_stopped_with_reason_shows_reason_in_secondary():
    """When stopped_reason is non-empty, it appears in the secondary label.

    Mutation kill target: substituting the empty-string branch for the reason branch
    would suppress the reason and break operator diagnostics.
    """
    ui = _FakeUI()
    scan_states.set_sync_stopped(ui, "2 consecutive failures")
    texts = [str(c.get("text", "")) for c in ui._sec_lbl._configure_calls if "text" in c]
    assert any("2 consecutive failures" in t for t in texts)


def test_set_sync_stopped_without_reason_shows_default_message():
    """Empty stopped_reason → default fallback text contains 'needs_attention'."""
    ui = _FakeUI()
    scan_states.set_sync_stopped(ui, "")
    texts = [str(c.get("text", "")) for c in ui._sec_lbl._configure_calls if "text" in c]
    assert any("needs_attention" in t for t in texts)


# ── Tests: dismiss SYNC_STOPPED via ESC ──────────────────────────────────────


def test_dismiss_no_match_clears_sync_stopped_state():
    """ESC (dismiss_no_match) must call _set_idle when state is SYNC_STOPPED.

    Mutation kill target: removing SYNC_STOPPED from dismiss routing → _idle_called
    stays False; operator cannot clear the banner.
    """
    ui = _FakeUI()
    ui._state = "SYNC_STOPPED"
    ui._last_sync_stop_at = _STOP_AT

    scan_states.dismiss_no_match(ui)

    assert ui._idle_called is True


def test_dismiss_sync_stopped_records_dismissed_updated_at():
    """dismiss_sync_stopped must copy _last_sync_stop_at → _dismissed_sync_stop_at.

    Without this, the next poll immediately re-alerts for the same event — creating
    an un-dismissable loop.

    Mutation kill target: setting _dismissed_sync_stop_at to None or a constant
    causes the next poll to re-alert, making this assertion fail.
    """
    ui = _FakeUI()
    ui._state = "SYNC_STOPPED"
    ui._last_sync_stop_at = _STOP_AT

    scan_states.dismiss_sync_stopped(ui)

    assert ui._dismissed_sync_stop_at == _STOP_AT
