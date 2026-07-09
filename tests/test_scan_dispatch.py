"""
Owns: tests for core.scan_dispatch.decide_scan_action — the pure decision function
      that maps (state, barcode, context) → ScanAction.
Must not: import adapters, services, tkinter, or perform any I/O.
May import: core.scan_dispatch, pytest.

Safety invariant under test: SERIAL_MATCH is reachable ONLY from MID_SCAN.
Precedence invariant under test: block (PROPOSE/NEEDS_MODEL) wins over PO: intercept.

not_measured: actual Tk dispatch, thread behaviour, alarm timing — those are
              exercised by test_scan_flow.py at the adapter level.

PASS thresholds (pre-declared):
  PASS:    all assertions green.
  PARTIAL: none — every dispatch branch must be covered.
  KILL:    any assertion failure.
"""

from __future__ import annotations

from core.scan_dispatch import ScanAction, ScanActionKind, decide_scan_action

# ── Canonical test context ─────────────────────────────────────────────────────

_ACTIVE_POS = ["12345", "99999"]
_KNOWN_PO_BARCODE = "PO:12345"
_UNKNOWN_PO_BARCODE = "PO:00000"
_SERIAL = "SN-ABCDEF"
_MODEL_BARCODE = "MDL-XYZ"


def _decide(
    state: str,
    barcode: str = _SERIAL,
    *,
    has_po: bool = True,
    has_resolver: bool = True,
    active_pos: list[str] | None = None,
) -> ScanAction:
    return decide_scan_action(
        state,
        barcode,
        has_po,
        has_resolver,
        active_pos if active_pos is not None else _ACTIVE_POS,
    )


# ── Safety invariant: SERIAL_MATCH is reachable ONLY from MID_SCAN ────────────

_ALL_KNOWN_STATES = [
    "IDLE",
    "MATCH_FOUND",
    "MID_SCAN",
    "MATCHING",
    "RESOLVING",
    "PROPOSE",
    "NEEDS_MODEL",
    "SYNC_STOPPED",
    "NO_MATCH",
    "PRINT_FAILED",
    "ALREADY_SCANNED",
]


def test_serial_match_reachable_only_from_mid_scan() -> None:
    """Exhaustive: across every known state, SERIAL_MATCH is returned for MID_SCAN only.

    This is the load-bearing safety proof. A mutant that mis-routes PROPOSE,
    NEEDS_MODEL, or any other state to SERIAL_MATCH MUST fail here.

    Mutation kill: any change that widens the SERIAL_MATCH condition beyond MID_SCAN.
    """
    serial_match_states = [
        s
        for s in _ALL_KNOWN_STATES
        if _decide(s, _SERIAL, has_po=True, has_resolver=True).kind == ScanActionKind.SERIAL_MATCH
    ]
    assert serial_match_states == ["MID_SCAN"], (
        f"SERIAL_MATCH reachable from unexpected states: {serial_match_states}"
    )


def test_serial_match_not_returned_for_propose() -> None:
    """PROPOSE + serial-looking barcode → TURNSTILE, never SERIAL_MATCH.

    Mutation kill: swapping PROPOSE check to SERIAL_MATCH would allow a serial
    scan to proceed while the system is waiting for turnstile confirmation.
    """
    action = _decide("PROPOSE", _SERIAL)
    assert action.kind == ScanActionKind.TURNSTILE
    assert action.kind != ScanActionKind.SERIAL_MATCH


def test_serial_match_not_returned_for_needs_model() -> None:
    """NEEDS_MODEL + any barcode → BLOCKED_REALERT, never SERIAL_MATCH.

    Mutation kill: removing the NEEDS_MODEL guard would fall through to MID_SCAN
    (if state somehow ended up there) or produce wrong routing.
    """
    action = _decide("NEEDS_MODEL", _SERIAL)
    assert action.kind == ScanActionKind.BLOCKED_REALERT
    assert action.kind != ScanActionKind.SERIAL_MATCH


# ── DROP_BUSY ─────────────────────────────────────────────────────────────────


def test_matching_drops_any_barcode() -> None:
    """State MATCHING → DROP_BUSY regardless of barcode content.

    Mutation kill: removing MATCHING from the busy guard lets a second scan through.
    """
    action = _decide("MATCHING", _SERIAL)
    assert action.kind == ScanActionKind.DROP_BUSY


