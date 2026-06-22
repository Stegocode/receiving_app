"""
Owns: color/font constants, scan state machine logic, and manual-entry widgets for the
      receiving UI.
Must not: import services, adapters.db, adapters.sink, adapters.source, sqlite3.
May import: core.schema, sys, threading, time, tkinter.

State markers: IDLE, MID_SCAN, MATCHING, MATCH_FOUND, NO_MATCH, PRINT_FAILED.
"""

from __future__ import annotations

import sys
import threading
import time
import tkinter as tk
from typing import Any

from core.schema import ReceivingRecord

# ── Colors ────────────────────────────────────────────────────────────────────
C_LEFT = "#34495E"
C_IDLE = "#2C3E50"
C_MATCH = "#27AE60"
C_NOMATCH = "#E74C3C"
C_NOMATCH2 = "#C0392B"
C_FAILED = "#D35400"
C_BAR = "#1A252F"
C_LOG_BG = "#1E2D3A"
C_WHITE = "#ECF0F1"
C_DIM = "#BDC3C7"
C_ACCENT = "#3498DB"
C_INPUT_BG = "#243342"

# ── Fonts ─────────────────────────────────────────────────────────────────────
F_STATE = ("Arial", 72, "bold")
F_SECONDARY = ("Arial", 28)
F_BOTTOM = ("Arial", 22, "bold")
F_LABEL = ("Arial", 13)
F_LOG = ("Courier New", 11)
F_PO_ENTRY = ("Arial", 14)
F_PO_LIST = ("Arial", 13)
F_TITLE = ("Arial", 14, "bold")
F_SECTION = ("Arial", 11, "bold")


# ── State transitions ─────────────────────────────────────────────────────────
# ui: ReceivingUI instance (typed Any to avoid circular import).


def set_right_bg(ui: Any, color: str) -> None:
    ui._right.configure(bg=color)
    ui._center.configure(bg=color)
    ui._state_lbl.configure(bg=color)
    ui._sec_lbl.configure(bg=color)


def set_idle(ui: Any) -> None:
    ui._state = "IDLE"
    ui._model_scan = None
    ui._alarm_event.set()
    stop_flash(ui)
    hide_manual_entry(ui)
    ui._reset_btn.place_forget()
    set_right_bg(ui, C_IDLE)
    if ui._current_po:
        ui._state_lbl.configure(text="SCAN MODEL", fg=C_WHITE)
        ui._sec_lbl.configure(text=f"PO: {ui._current_po}", fg=C_ACCENT)
    else:
        ui._state_lbl.configure(text="ADD PO TO BEGIN", fg=C_WHITE)
        ui._sec_lbl.configure(text="Enter PO number(s) on the left", fg=C_DIM)


def set_mid_scan(ui: Any, model_text: str) -> None:
    """Enter MID_SCAN state: model barcode captured, waiting for serial barcode."""
    ui._state = "MID_SCAN"
    ui._reset_btn.place(relx=0.5, rely=0.82, anchor="center")
    set_right_bg(ui, C_IDLE)
    ui._state_lbl.configure(text=model_text, fg=C_WHITE)
    ui._sec_lbl.configure(text="SCAN SERIAL NUMBER", fg=C_DIM)


def set_match_found(ui: Any, record: ReceivingRecord) -> None:
    ui._state = "MATCH_FOUND"
    ui._model_scan = None
    ui._alarm_event.set()
    stop_flash(ui)
    set_right_bg(ui, C_MATCH)
    ui._state_lbl.configure(text="MATCHED", fg=C_WHITE)
    ui._sec_lbl.configure(
        text=(
            f"PO: {record.purchase_order}\n"
            f"Inventory ID: {record.inventory_id}\n"
            f"Model: {record.model_number}"
            + (f"\nSerial: {record.serial}" if record.serial else "")
        ),
        fg=C_WHITE,
    )
    ui._root.after(2000, set_idle, ui)


def set_no_match(ui: Any) -> None:
    ui._state = "NO_MATCH"
    ui._reset_btn.place(relx=0.5, rely=0.82, anchor="center")
    set_right_bg(ui, C_NOMATCH)
    ui._state_lbl.configure(text="NOT ON PO", fg=C_WHITE)
    ui._sec_lbl.configure(text="SET ASIDE  ·  Esc to dismiss", fg=C_WHITE)
    start_flash(ui)
    start_alarm(ui._alarm_event, ui._root.bell)


def set_print_failed(ui: Any, record: ReceivingRecord) -> None:
    ui._state = "PRINT_FAILED"
    ui._reset_btn.place(relx=0.5, rely=0.82, anchor="center")
    set_right_bg(ui, C_FAILED)
    ui._state_lbl.configure(text="LABEL FAILED — REPRINT", fg=C_WHITE)
    ui._sec_lbl.configure(
        text=(f"Record saved  ·  PO:{record.purchase_order}  Model:{record.model_number}"),
        fg=C_WHITE,
    )


def dismiss_no_match(ui: Any) -> None:
    if ui._state in ("NO_MATCH", "PRINT_FAILED"):
        ui._set_idle()


# ── Flash ─────────────────────────────────────────────────────────────────────


def start_flash(ui: Any) -> None:
    stop_flash(ui)
    do_flash(ui, C_NOMATCH)


