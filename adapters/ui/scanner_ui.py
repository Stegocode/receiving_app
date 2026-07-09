"""
Owns: Tkinter desktop UI for the barcode scanner receiving workflow.
Must not: import services, adapters.db, adapters.sink, adapters.source, sqlite3,
          playwright, or selenium. Services and printer come in via injection.
May import: tkinter, core.schema, core.errors, core.model_resolution, core.ports,
            adapters.scanner, adapters.ui.controller, adapters.ui.scan_states,
            adapters.ui.blocking_states.

Scope: single-writer, single-machine.
Scan flow: IDLE→RESOLVING→(MID_SCAN|PROPOSE|NEEDS_MODEL)→MATCHING→SYNC_STOPPED.
PO labels ("PO:{n}") switch the locked PO without triggering a model match.

not_measured: live Tk rendering, real cross-process timing, 1500 ms poll accuracy.
"""

from __future__ import annotations

import threading
import tkinter as tk
from collections.abc import Callable
from datetime import datetime
from tkinter import scrolledtext

from adapters.scanner import make_scanner
from adapters.ui import blocking_states, scan_states
from adapters.ui import scanner_ui_builder as _builder
from adapters.ui.controller import ScanOutcome, handle_scan
from adapters.ui.scan_states import (
    C_BAR,
    C_DIM,
    C_IDLE,
    C_LEFT,
    C_WHITE,
    F_BOTTOM,
    _note_poll_error,
    _populate_and_queue,
)
from core.model_resolution import ModelScanResult, ScanVerdict
from core.ports import Printer, SyncStatusStore
from core.scan_dispatch import ScanActionKind, decide_scan_action
from core.schema import ReceivingRecord


