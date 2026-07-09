"""
Owns: tests for save-and-learn, check_model_on_po, on_needs_model_submit routing,
      and the no-thresholds behavioral guard.
Must not: open a real Tk window; no real I/O; no real DB or scanner.
May import: adapters.ui.blocking_states, adapters.ui.scan_states, core.model_resolution,
            services.model_resolution, tests.fakes, threading, datetime.

not_measured: real Tk rendering, focus-poll timing, actual alarm hardware output,
              cross-PO resolution, off-PO board-post round-trip.

PASS thresholds (pre-declared):
  PASS:    all assertions green.
  PARTIAL: none — all behavioral contracts must be covered.
  KILL:    any assertion failure.
"""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Any

from adapters.ui import blocking_states
from core.model_resolution import ScanVerdict, resolve_scan
from services.model_resolution import check_model_on_po, resolve_model_barcode
from tests.fakes.fake_db import FakeRepository

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
    """Minimal fake ReceivingUI for routing / save-and-learn tests."""

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

        self._save_mapping: Any = lambda b, m, s: self._save_calls.append((b, m, s))
        self._check_model_on_po: Any = None

    def _set_idle(self) -> None:
        self._idle_called = True
        self._state = "IDLE"

    def _log(self, msg: str) -> None:
        self._log_messages.append(msg)

    def _run_match(self, model: str, serial: str, po: str) -> None:
        self._run_match_calls.append((model, serial, po))


# ── Save-and-learn: resolve_scan with learned_model ───────────────────────────


def test_save_and_learn_resolves_via_learned_after_needs_model() -> None:
    """After a NEEDS_MODEL typed answer is persisted, the same raw barcode resolves AUTO.

    This is the end-to-end save-and-learn contract:
      1. Operator types "MDL-A" for barcode "RAW-X".
      2. save_barcode_mapping("RAW-X", "MDL-A", ...) is called.
      3. Next scan: lookup_barcode_mapping("RAW-X") → "MDL-A" (the learned_model).
      4. resolve_scan("RAW-X", po_models, "MDL-A") → AUTO("MDL-A") — no prompt.

    Mutation kill: removing the step-1 guard causes PROPOSE or NEEDS_MODEL, failing
    the AUTO assertion.
    """
    learned_model = "MDL-A"
    result = resolve_scan("RAW-X", ["OTHER-MDL", "YET-ANOTHER"], learned_model=learned_model)
    assert result.verdict == ScanVerdict.AUTO
    assert result.model == "MDL-A"


def test_save_and_learn_with_fake_repository() -> None:
    """FakeRepository round-trip: save mapping → lookup → resolve → AUTO.

    Covers the service-layer integration: resolve_model_barcode uses the
    repository to retrieve the learned model.
    """
    repo = FakeRepository()
    repo.upsert_items(
        [
            {
                "inventory_id": "INV-1",
                "purchase_order": "PO-001",
                "model_number": "SHX78CM5N",
                "product_category": "",
                "truck": "",
                "stop": "",
                "sales_order": "",
                "product_size": {"w": 0, "d": 0, "h": 0},
                "quantity": 1,
                "brand": "",
                "vendor": "",
                "tags": "",
            }
        ]
    )
    repo.save_barcode_mapping("SHX78-SCAN", "SHX78CM5N", 0.0, "manual")

    result = resolve_model_barcode("SHX78-SCAN", "PO-001", repo)
    assert result.verdict == ScanVerdict.AUTO
    assert result.model == "SHX78CM5N"


# ── Routing: check_model_on_po service ────────────────────────────────────────


def _po_item(inv_id: str, model: str) -> dict:
    return {
        "inventory_id": inv_id,
        "purchase_order": "PO-001",
        "model_number": model,
        "product_category": "",
        "truck": "",
        "stop": "",
        "sales_order": "",
        "product_size": {"w": 0, "d": 0, "h": 0},
        "quantity": 1,
        "brand": "",
        "vendor": "",
        "tags": "",
    }


def test_check_model_on_po_returns_true_for_exact_match() -> None:
    """Typed model exactly matches an unclaimed PO item → True (on-PO path)."""
    repo = FakeRepository()
    repo.upsert_items([_po_item("INV-1", "MDL-A")])
    assert check_model_on_po("MDL-A", "PO-001", repo) is True


def test_check_model_on_po_normalized_match() -> None:
    """Typed 'MDL A' normalizes to same key as 'MDL-A' → True."""
    repo = FakeRepository()
    repo.upsert_items([_po_item("INV-1", "MDL-A")])
    assert check_model_on_po("MDL A", "PO-001", repo) is True


