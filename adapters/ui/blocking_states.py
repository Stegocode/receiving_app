"""
Owns: PROPOSE and NEEDS_MODEL blocking-state logic — UI transitions, scan-dispatch
      handlers, model entry overlay, and NEEDS_MODEL submit routing.
Must not: import services, adapters.db, adapters.sink, adapters.source, sqlite3.
May import: core.schema, adapters.ui.scan_states, collections.abc, threading, tkinter.

State markers: PROPOSE, NEEDS_MODEL.
PROPOSE:     one walk candidate; operator re-scans same barcode to confirm (turnstile).
NEEDS_MODEL: no confident match; operator types the model; scanner blocked.

Both states fire start_alarm (same as not-on-PO/set-aside path) and block the
scanner so the operator cannot barrel forward to a serial scan.
"""

from __future__ import annotations

import threading
import tkinter as tk
from typing import Any

from adapters.ui.scan_states import (
    C_ACCENT,
    C_DIM,
    C_WHITE,
    F_LABEL,
    set_mid_scan,
    start_alarm,
    stop_flash,
)

# Steel blue — distinct from IDLE (#2C3E50), NO_MATCH (#E74C3C), SYNC_STOPPED (#E67E22).
C_WAITING = "#1F618D"


# ── State entry ───────────────────────────────────────────────────────────────


def set_propose(ui: Any, raw_barcode: str, proposed_model: str) -> None:
    """Enter PROPOSE: one walk candidate found; block until operator confirms."""
    ui._state = "PROPOSE"
    ui._pending_barcode = raw_barcode
    ui._proposed_model = proposed_model
    stop_flash(ui)
    ui._reset_btn.place(relx=0.5, rely=0.82, anchor="center")
    _set_right_bg(ui, C_WAITING)
    ui._state_lbl.configure(text="CONFIRM MODEL?", fg=C_WHITE)
    ui._sec_lbl.configure(
        text=f"Proposed: {proposed_model}\nRe-scan barcode to confirm  ·  Esc to reset",
        fg=C_WHITE,
    )
    start_alarm(ui._alarm_event, ui._root.bell)


def set_needs_model(ui: Any, raw_barcode: str) -> None:
    """Enter NEEDS_MODEL: no match; block scanner until operator types model."""
    ui._state = "NEEDS_MODEL"
    ui._pending_barcode = raw_barcode
    stop_flash(ui)
    ui._reset_btn.place_forget()
    _set_right_bg(ui, C_WAITING)
    ui._state_lbl.configure(text="TYPE MODEL", fg=C_WHITE)
    ui._sec_lbl.configure(
        text="Scanner BLOCKED  ·  Enter model below  ·  Esc to reset",
        fg=C_WHITE,
    )
    start_alarm(ui._alarm_event, ui._root.bell)
    show_needs_model_entry(ui)


# ── Scan-dispatch handlers ────────────────────────────────────────────────────


def handle_propose_scan(ui: Any, incoming_barcode: str) -> None:
    """Turnstile handler: same barcode → confirmed; anything else → re-alert + stay.

    Called by _on_scan when state is PROPOSE.
    """
    if incoming_barcode == ui._pending_barcode:
        model = ui._proposed_model or ""
        ui._model_scan = model
        set_mid_scan(ui, model)
    else:
        start_alarm(ui._alarm_event, ui._root.bell)


def handle_needs_model_scan(ui: Any) -> None:
    """Block handler: re-alert to remind the operator the scanner is blocked.

    Called by _on_scan when state is NEEDS_MODEL.
    """
    start_alarm(ui._alarm_event, ui._root.bell)


# ── NEEDS_MODEL entry overlay ─────────────────────────────────────────────────


def build_needs_model_frame(ui: Any, parent: Any) -> None:
    """Build the NEEDS_MODEL input overlay. Called once during _build_right()."""
    f = tk.Frame(parent, bg=C_WAITING)
    ui._needs_model_frame = f
    ui._needs_model_lbl = tk.Label(f, text="Model number:", bg=C_WAITING, fg=C_DIM, font=F_LABEL)
    ui._needs_model_lbl.pack(pady=(0, 2))
    ui._needs_model_var = tk.StringVar()
    entry = tk.Entry(
        f,
        textvariable=ui._needs_model_var,
        bg="#243342",
        fg=C_WHITE,
        insertbackground=C_WHITE,
        font=("Arial", 20),
        relief="flat",
        bd=4,
        width=22,
    )
    entry.pack(pady=(0, 8))
    entry.bind("<Return>", lambda _e: on_needs_model_submit(ui))
    ui._needs_model_entry = entry
    tk.Button(
        f,
        text="Submit",
        command=lambda: on_needs_model_submit(ui),
        bg=C_ACCENT,
        fg=C_WHITE,
        font=F_LABEL,
        relief="flat",
        padx=12,
        cursor="hand2",
    ).pack(pady=(4, 0))


def show_needs_model_entry(ui: Any) -> None:
    """Show the NEEDS_MODEL input overlay and focus it."""
    ui._needs_model_var.set("")
    ui._needs_model_frame.configure(bg=C_WAITING)
    ui._needs_model_lbl.configure(bg=C_WAITING)
    ui._needs_model_frame.place(relx=0.5, rely=0.68, anchor="center")
    ui._needs_model_entry.focus_force()


def hide_needs_model_entry(ui: Any) -> None:
    """Hide the NEEDS_MODEL input overlay (idempotent)."""
    ui._needs_model_frame.place_forget()


# ── NEEDS_MODEL submit ────────────────────────────────────────────────────────


def on_needs_model_submit(ui: Any) -> None:
    """Handle typed model submission from NEEDS_MODEL state.

    1. Save mapping (raw_barcode → typed_model) regardless of PO outcome so the
       next identical scan resolves at step 1 (LEARNED).
    2. Check if typed model is on the locked PO's unclaimed lines.
    3. on-PO → set_mid_scan (operator scans serial; existing claim path → received).
    4. off-PO → route to existing no_match outcome via _run_match.
    """
    model = (ui._needs_model_var.get() or "").strip()
    hide_needs_model_entry(ui)
    if not model:
        ui._log("Model number is required")
        set_needs_model(ui, ui._pending_barcode or "")
        return
    po = ui._current_po
    if not po:
        ui._log("No active PO — reset and add a PO first")
        ui._set_idle()
        return
    raw = ui._pending_barcode or ""

    # Save mapping — BOTH on-PO and off-PO branches (dispatch invariant)
    if ui._save_mapping is not None:
        try:
            ui._save_mapping(raw, model, "manual")
        except Exception as exc:
            ui._log(f"WARNING: barcode mapping save failed: {exc}")

    # PO check — route to the existing claim or no_match path
    on_po = bool(ui._check_model_on_po and ui._check_model_on_po(model, po))
    if on_po:
        ui._model_scan = model
        set_mid_scan(ui, model)
    else:
        ui._state = "MATCHING"
        ui._root.after(0, ui._state_lbl.configure, {"text": "MATCHING…", "fg": C_WHITE})
        threading.Thread(target=ui._run_match, args=(model, "", po), daemon=True).start()


# ── Internal helpers ──────────────────────────────────────────────────────────


def _set_right_bg(ui: Any, color: str) -> None:
    ui._right.configure(bg=color)
    ui._center.configure(bg=color)
    ui._state_lbl.configure(bg=color)
    ui._sec_lbl.configure(bg=color)
