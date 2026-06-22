"""
Owns: label printer adapters — ZebraPrinter (ZPL/win32print), PreviewPrinter (HTML
      browser preview), and make_printer() factory.
Must not: import services or DB adapters; must not read environment variables.
May import: core.errors, core.schema, stdlib, win32print (Windows-only, guarded).

Scope: ZebraPrinter is live-untested (DEBT-T16.2-001); use PRINTER_TYPE=preview
in development and CI.
"""

from __future__ import annotations

import tempfile
import webbrowser
from datetime import date
from pathlib import Path

from core.errors import PrinterError
from core.schema import ReceivingRecord

# Module-level reference to webbrowser.open so tests can monkeypatch it.
_open = webbrowser.open

# Cached Zebra printer name — None means not yet searched, "" means not found.
_zebra_printer_name: str | None = None


# ── ZPL helpers ───────────────────────────────────────────────────────────────


def _zpl_safe(s: object) -> str:
    """Strip ZPL control characters ^ and ~ from field data; escape & (ZPL newline)."""
    return str(s or "").replace("^", "").replace("~", "").replace("&", "+")


def _build_zpl(record: ReceivingRecord) -> str:
    """Build a 4" x 3" ZPL label string from the record fields.

    Layout mirrors the oracle label_printer.py _build_zpl byte-faithfully:
      L1  Description (model – category)
      L2  Brand: {brand}
      L4  Purchase Order: {po}
      L5  Model: {model}    SN#: {serial}
      L6  Tags: {tags}
      L7  Inventory ID: {inv_id}
      BC  Code 128 barcode of {inv_id}
      BIG Large inv_id centred below barcode
      --- Separator rule
      FTR Received / Printed dates
    """
    today = date.today().strftime("%m/%d/%Y")
    description = _zpl_safe(f"{record.model_number} - {record.product_category}")
    inv = _zpl_safe(record.inventory_id)
    po = _zpl_safe(record.purchase_order)
    mod = _zpl_safe(record.model_number)
    br = _zpl_safe(record.brand)
    ser = _zpl_safe(record.serial)
    tg = _zpl_safe(record.tags)
    tod = _zpl_safe(today)

    return (
        "^XA\n"
        "^PW812\n"
        "^LL609\n"
        "^CI28\n"
        f"^FO10,20^A0N,28,28^FB790,3,0,L^FD{description}^FS\n"
        f"^FO10,118^A0N,24,24^FDBrand: {br}^FS\n"
        f"^FO10,154^A0N,22,22^FDPurchase Order: {po}^FS\n"
        f"^FO10,182^A0N,28,28^FDModel: {mod}^FS\n"
        f"^FO430,182^A0N,28,28^FDSN#: {ser}^FS\n"
        f"^FO10,246^A0N,20,20^FDTags: {tg}^FS\n"
        f"^FO10,270^A0N,20,20^FDInventory ID: {inv}^FS\n"
        f"^FO10,296^BY4^BCN,80,N,N,N^FD%{inv}%^FS\n"
        f"^FO0,412^A0N,80,80^FB812,1,0,C^FD{inv}^FS\n"
        "^FO10,498^GB790,2,2^FS\n"
        f"^FO10,504^A0N,20,20^FDReceived: {tod}^FS\n"
        f"^FO500,504^A0N,20,20^FDPrinted: {tod}^FS\n"
        "^XZ\n"
    )


def _build_po_zpl(po_number: str) -> str:
    """Build a 4" x 2" ZPL PO label. Barcode encodes 'PO:{po_number}'."""
    today = date.today().strftime("%m/%d/%Y")
    po = _zpl_safe(po_number)
    bc = _zpl_safe(f"PO:{po_number}")
    return (
        "^XA\n"
        "^PW812\n"
        "^LL406\n"
        "^CI28\n"
        "^FO10,15^A0N,28,28^FDPURCHASE ORDER^FS\n"
        f"^FO10,55^A0N,80,80^FD{po}^FS\n"
        f"^FO10,152^BY3^BCN,80,N,N,N^FD{bc}^FS\n"
        f"^FO0,266^A0N,28,28^FB812,1,0,C^FD{bc}^FS\n"
        f"^FO10,316^A0N,22,22^FDPrinted: {today}^FS\n"
        "^XZ\n"
    )


def _find_zebra_printer() -> str:
    """Return the first Zebra/ZDesigner printer name, or empty string if none found.

    Cached after first call. Raises PrinterError only on unexpected enumeration errors.
    """
    global _zebra_printer_name
    if _zebra_printer_name is not None:
        return _zebra_printer_name

    try:
        import win32print  # type: ignore[import-untyped]
    except ImportError:
        _zebra_printer_name = ""
        return ""

    _SEARCH_TERMS = [
        "ZD421-203dpi ZPL",
        "UPS Thermal 2844",
        "ZP 450",
        "ZDesigner ZP",
        "Zebra",
        "ZDesigner",
    ]
    try:
        printers = win32print.EnumPrinters(
            win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS,
            None,
            2,
        )
        names = [p.get("pPrinterName", "") for p in printers]
        for term in _SEARCH_TERMS:
            for name in names:
                if term.lower() in name.lower():
                    _zebra_printer_name = name
                    return name
        _zebra_printer_name = ""
        return ""
    except Exception as exc:
        raise PrinterError(f"Zebra printer enumeration failed — {exc}") from exc


