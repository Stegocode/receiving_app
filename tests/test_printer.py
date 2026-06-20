"""
Owns: tests for adapters.printer — PreviewPrinter and make_printer factory.
Must not: open a real browser or write to real temp paths (webbrowser.open monkeypatched).
May import: adapters.printer, core.errors, core.schema, pytest, stdlib.

not_measured: real browser rendering, OS file-open behaviour, real print device.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

import adapters.printer as printer_mod
from adapters.printer import PreviewPrinter, make_printer
from core.errors import PrinterError
from core.schema import from_dict


def _make_record():
    return from_dict(
        {
            "receiving_id": "test-abc-001",
            "purchase_order": "PO-9001",
            "inventory_id": "INV-001",
            "model_number": "MDL-X",
            "product_category": "Furniture",
            "truck": "T1",
            "stop": "S2",
            "sales_order": "SO-500",
            "product_size": {"w": 24, "d": 18, "h": 36},
            "quantity": 2,
            "match_status": "received",
            "timestamp": datetime.now().isoformat(),
        }
    )


def test_preview_printer_writes_html_and_opens_uri(monkeypatch):
    """print_label creates an HTML file and calls _open with its file:// URI."""
    opened: list[str] = []
    monkeypatch.setattr(printer_mod, "_open", lambda uri: opened.append(uri))

    record = _make_record()
    PreviewPrinter().print_label(record)

    assert len(opened) == 1
    uri = opened[0]
    assert uri.startswith("file://")
    html_path = Path(uri[len("file://") :])
    assert html_path.suffix == ".html"
    assert html_path.exists()


def test_preview_printer_html_contains_po(monkeypatch):
    """HTML content includes the purchase order number."""
    monkeypatch.setattr(printer_mod, "_open", lambda uri: None)
    record = _make_record()
    # Capture the temp file path by intercepting _open before it discards the uri.
    written: list[str] = []

    def capture(uri):
        written.append(uri)

    monkeypatch.setattr(printer_mod, "_open", capture)
    PreviewPrinter().print_label(record)
    html_path = Path(written[0][len("file://") :])
    content = html_path.read_text(encoding="utf-8")
    assert record.purchase_order in content
    assert record.model_number in content


def test_make_printer_preview_returns_preview_printer():
    """make_printer('preview') returns a PreviewPrinter instance."""
    printer = make_printer("preview")
    assert isinstance(printer, PreviewPrinter)


def test_make_printer_unknown_type_raises_printer_error():
    """make_printer with an unrecognised type raises PrinterError."""
    with pytest.raises(PrinterError, match="Unknown PRINTER_TYPE"):
        make_printer("zebra_zpl")


def test_print_label_wraps_open_failure_in_printer_error(monkeypatch):
    """If _open raises, print_label re-raises as PrinterError."""

    def _raise(_uri):
        raise OSError("no browser")

    monkeypatch.setattr(printer_mod, "_open", _raise)
    with pytest.raises(PrinterError, match="preview label failed"):
        PreviewPrinter().print_label(_make_record())