def test_resolving_drops_any_barcode() -> None:
    """State RESOLVING → DROP_BUSY — in-flight resolution blocks new scans.

    Mutation kill: removing RESOLVING from the busy guard allows re-entry.
    """
    action = _decide("RESOLVING", _SERIAL)
    assert action.kind == ScanActionKind.DROP_BUSY


def test_matching_drops_po_barcode_too() -> None:
    """MATCHING + PO: barcode → DROP_BUSY (busy always wins, even over PO switch)."""
    action = _decide("MATCHING", _KNOWN_PO_BARCODE)
    assert action.kind == ScanActionKind.DROP_BUSY


# ── Precedence: block wins over PO: intercept ────────────────────────────────


def test_propose_blocks_known_po_barcode() -> None:
    """PROPOSE + PO: barcode for a loaded PO → TURNSTILE, not PO_SWITCH.

    Encodes the chosen precedence: the blocked state wins.
    A PO scan cannot change context while the system awaits turnstile confirmation.

    Mutation kill: swapping the guard order → PO_SWITCH returned, block bypassed.
    """
    action = _decide("PROPOSE", _KNOWN_PO_BARCODE)
    assert action.kind == ScanActionKind.TURNSTILE
    assert action.kind != ScanActionKind.PO_SWITCH


def test_needs_model_blocks_known_po_barcode() -> None:
    """NEEDS_MODEL + PO: barcode for a loaded PO → BLOCKED_REALERT, not PO_SWITCH.

    Mutation kill: swapping guard order → PO_SWITCH while operator must type model.
    """
    action = _decide("NEEDS_MODEL", _KNOWN_PO_BARCODE)
    assert action.kind == ScanActionKind.BLOCKED_REALERT
    assert action.kind != ScanActionKind.PO_SWITCH


def test_propose_payload_is_incoming_barcode() -> None:
    """TURNSTILE payload is the incoming barcode (forwarded to handle_propose_scan)."""
    action = _decide("PROPOSE", "SOME-BARCODE")
    assert action.kind == ScanActionKind.TURNSTILE
    assert action.payload == "SOME-BARCODE"


# ── TURNSTILE ─────────────────────────────────────────────────────────────────


def test_propose_any_non_po_barcode_is_turnstile() -> None:
    """Any non-PO barcode while PROPOSE → TURNSTILE; payload is the barcode."""
    action = _decide("PROPOSE", "ANYTHING")
    assert action.kind == ScanActionKind.TURNSTILE
    assert action.payload == "ANYTHING"


# ── BLOCKED_REALERT ───────────────────────────────────────────────────────────


def test_needs_model_any_barcode_is_blocked_realert() -> None:
    """Any barcode while NEEDS_MODEL → BLOCKED_REALERT."""
    action = _decide("NEEDS_MODEL", "ANYTHING")
    assert action.kind == ScanActionKind.BLOCKED_REALERT


# ── PO: intercept (non-blocked, non-busy states) ─────────────────────────────


def test_po_switch_when_po_in_active_list() -> None:
    """PO: barcode for a loaded PO while IDLE → PO_SWITCH with the PO number."""
    action = _decide("IDLE", _KNOWN_PO_BARCODE)
    assert action.kind == ScanActionKind.PO_SWITCH
    assert action.payload == "12345"


def test_po_not_loaded_when_po_unknown() -> None:
    """PO: barcode for an unloaded PO while IDLE → PO_NOT_LOADED."""
    action = _decide("IDLE", _UNKNOWN_PO_BARCODE)
    assert action.kind == ScanActionKind.PO_NOT_LOADED
    assert action.payload == "00000"


def test_po_intercept_case_insensitive() -> None:
    """'po:12345' (lowercase) is recognized the same as 'PO:12345'."""
    action = _decide("IDLE", "po:12345")
    assert action.kind == ScanActionKind.PO_SWITCH
    assert action.payload == "12345"


def test_po_switch_from_match_found_state() -> None:
    """PO: intercept works from MATCH_FOUND state too."""
    action = _decide("MATCH_FOUND", _KNOWN_PO_BARCODE)
    assert action.kind == ScanActionKind.PO_SWITCH