def do_flash(ui: Any, current: str) -> None:
    if ui._state != "NO_MATCH":
        return
    nxt = C_NOMATCH2 if current == C_NOMATCH else C_NOMATCH
    set_right_bg(ui, nxt)
    ui._flash_after_id = ui._root.after(400, do_flash, ui, nxt)


def stop_flash(ui: Any) -> None:
    if ui._flash_after_id:
        ui._root.after_cancel(ui._flash_after_id)
        ui._flash_after_id = None


# ── Alarm ─────────────────────────────────────────────────────────────────────


def start_alarm(alarm_event: threading.Event, bell_fn: Any) -> None:
    """Start the no-match alarm. On Windows: looping winsound thread. Else: bell."""
    alarm_event.clear()
    if sys.platform == "win32":
        threading.Thread(target=_alarm_loop, args=(alarm_event,), daemon=True).start()
    else:
        bell_fn()


def _alarm_loop(alarm_event: threading.Event) -> None:
    import winsound  # lazy: only reachable on Windows (guarded by sys.platform)

    ws: Any = winsound  # typed Any so mypy skips platform-conditional attribute checks
    while not alarm_event.is_set():
        ws.Beep(880, 200)
        if alarm_event.is_set():
            break
        time.sleep(0.1)
        ws.Beep(440, 200)
        if alarm_event.is_set():
            break
        time.sleep(0.2)


# ── Manual entry ──────────────────────────────────────────────────────────────


def _entry(parent: Any, var: Any) -> Any:
    """Return a styled tk.Entry bound to var."""
    return tk.Entry(
        parent,
        textvariable=var,
        bg=C_INPUT_BG,
        fg=C_WHITE,
        insertbackground=C_WHITE,
        font=("Arial", 20),
        relief="flat",
        bd=4,
        width=22,
    )


def build_manual_frame(ui: Any, parent: Any) -> None:
    """Build the hidden manual-entry overlay and the 'Type Model' button."""
    f = tk.Frame(parent, bg=C_IDLE)
    ui._manual_frame = f
    tk.Label(f, text="Model number:", bg=C_IDLE, fg=C_DIM, font=F_LABEL).pack(pady=(0, 2))
    ui._manual_model_var = tk.StringVar()
    ui._manual_model_entry = _entry(f, ui._manual_model_var)
    ui._manual_model_entry.pack(pady=(0, 8))
    ui._manual_model_entry.bind("<Return>", lambda _e: ui._manual_serial_entry.focus_set())
    tk.Label(f, text="Serial number:", bg=C_IDLE, fg=C_DIM, font=F_LABEL).pack(pady=(0, 2))
    ui._manual_serial_var = tk.StringVar()
    ui._manual_serial_entry = _entry(f, ui._manual_serial_var)
    ui._manual_serial_entry.pack(pady=(0, 8))
    ui._manual_serial_entry.bind("<Return>", lambda _e: on_manual_submit(ui))
    tk.Button(
        f,
        text="Submit",
        command=lambda: on_manual_submit(ui),
        bg=C_ACCENT,
        fg=C_WHITE,
        font=F_LABEL,
        relief="flat",
        padx=12,
        cursor="hand2",
    ).pack(pady=(4, 0))
    ui._type_btn = tk.Button(
        parent,
        text="Type Model",
        command=lambda: show_manual_entry(ui),
        bg="#4A6278",
        fg=C_WHITE,
        font=("Arial", 14),
        relief="flat",
        padx=18,
        pady=10,
        cursor="hand2",
    )
    ui._type_btn.place(relx=0.5, rely=0.82, anchor="center")


def show_manual_entry(ui: Any) -> None:
    """Show the manual model+serial form; only valid from IDLE or MATCH_FOUND."""
    if ui._state not in ("IDLE", "MATCH_FOUND"):
        return
    if not ui._current_po:
        ui._log("Set a PO first before using manual entry")
        return
    ui._manual_model_var.set("")
    ui._manual_serial_var.set("")
    ui._manual_frame.place(relx=0.5, rely=0.68, anchor="center")
    ui._type_btn.configure(text="Cancel", command=lambda: hide_manual_entry(ui))
    ui._manual_model_entry.focus_force()


def hide_manual_entry(ui: Any) -> None:
    """Hide the manual entry form and restore the 'Type Model' button."""
    ui._manual_frame.place_forget()
    ui._type_btn.configure(text="Type Model", command=lambda: show_manual_entry(ui))


def on_manual_submit(ui: Any) -> None:
    """Submit typed model+serial; route through the same path as a barcode scan."""
    model = ui._manual_model_var.get().strip()
    serial = ui._manual_serial_var.get().strip()
    hide_manual_entry(ui)
    if not model:
        ui._log("Model number is required for manual entry")
        return
    if not ui._current_po:
        ui._log("Set a PO first before using manual entry")
        return
    po = ui._current_po
    ui._model_scan = model
    ui._state = "MATCHING"
    ui._root.after(0, ui._state_lbl.configure, {"text": "MATCHING…", "fg": C_WHITE})
    ui._root.after(0, ui._sec_lbl.configure, {"text": f"Model: {model}", "fg": C_DIM})
    threading.Thread(target=ui._run_match, args=(model, serial, po), daemon=True).start()