# ── Printer implementations ───────────────────────────────────────────────────


class ZebraPrinter:
    """Sends ZPL labels to a Zebra printer via win32print RAW spool.

    Windows-only: win32print is guarded at import time. Raises PrinterError if no
    Zebra printer is found or if the spool call fails.

    DEBT-T16.2-001: live-untested — no physical Zebra printer in CI.
    """

    def print_label(self, record: ReceivingRecord) -> None:
        printer_name = _find_zebra_printer()
        if not printer_name:
            raise PrinterError(
                "No Zebra printer found — install a ZPL-capable Zebra driver and retry."
            )
        zpl = _build_zpl(record)
        try:
            import win32print  # type: ignore[import-untyped]

            h = win32print.OpenPrinter(printer_name)
            try:
                win32print.StartDocPrinter(h, 1, ("ZPL Label", None, "RAW"))
                try:
                    win32print.StartPagePrinter(h)
                    win32print.WritePrinter(h, zpl.encode("utf-8"))
                    win32print.EndPagePrinter(h)
                finally:
                    win32print.EndDocPrinter(h)
            finally:
                win32print.ClosePrinter(h)
        except ImportError as exc:
            raise PrinterError(
                "win32print not available — ZebraPrinter requires Windows with pywin32 installed."
            ) from exc
        except Exception as exc:
            raise PrinterError(
                f"ZPL spool failed for inventory_id={record.inventory_id!r} — {exc}"
            ) from exc

    def print_po_label(self, po_number: str) -> None:
        printer_name = _find_zebra_printer()
        if not printer_name:
            raise PrinterError(
                "No Zebra printer found — install a ZPL-capable Zebra driver and retry."
            )
        zpl = _build_po_zpl(po_number)
        try:
            import win32print  # type: ignore[import-untyped]

            h = win32print.OpenPrinter(printer_name)
            try:
                win32print.StartDocPrinter(h, 1, ("PO Label", None, "RAW"))
                try:
                    win32print.StartPagePrinter(h)
                    win32print.WritePrinter(h, zpl.encode("utf-8"))
                    win32print.EndPagePrinter(h)
                finally:
                    win32print.EndDocPrinter(h)
            finally:
                win32print.ClosePrinter(h)
        except ImportError as exc:
            raise PrinterError(
                "win32print not available — ZebraPrinter requires Windows with pywin32 installed."
            ) from exc
        except Exception as exc:
            raise PrinterError(
                f"PO label spool failed for po_number={po_number!r} — {exc}"
            ) from exc


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

    def print_po_label(self, po_number: str) -> None:
        try:
            html = (
                "<!DOCTYPE html><html><head><meta charset='utf-8'>"
                "<title>PO Label</title></head><body>"
                f"<h1>Purchase Order</h1><p style='font-size:3em'>{po_number}</p>"
                f"<p>Barcode: PO:{po_number}</p>"
                "</body></html>"
            )
            with tempfile.NamedTemporaryFile(
                "w", suffix=".html", delete=False, encoding="utf-8"
            ) as fh:
                fh.write(html)
                tmp = Path(fh.name)
            _open(tmp.as_uri())
        except Exception as exc:
            raise PrinterError(f"preview PO label failed — {exc}") from exc


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
        f"<dt>Serial</dt><dd>{record.serial}</dd>\n"
        f"<dt>Brand</dt><dd>{record.brand}</dd>\n"
        f"<dt>Vendor</dt><dd>{record.vendor}</dd>\n"
        f"<dt>Tags</dt><dd>{record.tags}</dd>\n"
        f"<dt>Status</dt><dd>{record.match_status}</dd>\n"
        f"<dt>Truck</dt><dd>{record.truck}</dd>\n"
        f"<dt>Stop</dt><dd>{record.stop}</dd>\n"
        f"<dt>Sales Order</dt><dd>{record.sales_order}</dd>\n"
        f"<dt>Size</dt><dd>{dims}</dd>\n"
        f"<dt>Qty</dt><dd>{record.quantity}</dd>\n"
        f"<dt>Timestamp</dt><dd>{record.timestamp}</dd>\n"
        "</dl></body></html>"
    )


# ── Factory ───────────────────────────────────────────────────────────────────


def make_printer(printer_type: str) -> ZebraPrinter | PreviewPrinter:
    """Construct a Printer from a type string.

    Raises PrinterError for any unrecognised printer_type.
    """
    if printer_type == "preview":
        return PreviewPrinter()
    if printer_type == "zebra":
        return ZebraPrinter()
    raise PrinterError(f"Unknown PRINTER_TYPE '{printer_type}' — supported values: preview, zebra.")