# ── IDLE / MATCH_FOUND routing ────────────────────────────────────────────────


def test_idle_with_resolver_returns_resolve() -> None:
    """IDLE + PO set + resolver wired → RESOLVE with the barcode as payload.

    Mutation kill: returning MID_SCAN_DIRECT instead skips the model-resolution step.
    """
    action = _decide("IDLE", _MODEL_BARCODE, has_po=True, has_resolver=True)
    assert action.kind == ScanActionKind.RESOLVE
    assert action.payload == _MODEL_BARCODE


def test_match_found_with_resolver_returns_resolve() -> None:
    """MATCH_FOUND behaves identically to IDLE for model scans."""
    action = _decide("MATCH_FOUND", _MODEL_BARCODE, has_po=True, has_resolver=True)
    assert action.kind == ScanActionKind.RESOLVE
    assert action.payload == _MODEL_BARCODE


def test_idle_without_resolver_returns_mid_scan_direct() -> None:
    """IDLE + no resolver → MID_SCAN_DIRECT (legacy path, no model resolution)."""
    action = _decide("IDLE", _MODEL_BARCODE, has_po=True, has_resolver=False)
    assert action.kind == ScanActionKind.MID_SCAN_DIRECT
    assert action.payload == _MODEL_BARCODE


def test_idle_no_po_returns_need_po() -> None:
    """IDLE + no current PO → NEED_PO regardless of resolver.

    Mutation kill: skipping the has_current_po check → RESOLVE/MID_SCAN_DIRECT returned.
    """
    action = _decide("IDLE", _MODEL_BARCODE, has_po=False, has_resolver=True)
    assert action.kind == ScanActionKind.NEED_PO


def test_match_found_no_po_returns_need_po() -> None:
    """MATCH_FOUND + no current PO → NEED_PO."""
    action = _decide("MATCH_FOUND", _MODEL_BARCODE, has_po=False, has_resolver=False)
    assert action.kind == ScanActionKind.NEED_PO


# ── MID_SCAN → SERIAL_MATCH (positive control) ────────────────────────────────


def test_mid_scan_returns_serial_match() -> None:
    """MID_SCAN + any barcode → SERIAL_MATCH with the serial as payload.

    Positive control: confirms the accepted path is working.
    Mutation kill: changing SERIAL_MATCH to DROP_BUSY would prevent all receiving.
    """
    action = _decide("MID_SCAN", _SERIAL)
    assert action.kind == ScanActionKind.SERIAL_MATCH
    assert action.payload == _SERIAL


def test_mid_scan_serial_match_payload_is_the_barcode() -> None:
    """SERIAL_MATCH payload is the exact cleaned barcode — no mutation."""
    action = _decide("MID_SCAN", "SERIAL-XYZ-001")
    assert action.payload == "SERIAL-XYZ-001"


# ── Defensive: unknown states ─────────────────────────────────────────────────


def test_unknown_state_drops() -> None:
    """An unknown state string (e.g. a future state) → DROP_BUSY (fail closed)."""
    action = _decide("SOME_FUTURE_STATE", _SERIAL)
    assert action.kind == ScanActionKind.DROP_BUSY


def test_no_match_state_drops() -> None:
    """NO_MATCH state → DROP_BUSY (operator must dismiss before scanning)."""
    action = _decide("NO_MATCH", _SERIAL)
    assert action.kind == ScanActionKind.DROP_BUSY


# ── ScanAction structural ─────────────────────────────────────────────────────


def test_scan_action_is_frozen() -> None:
    """ScanAction is immutable — callers cannot mutate a returned result."""
    action = decide_scan_action("MID_SCAN", "SCAN", True, True, [])
    try:
        action.kind = ScanActionKind.DROP_BUSY  # type: ignore[misc]
        raise AssertionError("should have raised FrozenInstanceError")
    except AssertionError:
        raise
    except Exception:
        pass


def test_decide_scan_action_returns_scan_action_instance() -> None:
    """Return type is always ScanAction — never None."""
    result = decide_scan_action("IDLE", "BARCODE", True, True, [])
    assert isinstance(result, ScanAction)
