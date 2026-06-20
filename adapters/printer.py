"""
Owns: label printer adapter — HTML preview and printer factory.
Must not: import services or DB adapters; must not read environment variables.
May import: core.errors, core.ports, core.schema, stdlib.
"""

from __future__ import annotations

import tempfile
import webbrowser
from pathlib import Path

from core.errors import PrinterError
from core.schema import ReceivingRecord

# Module-level reference to webbrowser.open so tests can monkeypatch it.
_open = webbrowser.open


class PreviewPrinter:
    """Renders a receiving label as HTML and opens it in the default browser."""

    def print_label(self, record: ReceivingRecord) -> None:
        try:
            html = _render_label(record)
            with tempfile.NamedTemporaryFile(
                "w", suffix=".html", delete=False, encoding="utf-8"
            ) as fh:
                fh.write(html)
                tmp = Path(fh.name)
            _open(tmp.as_uri())
        except Exception as exc:
            raise PrinterError(f"preview label failed — {exc}") from exc


def _render_label(record: ReceivingRecord) -> str:
    size = record.product_size
    dims = f"{size.get('w', 0)} x {size.get('d', 0)} x {size.get('h', 0)}"
    return (
        "<!DOCTYPE html>\n"
        "<html><head><meta charset='utf-8'>"
        "<title>Receiving Label</title></head><body>\n"
        "<h1>Receiving Label</h1><dl>\n"
        f"<dt>PO</dt><dd>{record.purchase_order}</dd>\n"
        f"<dt>Model</dt><dd>{record.model_number}</dd>\n"
        f"<dt>Inventory ID</dt><dd>{record.inventory_id}</dd>\n"
        f"<dt>Status</dt><dd>{record.match_status}</dd>\n"
        f"<dt>Truck</dt><dd>{record.truck}</dd>\n"
        f"<dt>Stop</dt><dd>{record.stop}</dd>\n"
        f"<dt>Sales Order</dt><dd>{record.sales_order}</dd>\n"
        f"<dt>Size</dt><dd>{dims}</dd>\n"
        f"<dt>Qty</dt><dd>{record.quantity}</dd>\n"
        f"<dt>Timestamp</dt><dd>{record.timestamp}</dd>\n"
        "</dl></body></html>"
    )


def make_printer(printer_type: str) -> PreviewPrinter:
    """Construct a Printer from a type string.

    Raises PrinterError for any unrecognised printer_type.
    """
    if printer_type == "preview":
        return PreviewPrinter()
    raise PrinterError(f"Unknown PRINTER_TYPE '{printer_type}' — supported values: preview.")
