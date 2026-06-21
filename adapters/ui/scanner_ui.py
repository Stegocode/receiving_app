"""
Owns: Tkinter desktop UI for the barcode scanner receiving workflow.
Must not: import services, adapters.db, adapters.sink, adapters.source, sqlite3,
          playwright, or selenium. Services and printer come in via injection.
May import: tkinter, core.schema, core.errors, core.ports, adapters.scanner,
            adapters.ui.controller, adapters.ui.scan_states.

Scope assumptions: single-writer, single-machine, no concurrent users.
"""

from __future__ import annotations

import threading
import tkinter as tk
from collections.abc import Callable
from datetime import datetime
from tkinter import scrolledtext

from adapters.scanner import make_scanner
from adapters.ui import scan_states
from adapters.ui.controller import ScanOutcome, handle_scan
from adapters.ui.scan_states import (
    C_ACCENT,
    C_BAR,
    C_DIM,
    C_IDLE,
    C_INPUT_BG,
    C_LEFT,
    C_LOG_BG,
    C_WHITE,
    F_BOTTOM,
    F_LABEL,
    F_LOG,
    F_PO_ENTRY,
    F_PO_LIST,
    F_SECONDARY,
    F_SECTION,
    F_STATE,
    F_TITLE,
)
from core.ports import Printer
from core.schema import ReceivingRecord


