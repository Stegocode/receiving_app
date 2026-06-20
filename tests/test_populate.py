"""
Owns: tests for services.populate.populate_po.
Must not: import concrete adapters; must not perform real network or DB I/O.
May import: pytest, services.populate, tests.fakes.

not_measured: real network calls, real portal scraper, real SQLite file,
              real USB scanner device.

SKIP:    PO already has rows → source.fetch_order never called (idempotent).
FETCH:   PO missing from repo → source.fetch_order called, rows upserted.
"""

from __future__ import annotations

from services.populate import populate_po
from tests.fakes.fake_db import FakeRepository
from tests.fakes.fake_source import FakePurchaseOrderSource

_PO = "PO-001"
_ITEM = {
    "inventory_id": "INV-001",
    "purchase_order": _PO,
    "model_number": "MODEL-A",
    "description": "Chair",
    "brand": "Brand A",
    "vendor": "Vendor A",
    "tags": "",
    "created_at": "2026-06-19T10:00:00",
}


class _TrackingSource:
    """Wraps FakePurchaseOrderSource and records fetch_order calls."""

    def __init__(self, fixture: dict[str, list[dict]]) -> None:
        self._inner = FakePurchaseOrderSource(fixture)
        self.fetch_order_calls: list[str] = []

    def fetch_order(self, po_number: str) -> list[dict]:
        self.fetch_order_calls.append(po_number)
        return self._inner.fetch_order(po_number)

    def fetch_all_open_orders(self) -> list[dict]:
        return self._inner.fetch_all_open_orders()


def test_populate_already_present() -> None:
    """PO rows already in repo → source.fetch_order is NOT called (idempotent skip)."""
    repo = FakeRepository()
    repo.upsert_items([_ITEM])
    source = _TrackingSource({_PO: [_ITEM]})

    populate_po(_PO, repo, source)

    assert source.fetch_order_calls == []  # source was never queried
    assert len(repo.get_purchase_order(_PO)) == 1  # original row untouched


def test_populate_missing() -> None:
    """PO not in repo → source.fetch_order called once, rows upserted into repo."""
    repo = FakeRepository()
    source = _TrackingSource({_PO: [_ITEM]})

    populate_po(_PO, repo, source)

    assert source.fetch_order_calls == [_PO]  # exactly one fetch
    rows = repo.get_purchase_order(_PO)
    assert len(rows) == 1
    assert rows[0]["inventory_id"] == "INV-001"
