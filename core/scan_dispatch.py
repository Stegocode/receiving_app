"""
Owns: pure dispatch decision for the barcode scanner — maps (state, barcode, context)
      to a typed ScanAction. No I/O, no Tk, no threading.
Must not: import adapters, services, or perform any side effects.
May import: stdlib (dataclasses, enum).

Precedence (hard-coded invariant):
  1. Busy states (MATCHING, RESOLVING) → DROP_BUSY.
  2. Blocked states (PROPOSE, NEEDS_MODEL) → TURNSTILE / BLOCKED_REALERT.
     A PO: barcode while blocked is REFUSED — the block wins.
  3. PO: intercept — only reached in non-busy, non-blocked states.
  4. IDLE / MATCH_FOUND → RESOLVE / MID_SCAN_DIRECT / NEED_PO.
  5. MID_SCAN → SERIAL_MATCH.
  6. Any other state (defensive) → DROP_BUSY.

Safety invariant: SERIAL_MATCH is reachable ONLY from MID_SCAN.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ScanActionKind(Enum):
    DROP_BUSY = "drop_busy"
    PO_SWITCH = "po_switch"
    PO_NOT_LOADED = "po_not_loaded"
    TURNSTILE = "turnstile"
    BLOCKED_REALERT = "blocked_realert"
    NEED_PO = "need_po"
    RESOLVE = "resolve"
    MID_SCAN_DIRECT = "mid_scan_direct"
    SERIAL_MATCH = "serial_match"


@dataclass(frozen=True)
class ScanAction:
    """Typed result of decide_scan_action. Payload semantics per kind:

    DROP_BUSY        — None.
    PO_SWITCH        — the PO number string.
    PO_NOT_LOADED    — the PO number string (not in active_pos).
    TURNSTILE        — the incoming cleaned barcode (forwarded to handle_propose_scan).
    BLOCKED_REALERT  — None.
    NEED_PO          — None.
    RESOLVE          — the cleaned barcode (forwarded to the model resolver).
    MID_SCAN_DIRECT  — the cleaned barcode (legacy: no resolver wired).
    SERIAL_MATCH     — the cleaned barcode (the serial to match).
    """

    kind: ScanActionKind
    payload: str | None = None


def decide_scan_action(
    state: str,
    cleaned_barcode: str,
    has_current_po: bool,
    has_resolver: bool,
    active_pos: list[str],
) -> ScanAction:
    """Return the action the scanner UI should execute for this (state, barcode) pair.

    Pure — takes no locks, does no I/O, has no side effects.
    The caller (ReceivingUI._on_scan) does all Tk work after receiving the action.

    Args:
        state:           current UI state string (e.g. "IDLE", "MID_SCAN").
        cleaned_barcode: barcode.strip() — whitespace already removed by the caller.
        has_current_po:  bool(self._current_po).
        has_resolver:    self._resolve_model is not None.
        active_pos:      self._active_pos list.
    """
    # 1. Busy — drop everything; in-flight operation is authoritative.
    if state in ("MATCHING", "RESOLVING"):
        return ScanAction(ScanActionKind.DROP_BUSY)

    # 2. Blocked — block wins; PO: scans are refused while the interlock is active.
    if state == "PROPOSE":
        return ScanAction(ScanActionKind.TURNSTILE, payload=cleaned_barcode)
    if state == "NEEDS_MODEL":
        return ScanAction(ScanActionKind.BLOCKED_REALERT)

    # 3. PO: intercept — only reached in non-busy, non-blocked states.
    if cleaned_barcode.upper().startswith("PO:"):
        po_num = cleaned_barcode[3:].strip()
        if po_num in active_pos:
            return ScanAction(ScanActionKind.PO_SWITCH, payload=po_num)
        return ScanAction(ScanActionKind.PO_NOT_LOADED, payload=po_num)

    # 4. Accept a model scan in IDLE / MATCH_FOUND.
    if state in ("IDLE", "MATCH_FOUND"):
        if not has_current_po:
            return ScanAction(ScanActionKind.NEED_PO)
        if has_resolver:
            return ScanAction(ScanActionKind.RESOLVE, payload=cleaned_barcode)
        return ScanAction(ScanActionKind.MID_SCAN_DIRECT, payload=cleaned_barcode)

    # 5. Serial scan — ONLY from MID_SCAN.
    if state == "MID_SCAN":
        return ScanAction(ScanActionKind.SERIAL_MATCH, payload=cleaned_barcode)

    # 6. Defensive: any unknown/unhandled state (NO_MATCH, PRINT_FAILED, etc.) → drop.
    return ScanAction(ScanActionKind.DROP_BUSY)