class ReceivingUI:
    # Declared here because they are assigned by scanner_ui_builder, not __init__.
    _po_var: tk.StringVar
    _po_input: tk.Entry
    _log_widget: scrolledtext.ScrolledText
    _po_list: tk.Text
    _center: tk.Frame
    _state_lbl: tk.Label
    _sec_lbl: tk.Label
    _reset_btn: tk.Button
    _manual_model_entry: tk.Entry
    _manual_serial_entry: tk.Entry
    _needs_model_entry: tk.Entry

    def __init__(
        self,
        process: Callable[[str, str, str], ReceivingRecord],
        printer: Printer,
        scanner_type: str,
        populate: Callable[[str], None] | None = None,
        sync_status_store: SyncStatusStore | None = None,
        resolve_model: Callable[[str, str], ModelScanResult] | None = None,
        check_model_on_po: Callable[[str, str], bool] | None = None,
        save_mapping: Callable[[str, str, str], None] | None = None,
    ) -> None:
        self._process = process
        self._printer = printer
        self._scanner_type = scanner_type
        self._populate = populate
        self._sync_status_store = sync_status_store
        self._resolve_model = resolve_model
        self._check_model_on_po = check_model_on_po
        self._save_mapping = save_mapping

    def run(self) -> None:
        root = tk.Tk()
        self._root = root
        self._state = "IDLE"
        self._current_po = ""
        self._active_pos: list[str] = []
        self._model_scan: str | None = None
        self._pending_barcode: str | None = None
        self._proposed_model: str | None = None
        self._flash_after_id: str | None = None
        self._alarm_event = threading.Event()
        self._dismissed_sync_stop_at: str | None = None
        self._last_sync_stop_at: str | None = None
        self._sync_poll_error_logged: list[bool] = [False]

        self._build_ui()
        if self._sync_status_store is not None:
            self._root.after(1500, self._poll_sync_status)

        scanner = make_scanner(self._scanner_type, parent=self._right)
        scanner.start(self._on_scan)

        if hasattr(scanner, "focus_entry"):
            scan_entry = scanner.focus_entry()
            _allow = (
                self._po_input,
                scan_entry,
                self._manual_model_entry,
                self._manual_serial_entry,
                self._needs_model_entry,
            )

            _fault_logged: list[bool] = [False]

            def _poll_focus() -> None:
                try:
                    focused = root.focus_get()
                    if focused not in _allow:
                        scan_entry.focus_force()
                except Exception as exc:
                    _note_poll_error(exc, _fault_logged, self._log)
                root.after(50, _poll_focus)

            _poll_focus()

        root.bind("<Escape>", self._dismiss_no_match)
        root.bind("<End>", self._dismiss_no_match)
        root.mainloop()

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
        _builder.build_left(self, self._left)

    def _build_right(self) -> None:
        _builder.build_right(self, self._right)

    def _on_scan(self, barcode: str) -> None:
        action = decide_scan_action(
            self._state,
            barcode.strip(),
            bool(self._current_po),
            self._resolve_model is not None,
            self._active_pos,
        )
        if action.kind == ScanActionKind.DROP_BUSY:
            return
        if action.kind == ScanActionKind.TURNSTILE:
            self._root.after(0, blocking_states.handle_propose_scan, self, action.payload or "")
        elif action.kind == ScanActionKind.BLOCKED_REALERT:
            self._root.after(0, blocking_states.handle_needs_model_scan, self)
        elif action.kind == ScanActionKind.PO_SWITCH:
            self._root.after(0, self._lock_po, action.payload or "")
        elif action.kind == ScanActionKind.PO_NOT_LOADED:
            self._log(f"PO {action.payload} not loaded — enter it in the PO field first")
        elif action.kind == ScanActionKind.NEED_PO:
            self._log("Add a PO number first")
        elif action.kind == ScanActionKind.RESOLVE:
            cleaned = action.payload or ""
            self._pending_barcode = cleaned
            self._state = "RESOLVING"
            threading.Thread(
                target=self._run_resolution, args=(cleaned, self._current_po), daemon=True
            ).start()
        elif action.kind == ScanActionKind.MID_SCAN_DIRECT:
            self._model_scan = action.payload
            self._root.after(0, scan_states.set_mid_scan, self, action.payload or "")
        elif action.kind == ScanActionKind.SERIAL_MATCH:
            model = self._model_scan or ""
            serial = action.payload or ""
            self._state = "MATCHING"
            self._root.after(0, self._state_lbl.configure, {"text": "MATCHING…", "fg": C_WHITE})
            self._root.after(0, self._sec_lbl.configure, {"text": f"Serial: {serial}", "fg": C_DIM})
            threading.Thread(
                target=self._run_match, args=(model, serial, self._current_po), daemon=True
            ).start()

    def _lock_po(self, po_number: str) -> None:
        self._current_po = po_number
        self._model_scan = None
        scan_states.set_idle(self)
        self._log(f"PO switched to {po_number} — scan model")
        threading.Thread(target=self._print_po_label_bg, args=(po_number,), daemon=True).start()

    def _run_resolution(self, raw_barcode: str, po: str) -> None:
        try:
            result = self._resolve_model(raw_barcode, po)  # type: ignore[misc]
        except Exception as exc:
            self._log(f"ERROR during model resolution: {exc}")
            self._root.after(0, self._set_idle)
            return
        self._root.after(0, self._apply_verdict, result, raw_barcode)

    def _apply_verdict(self, result: ModelScanResult, raw_barcode: str) -> None:
        if result.verdict == ScanVerdict.AUTO:
            self._model_scan = result.model
            scan_states.set_mid_scan(self, result.model or raw_barcode)
        elif result.verdict == ScanVerdict.PROPOSE:
            self._proposed_model = result.model
            blocking_states.set_propose(self, raw_barcode, result.model or "")
        else:
            blocking_states.set_needs_model(self, raw_barcode)

    def _run_match(self, model: str, serial: str, po: str) -> None:
        try:
            outcome = handle_scan(model, serial, po, self._process, self._printer)
        except Exception as exc:
            self._log(f"ERROR during scan: {exc}")
            self._root.after(0, self._set_idle)
            return
        self._root.after(0, self._apply_outcome, outcome)

    def _apply_outcome(self, outcome: ScanOutcome) -> None:
        rec = outcome.record
        if outcome.status == "received":
            self._log(
                f"MATCHED  PO:{rec.purchase_order}  Model:{rec.model_number}  Serial:{rec.serial}"
            )
            scan_states.set_match_found(self, rec)
        elif outcome.status == "no_match":
            self._log(f"NO MATCH  PO:{rec.purchase_order}")
            scan_states.set_no_match(self)
        elif outcome.status == "already_scanned":
            self._log(f"ALREADY SCANNED  PO:{rec.purchase_order}  Model:{rec.model_number}")
            scan_states.set_already_scanned(self, rec)
        else:
            self._log(f"PRINT FAILED  PO:{rec.purchase_order}  Model:{rec.model_number}")
            scan_states.set_print_failed(self, rec)

    def _set_idle(self) -> None:
        scan_states.set_idle(self)

    def _dismiss_no_match(self, _event: object = None) -> None:
        scan_states.dismiss_no_match(self)

    def _poll_sync_status(self) -> None:
        try:
            status = self._sync_status_store.read_sync_status()  # type: ignore[union-attr]
            if scan_states.should_alert_sync_stopped(
                status, self._dismissed_sync_stop_at
            ) and self._state not in ("SYNC_STOPPED", "MATCHING"):
                assert status is not None
                self._last_sync_stop_at = status.updated_at
                scan_states.set_sync_stopped(self, status.stopped_reason)
        except Exception as exc:
            _note_poll_error(exc, self._sync_poll_error_logged, self._log, "sync poll")
        self._root.after(1500, self._poll_sync_status)

    def _print_po_label_bg(self, po_number: str) -> None:
        try:
            self._printer.print_po_label(po_number)
        except Exception as exc:
            self._log(f"PO {po_number} label: {exc}")

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

        def _queue(p: str) -> None:
            self._root.after(0, self._add_po, p)

        _populate_and_queue(populate, po, self._log, _queue)

    def _add_po(self, po: str) -> None:
        if po not in self._active_pos:
            self._active_pos.append(po)
            threading.Thread(target=self._print_po_label_bg, args=(po,), daemon=True).start()
        self._current_po = po
        self._set_po_list(self._active_pos)
        self._set_idle()
