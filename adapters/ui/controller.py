"""
Owns: scan/print orchestration — coordinate a barcode scan with the print adapter.
Must not: import services; must not import tkinter; must not read environment variables.
May import: core.errors, core.ports, core.schema, collections.abc, dataclasses.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from core.errors import PrinterError
from core.ports import Printer
from core.schema import ReceivingRecord


@dataclass(frozen=True)
class ScanOutcome:
    """Result of a single scan-and-print cycle.

    status: "received" | "no_match" | "already_scanned" | "print_failed"
    record: the ReceivingRecord produced by the scan (always present).
    """

    status: str
    record: ReceivingRecord


def handle_scan(
    barcode: str,
    serial: str,
    po_number: str,
    process: Callable[[str, str, str], ReceivingRecord],
    printer: Printer,
) -> ScanOutcome:
    """Process one barcode scan and print a label if the record matched.

    process(barcode, serial, po_number) is injected (adapters must not import
    services directly). serial is the second scan (serial number barcode); pass
    empty string when running in single-scan mode.
    PrinterError is caught and surfaced as status "print_failed" — the record
    is already saved and can be re-printed without re-scanning.
    """
    record = process(barcode, serial, po_number)
    if record.match_status == "already_scanned":
        return ScanOutcome("already_scanned", record)
    if record.match_status != "received":
        return ScanOutcome("no_match", record)
    try:
        printer.print_label(record)
    except PrinterError:
        return ScanOutcome("print_failed", record)
    return ScanOutcome("received", record)
