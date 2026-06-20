"""
Owns: tests for services.receive.process_scan.
Must not: import concrete adapters; must not perform real network or DB I/O.
May import: pytest, services.receive, tests.fakes.

not_measured: real network calls, real SQLite file, real result sink API,
              real USB scanner device, real Tkinter UI.

PASS:       barcode matches a PO candidate → match_status='received', emit called once.
NO_MATCH:   barcode matches nothing → match_status='no_match', emit called once.
IDEMPOTENT: same scan inputs twice → was_emitted guard blocks second emit call.
"""

from __future__ import annotations

from core.schema import ReceivingRecord
from services.receive import process_scan
from tests.fakes.fake_db import FakeRepository
from tests.fakes.fake_sink import FakeResultSink

_TIMESTAMP = "2026-06-19T10:00:00"


def _make_candidate(
    inventory_id: str,
    model_number: str,
    po_number: str,
) -> dict:
    return {
        "inventory_id": inventory_id,
        "purchase_order": po_number,
        "model_number": model_number,
        "product_category": "Furniture",
        "truck": "T1",
        "stop": "S1",
        "sales_order": "SO-001",
        "product_size": {"w": 10.0, "d": 20.0, "h": 30.0},
        "quantity": 2,
        "brand": "Brand A",
        "vendor": "Vendor A",
        "tags": "",
        "created_at": _TIMESTAMP,
    }


def test_process_scan_match() -> None:
    """Matching barcode → match_status='received', record saved, emit called once."""
    repo = FakeRepository()
    sink = FakeResultSink()
    repo.upsert_items([_make_candidate("INV-001", "MODEL-A", "PO-001")])

    record = process_scan("MODEL-A", "PO-001", repo, sink)

    assert record.match_status == "received"
    assert record.purchase_order == "PO-001"
    assert record.inventory_id == "INV-001"
    assert record.model_number == "MODEL-A"
    assert repo.was_emitted(record.receiving_id)
    assert len(sink.emitted) == 1
    assert sink.emitted[0].receiving_id == record.receiving_id


def test_process_scan_no_match() -> None:
    """No matching candidate → match_status='no_match', routed through emit, record saved."""
    repo = FakeRepository()
    sink = FakeResultSink()
    repo.upsert_items([_make_candidate("INV-001", "MODEL-A", "PO-001")])

    record = process_scan("ZZZZZ-NOMATCH-999", "PO-001", repo, sink)

    assert record.match_status == "no_match"
    assert record.inventory_id == ""
    assert record.purchase_order == "PO-001"
    assert repo.was_emitted(record.receiving_id)
    assert len(sink.emitted) == 1
    assert len(sink.attention) == 0


def test_process_scan_idempotent() -> None:
    """Same scan inputs twice → was_emitted guard blocks second emit; call count is exactly 1."""
    repo = FakeRepository()

    class _CountingSink:
        def __init__(self) -> None:
            self.emit_call_count = 0

        def emit(self, record: ReceivingRecord) -> None:
            self.emit_call_count += 1

        def surface_attention(self, record: ReceivingRecord) -> None:
            self.emit_call_count += 1

    sink = _CountingSink()
    repo.upsert_items([_make_candidate("INV-001", "MODEL-A", "PO-001")])

    record1 = process_scan("MODEL-A", "PO-001", repo, sink)
    record2 = process_scan("MODEL-A", "PO-001", repo, sink)

    assert record1.receiving_id == record2.receiving_id
    assert sink.emit_call_count == 1  # was_emitted guard prevented second call
