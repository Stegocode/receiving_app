"""
Owns: in-memory Printer fake for use in tests.
Must not: perform real I/O; must not import adapters.
May import: core.errors, core.schema.
"""

from __future__ import annotations

from core.errors import PrinterError
from core.schema import ReceivingRecord


class FakePrinter:
    """Test double for the Printer port.

    Records every label printed. Raises PrinterError on every call when
    constructed with fail=True.
    """

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.printed: list[ReceivingRecord] = []
        self.printed_po_labels: list[str] = []

    def print_label(self, record: ReceivingRecord) -> None:
        if self.fail:
            raise PrinterError("FakePrinter configured to fail.")
        self.printed.append(record)

    def print_po_label(self, po_number: str) -> None:
        if self.fail:
            raise PrinterError("FakePrinter configured to fail.")
        self.printed_po_labels.append(po_number)
