"""
Owns: headless tests for adapters/scanner.py factory logic.
Must not: construct a Tk root or any widget (requires display — see DEBT-T11b-001).
May import: adapters.scanner, core.errors, pytest, tkinter (via importorskip only).

not_measured: WedgeScanner widget construction, ManualScanner widget construction,
              focus_entry(), start/stop callbacks — all require a live Tk display.
"""

from __future__ import annotations

import pytest


def test_make_scanner_unknown_type_raises():
    pytest.importorskip("tkinter")  # scanner.py imports tkinter at module top
    from adapters.scanner import make_scanner
    from core.errors import ScannerError

    with pytest.raises(ScannerError):
        make_scanner("bogus", None)  # raises before constructing any widget