class ReceivingUI:
    """Tkinter receiving UI — thin view driven by injected service callables.

    __init__ stores injected dependencies only; no Tk objects are created.
    Call run() to create the Tk root, build all widgets, and enter mainloop.
    """

    def __init__(
        self,
        process: Callable[[str, str], ReceivingRecord],
        printer: Printer,
        scanner_type: str,
        populate: Callable[[str], None] | None = None,
    ) -> None:
        self._process = process
        self._printer = printer
        self._scanner_type = scanner_type
        self._populate = populate

    def run(self) -> None:
        """Create Tk root, build widgets, enter mainloop."""
        root = tk.Tk()
        self._root = root
        self._state = "IDLE"
        self._current_po = ""
        self._active_pos: list[str] = []
        self._flash_after_id: str | None = None
        self._alarm_event = threading.Event()

        self._build_ui()

        scanner = make_scanner(self._scanner_type, parent=self._right)
        scanner.start(self._on_scan)

        if hasattr(scanner, "focus_entry"):
            scan_entry = scanner.focus_entry()

            def _poll_focus() -> None:
                try:
                    focused = root.focus_get()
                    if focused not in (self._po_input, scan_entry):
                        scan_entry.focus_force()
                except Exception:
                    pass
                root.after(50, _poll_focus)

            _poll_focus()

        root.bind("<Escape>", self._dismiss_no_match)
        root.bind("<End>", self._dismiss_no_match)
        root.mainloop()

    # ── Widget construction ────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self._root.configure(bg=C_BAR)
        self._root.title("Receiving Scanner")
        self._root.state("zoomed")
        top = tk.Frame(self._root, bg=C_BAR)
        top.pack(fill="both", expand=True)
        top.grid_columnconfigure(0, weight=3)
        top.grid_columnconfigure(1, weight=7)
        top.grid_rowconfigure(0, weight=1)
        self._left = tk.Frame(top, bg=C_LEFT)
        self._right = tk.Frame(top, bg=C_IDLE)
        self._left.grid(row=0, column=0, sticky="nsew")
        self._right.grid(row=0, column=1, sticky="nsew")
        bar = tk.Frame(self._root, bg=C_BAR, height=58)
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)
        self._count_lbl = tk.Label(
            bar, text="Received Today:  — / —", font=F_BOTTOM, bg=C_BAR, fg=C_WHITE
        )
        self._count_lbl.pack(expand=True)
        self._build_left()
        self._build_right()

    def _build_left(self) -> None:
        p = self._left
        tk.Label(p, text="RECEIVING SCANNER", bg=C_LEFT, fg=C_ACCENT, font=F_TITLE, pady=8).pack(
            fill="x", padx=12, pady=(10, 0)
        )
        tk.Frame(p, bg=C_ACCENT, height=2).pack(fill="x", padx=12)
        po_wrap = tk.Frame(p, bg=C_LEFT)
        po_wrap.pack(fill="x", padx=12, pady=(10, 0))
        tk.Label(po_wrap, text="Add PO #(s)", bg=C_LEFT, fg=C_WHITE, font=F_LABEL).pack(anchor="w")
        tk.Label(
            po_wrap,
            text="comma-separated  e.g. 11782, 11783",
            bg=C_LEFT,
            fg=C_DIM,
            font=("Arial", 10),
        ).pack(anchor="w")
        row = tk.Frame(po_wrap, bg=C_LEFT)
        row.pack(fill="x")
        self._po_var = tk.StringVar()
        self._po_input = tk.Entry(
            row,
            textvariable=self._po_var,
            bg=C_INPUT_BG,
            fg=C_WHITE,
            insertbackground=C_WHITE,
            font=F_PO_ENTRY,
            relief="flat",
            bd=4,
        )
        self._po_input.pack(side="left", fill="x", expand=True)
        self._po_input.bind("<Return>", self._on_po_submit)
        tk.Button(
            row,
            text="Go",
            command=self._on_po_submit,
            bg=C_ACCENT,
            fg=C_WHITE,
            font=F_LABEL,
            relief="flat",
            padx=10,
            cursor="hand2",
        ).pack(side="left", padx=(4, 0))
        tk.Frame(p, bg="#4A6278", height=1).pack(fill="x", padx=12, pady=8)
        tk.Label(p, text="STATUS LOG", bg=C_LEFT, fg=C_DIM, font=F_SECTION).pack(fill="x", padx=12)
        self._log_widget = scrolledtext.ScrolledText(
            p,
            state="disabled",
            wrap="word",
            bg=C_LOG_BG,
            fg=C_WHITE,
            font=F_LOG,
            relief="flat",
            bd=0,
        )
        self._log_widget.pack(fill="both", expand=True, padx=12, pady=(2, 4))
        tk.Frame(p, bg="#4A6278", height=1).pack(fill="x", padx=12, pady=(0, 4))
        tk.Label(p, text="TODAY'S POs", bg=C_LEFT, fg=C_DIM, font=F_SECTION).pack(fill="x", padx=12)
        self._po_list = tk.Text(
            p,
            state="disabled",
            wrap="none",
            bg=C_LOG_BG,
            fg=C_DIM,
            font=F_PO_LIST,
            relief="flat",
            bd=0,
            height=5,
        )
        self._po_list.pack(fill="x", padx=12, pady=(2, 10))

    def _build_right(self) -> None:
        p = self._right
        self._center = tk.Frame(p, bg=C_IDLE)
        self._center.place(relx=0.5, rely=0.40, anchor="center")
        self._state_lbl = tk.Label(
            self._center,
            text="ADD PO TO BEGIN",
            font=F_STATE,
            bg=C_IDLE,
            fg=C_WHITE,
            wraplength=700,
            justify="center",
        )
        self._state_lbl.pack()
        self._sec_lbl = tk.Label(
            self._center,
            text="Enter PO number(s) on the left",
            font=F_SECONDARY,
            bg=C_IDLE,
            fg=C_DIM,
            wraplength=700,
            justify="center",
        )
        self._sec_lbl.pack(pady=(14, 0))
        self._reset_btn = tk.Button(
            p,
            text="Reset",
            command=self._set_idle,
            bg="#922B21",
            fg=C_WHITE,
            font=("Arial", 14),
            relief="flat",
            padx=18,
            pady=10,
            cursor="hand2",
        )

    # ── Scan handling ──────────────────────────────────────────────────────────

    def _on_scan(self, barcode: str) -> None:
        if self._state == "MATCHING":
            return
        if not self._current_po:
            self._log("Add a PO number first")
            return
        self._state = "MATCHING"
        scan_states.set_right_bg(self, C_IDLE)
        self._state_lbl.configure(text="MATCHING…", fg=C_WHITE)
        self._sec_lbl.configure(text=f"Barcode: {barcode}", fg=C_DIM)
        threading.Thread(
            target=self._run_match, args=(barcode, self._current_po), daemon=True
        ).start()

    def _run_match(self, barcode: str, po: str) -> None:
        try:
            outcome = handle_scan(barcode, po, self._process, self._printer)
        except Exception as exc:
            self._log(f"ERROR during scan: {exc}")
            self._root.after(0, self._set_idle)
            return
        self._root.after(0, self._apply_outcome, outcome)

    def _apply_outcome(self, outcome: ScanOutcome) -> None:
        rec = outcome.record
        if outcome.status == "received":
            self._log(f"MATCHED  PO:{rec.purchase_order}  Model:{rec.model_number}")
            self._set_match_found(rec)
        elif outcome.status == "no_match":
            self._log(f"NO MATCH  PO:{rec.purchase_order}")
            self._set_no_match()
        else:
            self._log(f"PRINT FAILED  PO:{rec.purchase_order}  Model:{rec.model_number}")
            self._set_print_failed(rec)

    # ── State / flash / alarm — see adapters/ui/scan_states.py ───────────────

    def _set_right_bg(self, color: str) -> None:
        scan_states.set_right_bg(self, color)

    def _set_idle(self) -> None:
        scan_states.set_idle(self)

    def _set_match_found(self, record: ReceivingRecord) -> None:
        scan_states.set_match_found(self, record)

    def _set_no_match(self) -> None:
        scan_states.set_no_match(self)

    def _set_print_failed(self, record: ReceivingRecord) -> None:
        scan_states.set_print_failed(self, record)

    def _dismiss_no_match(self, _event: object = None) -> None:
        scan_states.dismiss_no_match(self)

    def _start_flash(self) -> None:
        scan_states.start_flash(self)

    def _do_flash(self, current: str) -> None:
        scan_states.do_flash(self, current)

    def _stop_flash(self) -> None:
        scan_states.stop_flash(self)

    def _start_alarm(self) -> None:
        scan_states.start_alarm(self._alarm_event, self._root.bell)

    def _stop_alarm(self) -> None:
        self._alarm_event.set()

    # ── Status log ────────────────────────────────────────────────────────────

    def _log(self, msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}\n"
        print(line.rstrip())

        def _append() -> None:
            self._log_widget.configure(state="normal")
            self._log_widget.insert("end", line)
            self._log_widget.see("end")
            self._log_widget.configure(state="disabled")

        self._root.after(0, _append)

    # ── PO list display ───────────────────────────────────────────────────────

    def _set_po_list(self, pos: list[str]) -> None:
        def _do() -> None:
            self._po_list.configure(state="normal")
            self._po_list.delete("1.0", "end")
            if pos:
                for po in sorted(set(pos)):
                    self._po_list.insert("end", po + "\n")
            else:
                self._po_list.insert("end", "(none)\n")
            self._po_list.configure(state="disabled")

        self._root.after(0, _do)

    # ── PO submission ─────────────────────────────────────────────────────────

    def _on_po_submit(self, _event: object = None) -> None:
        raw = self._po_var.get().strip()
        self._po_var.set("")
        if not raw:
            return
        po_list = [p.strip() for p in raw.split(",") if p.strip()]
        if not all(p.isdigit() for p in po_list):
            self._log(f"Invalid PO: {po_list!r} — must be numeric")
            return
        for po in po_list:
            self._log(f"Loading PO {po}…")
            if self._populate:
                threading.Thread(target=self._run_populate, args=(po,), daemon=True).start()
            else:
                self._add_po(po)

    def _run_populate(self, po: str) -> None:
        populate = self._populate
        if populate is None:
            return
        try:
            populate(po)
            self._log(f"PO {po} loaded")
        except Exception as exc:
            self._log(f"PO {po} error: {exc}")
        self._root.after(0, self._add_po, po)

    def _add_po(self, po: str) -> None:
        if po not in self._active_pos:
            self._active_pos.append(po)
        self._current_po = po
        self._set_po_list(self._active_pos)
        self._set_idle()
