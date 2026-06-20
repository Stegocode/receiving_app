"""
Owns: barcode scanner adapters — wedge (HID) and manual (keyboard) input.
Must not: import services or DB adapters.
May import: core.errors, tkinter (event binding only), collections.abc.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable

from core.errors import ScannerError


class WedgeScanner:
    """HID USB scanner via a hidden 1×1 Entry widget kept focused at all times.

    USB HID guns output text + Enter. The hidden entry captures keystrokes;
    <Return> reads the text, clears the widget, keeps focus on the entry, and
    delivers the text to the registered on_scan callback. Call focus_entry()
    to get the entry widget for focus-restore polling in the host UI.
    """

    def __init__(self, parent: tk.Misc) -> None:
        self._on_scan: Callable[[str], None] | None = None
        bg = parent.cget("bg")
        self._var = tk.StringVar()
        self._entry = tk.Entry(
            parent,
            textvariable=self._var,
            bg=bg,
            fg=bg,
            insertbackground=bg,
            relief="flat",
            bd=0,
            highlightthickness=0,
        )
        self._entry.place(x=0, y=0, width=1, height=1)
        self._entry.bind("<Return>", self._on_return)

    def start(self, on_scan: Callable[[str], None]) -> None:
        self._on_scan = on_scan
        self._entry.focus_force()

    def stop(self) -> None:
        self._on_scan = None

    def focus_entry(self) -> tk.Entry:
        """Return the hidden entry widget for focus-restore polling by the host UI."""
        return self._entry

    def _on_return(self, _event: object = None) -> None:
        text = self._var.get().strip()
        self._var.set("")
        self._entry.focus_force()
        if text and self._on_scan:
            self._on_scan(text)


class ManualScanner:
    """Visible Entry + Submit button for development and testing without a USB gun."""

    def __init__(self, parent: tk.Misc) -> None:
        self._on_scan: Callable[[str], None] | None = None
        self._var = tk.StringVar()
        frame = tk.Frame(parent, bg=parent.cget("bg"))
        frame.place(relx=0.5, rely=0.96, anchor="s")
        self._entry = tk.Entry(
            frame,
            textvariable=self._var,
            width=22,
            font=("Arial", 14),
        )
        self._entry.pack(side="left", padx=(0, 6))
        self._entry.bind("<Return>", self._submit)
        tk.Button(
            frame,
            text="Submit",
            command=self._submit,
            font=("Arial", 13),
        ).pack(side="left")

    def start(self, on_scan: Callable[[str], None]) -> None:
        self._on_scan = on_scan
        self._entry.focus_set()

    def stop(self) -> None:
        self._on_scan = None

    def _submit(self, _event: object = None) -> None:
        text = self._var.get().strip()
        self._var.set("")
        if text and self._on_scan:
            self._on_scan(text)


def make_scanner(
    scanner_type: str,
    parent: tk.Misc,
) -> WedgeScanner | ManualScanner:
    """Construct a Scanner from a type string.

    Raises ScannerError for unknown scanner_type values.
    """
    if scanner_type == "wedge":
        return WedgeScanner(parent)
    if scanner_type == "manual":
        return ManualScanner(parent)
    raise ScannerError(f"Unknown SCANNER_TYPE '{scanner_type}' — supported values: wedge, manual.")
