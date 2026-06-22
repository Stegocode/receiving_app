"""
Owns: color/font constants and scan state machine logic for the receiving UI.
Must not: import services, adapters.db, adapters.sink, adapters.source, sqlite3.
May import: core.schema, sys, threading, time, tkinter (for type hints only).

State markers: IDLE, MID_SCAN, MATCHING, MATCH_FOUND, NO_MATCH, PRINT_FAILED.
"""

from __future__ import annotations

import sys
import threading
import time
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
    ui._stop_alarm()
    ui._stop_flash()
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
    ui._stop_alarm()
    ui._stop_flash()
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
    ui._root.after(2000, ui._set_idle)


def set_no_match(ui: Any) -> None:
    ui._state = "NO_MATCH"
    ui._reset_btn.place(relx=0.5, rely=0.82, anchor="center")
    set_right_bg(ui, C_NOMATCH)
    ui._state_lbl.configure(text="NOT ON PO", fg=C_WHITE)
    ui._sec_lbl.configure(text="SET ASIDE  ·  Esc to dismiss", fg=C_WHITE)
    ui._start_flash()
    ui._start_alarm()


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
    ui._flash_after_id = ui._root.after(400, ui._do_flash, nxt)


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
