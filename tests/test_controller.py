"""
Owns: tests for adapters.ui.controller — handle_scan outcome paths.
Must not: import concrete scanner or printer adapters; no real I/O.
May import: adapters.ui.controller, tests.fakes, core.schema, core.errors, pytest.

not_measured: real scanner hardware, real printer, real DB writes, real sink calls.

PASS paths:
  received record  → printer called once, ScanOutcome.status == "received"
  no_match record  → printer NOT called, ScanOutcome.status == "no_match"
  print_failed     → PrinterError caught, ScanOutcome.status == "print_failed"
"""

from __future__ import annotations

from datetime import datetime

from adapters.ui.controller import ScanOutcome, handle_scan
from core.schema import ReceivingRecord, from_dict
from tests.fakes.fake_printer import FakePrinter


def _make_record(match_status: str) -> ReceivingRecord:
    is_match = match_status == "received"
    return from_dict(
        {
            "receiving_id": "ctrl-test-001",
            "purchase_order": "PO-001",
            "inventory_id": "INV-001" if is_match else "",
            "model_number": "MDL-X" if is_match else "",
            "product_category": "Electronics" if is_match else "",
            "truck": "T1" if is_match else "",
            "stop": "S1" if is_match else "",
            "sales_order": "SO-001" if is_match else "",
            "product_size": {"w": 10, "d": 10, "h": 10},
            "quantity": 1,
            "match_status": match_status,
            "timestamp": datetime.now().isoformat(),
        }
    )


def _process_stub(status: str):
    """Return a process Callable that always produces a record with the given status."""

    def process(barcode: str, serial: str, po_number: str) -> ReceivingRecord:
        return _make_record(status)

    return process


def test_received_calls_printer_and_returns_received():
    """Received record — printer.print_label called once, outcome.status == 'received'."""
    printer = FakePrinter()
    outcome = handle_scan("SCAN-001", "", "PO-001", _process_stub("received"), printer)
    assert outcome.status == "received"
    assert isinstance(outcome, ScanOutcome)
    assert len(printer.printed) == 1


def test_no_match_does_not_call_printer():
    """No-match record — printer is not called, outcome.status == 'no_match'."""
    printer = FakePrinter()
    outcome = handle_scan("SCAN-002", "", "PO-001", _process_stub("no_match"), printer)
    assert outcome.status == "no_match"
    assert len(printer.printed) == 0


def test_printer_error_returns_print_failed_without_raising():
    """PrinterError during print — outcome.status == 'print_failed', no exception escapes."""
    printer = FakePrinter(fail=True)
    outcome = handle_scan("SCAN-003", "", "PO-001", _process_stub("received"), printer)
    assert outcome.status == "print_failed"
    assert isinstance(outcome.record, ReceivingRecord)


def test_outcome_record_matches_process_result():
    """ScanOutcome.record is the exact object returned by process."""
    printer = FakePrinter()
    expected = _make_record("received")
    outcome = handle_scan("SCAN-004", "SN-XYZ", "PO-001", lambda b, s, p: expected, printer)
    assert outcome.record is expected


def test_serial_passed_through_to_process():
    """handle_scan passes serial to process Callable as the second positional arg."""
    printer = FakePrinter()
    captured: dict = {}

    def process(barcode: str, serial: str, po_number: str) -> ReceivingRecord:
        captured["serial"] = serial
        return _make_record("received")

    handle_scan("SCAN-005", "SN-CAPTURED-123", "PO-001", process, printer)
    assert captured["serial"] == "SN-CAPTURED-123"