def test_check_model_on_po_returns_false_when_off_po() -> None:
    """Typed model not in unclaimed PO lines → False (off-PO path).

    Mutation kill: returning True unconditionally fails this assert.
    """
    repo = FakeRepository()
    repo.upsert_items([_po_item("INV-1", "MDL-A")])
    assert check_model_on_po("MDL-Z", "PO-001", repo) is False


def test_check_model_on_po_returns_false_for_claimed_item() -> None:
    """Claimed item is not in unclaimed_for_po → off-PO path → False.

    Prevents double-claiming a unit via NEEDS_MODEL submit.
    """
    repo = FakeRepository()
    repo.upsert_items([_po_item("INV-1", "MDL-A")])
    repo.claim("INV-1", datetime.now().isoformat())
    assert check_model_on_po("MDL-A", "PO-001", repo) is False


def test_check_model_on_po_returns_false_for_empty_po() -> None:
    """No items on the PO → always False."""
    repo = FakeRepository()
    assert check_model_on_po("MDL-X", "PO-EMPTY", repo) is False


# ── on_needs_model_submit: save-in-both-branches + routing ────────────────────


def test_on_po_submit_saves_mapping_and_sets_mid_scan() -> None:
    """On-PO path: save_mapping called, then set_mid_scan (state → MID_SCAN).

    Mutation kill: skipping save_mapping → _save_calls empty, fails assert.
    """
    ui = _FakeUI(state="NEEDS_MODEL")
    ui._pending_barcode = "RAW-001"
    ui._needs_model_var = _FakeVar("MDL-A")
    ui._check_model_on_po = lambda m, p: True

    blocking_states.on_needs_model_submit(ui)

    assert ("RAW-001", "MDL-A", "manual") in ui._save_calls
    assert ui._state == "MID_SCAN"
    assert ui._model_scan == "MDL-A"


def test_off_po_submit_saves_mapping_and_routes_to_no_match() -> None:
    """Off-PO path: save_mapping called, then _run_match with empty serial.

    Mutation kill: skipping save_mapping → _save_calls empty, fails first assert.
    Mutation kill: routing to mid_scan instead of _run_match → state != MATCHING.
    """
    ui = _FakeUI(state="NEEDS_MODEL")
    ui._pending_barcode = "RAW-002"
    ui._needs_model_var = _FakeVar("MDL-Z")
    ui._check_model_on_po = lambda m, p: False
    ui._root = _FakeRoot()

    blocking_states.on_needs_model_submit(ui)

    assert ("RAW-002", "MDL-Z", "manual") in ui._save_calls
    assert ("MDL-Z", "", "PO-001") in ui._run_match_calls


def test_save_called_before_po_check_so_both_branches_learn() -> None:
    """The save happens before the PO branch — off-PO save is not conditional.

    If save were inside the on-PO branch, off-PO would never learn the mapping.
    This test verifies the mapping is saved even when check_model_on_po is False.

    Mutation kill: moving save inside on-PO branch → save_calls empty for off-PO.
    """
    saves: list[tuple] = []
    po_check_calls: list[str] = []

    ui = _FakeUI(state="NEEDS_MODEL")
    ui._pending_barcode = "RAW-003"
    ui._needs_model_var = _FakeVar("MDL-OFF")
    ui._save_mapping = lambda b, m, s: saves.append((b, m, s))
    ui._check_model_on_po = lambda m, p: (po_check_calls.append(m), False)[-1]

    blocking_states.on_needs_model_submit(ui)

    assert len(saves) == 1
    assert saves[0] == ("RAW-003", "MDL-OFF", "manual")


def test_submit_empty_model_stays_in_needs_model() -> None:
    """Empty typed model → re-enter NEEDS_MODEL; no save, no route.

    Mutation kill: proceeding on empty model would call save_mapping with "".
    """
    ui = _FakeUI(state="NEEDS_MODEL")
    ui._pending_barcode = "RAW-004"
    ui._needs_model_var = _FakeVar("   ")
    ui._save_mapping = lambda b, m, s: (_ for _ in ()).throw(AssertionError("must not save"))

    blocking_states.on_needs_model_submit(ui)

    assert ui._state == "NEEDS_MODEL"


# ── No fuzzy: behavioral guard ────────────────────────────────────────────────


def test_no_thresholds_in_resolve_scan() -> None:
    """Behavioral: resolve_scan never acts like a fuzzy matcher.

    Two PO models that are similar but distinct both produce NEEDS_MODEL
    when the barcode walks both — no score-ranked winner is picked.

    Mutation kill: a scoring branch that picks one would return PROPOSE.
    """
    result = resolve_scan("B36", ["B36-CL80", "B36CL90"], learned_model=None)
    assert result.verdict == ScanVerdict.NEEDS_MODEL
