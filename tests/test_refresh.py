"""
Owns: tests for services.refresh.refresh_all.
Must not: import concrete adapters; must not perform real network or DB I/O.
May import: pytest, services.refresh, tests.fakes.

not_measured: real network calls, real portal scraper, real SQLite file,
              real USB scanner device, real empty-catalog recovery procedure.

PASS:         after a successful confirmed refresh, count_po_items() == len(fetched rows).
PARTIAL:      empty fetch or unconfirmed → catalog unchanged.
KILL:         a fetch failure must NEVER empty the catalog
              (proved by test_failing_fetch_leaves_catalog_intact).
"""

from __future__ import annotations

import pytest

from services.refresh import RefreshResult, refresh_all
from tests.fakes.fake_db import FakeRepository
from tests.fakes.fake_source import FakePurchaseOrderSource

_OLD_ITEM = {
    "inventory_id": "OLD-001",
    "purchase_order": "PO-OLD",
    "model_number": "OLD-MODEL",
    "description": "",
    "brand": "",
    "vendor": "",
    "tags": "",
    "created_at": "2026-06-19T08:00:00",
}

_NEW_ITEM = {
    "inventory_id": "NEW-001",
    "purchase_order": "PO-NEW",
    "model_number": "NEW-MODEL",
    "description": "",
    "brand": "",
    "vendor": "",
    "tags": "",
    "created_at": "2026-06-19T10:00:00",
}


def test_refresh_confirmed_returns_success() -> None:
    """confirmed=True with rows → SUCCESS; old items replaced by new items."""
    repo = FakeRepository()
    repo.upsert_items([_OLD_ITEM])
    assert repo.count_po_items() == 1

    source = FakePurchaseOrderSource({"PO-NEW": [_NEW_ITEM]})

    result = refresh_all(source, repo, confirmed=True)

    assert result is RefreshResult.SUCCESS
    assert repo.count_po_items() == 1
    assert repo.get_purchase_order("PO-OLD") == []
    assert len(repo.get_purchase_order("PO-NEW")) == 1


def test_refresh_not_confirmed_returns_cancelled() -> None:
    """confirmed=False → CANCELLED; source never called; repo left unchanged."""
    repo = FakeRepository()
    repo.upsert_items([_OLD_ITEM])

    class _FailSource:
        def fetch_all_open_orders(self) -> list:
            raise RuntimeError("source must not be called when not confirmed")

        def fetch_order(self, po_number: str) -> list:
            raise RuntimeError("source must not be called when not confirmed")

    result = refresh_all(_FailSource(), repo, confirmed=False)

    assert result is RefreshResult.CANCELLED
    assert repo.count_po_items() == 1
    assert len(repo.get_purchase_order("PO-OLD")) == 1


def test_empty_fetch_returns_empty_abort() -> None:
    """An empty fetch result → EMPTY_ABORT; DB untouched.

    KILL-criterion: a mutation removing the empty-fetch guard calls
    replace_po_items([]) and leaves count=0, failing the count assertion.
    """
    repo = FakeRepository()
    repo.upsert_items([_OLD_ITEM])
    assert repo.count_po_items() == 1

    source = FakePurchaseOrderSource({})

    result = refresh_all(source, repo, confirmed=True)

    assert result is RefreshResult.EMPTY_ABORT
    assert repo.count_po_items() == 1
    assert len(repo.get_purchase_order("PO-OLD")) == 1


def test_failing_fetch_leaves_catalog_intact() -> None:
    """A failing fetch_all_open_orders must NOT touch the DB.

    This is the KILL-criterion test: a mutation that reverts refresh_all to
    wipe-first will clear the catalog before the fetch raises, leaving count=0
    and failing this assertion.
    """
    repo = FakeRepository()
    repo.upsert_items([_OLD_ITEM])
    assert repo.count_po_items() == 1

    class _FailingSource:
        def fetch_all_open_orders(self) -> list:
            raise RuntimeError("portal unreachable")

        def fetch_order(self, po_number: str) -> list:
            raise RuntimeError("portal unreachable")

    with pytest.raises(RuntimeError, match="portal unreachable"):
        refresh_all(_FailingSource(), repo, confirmed=True)

    assert repo.count_po_items() == 1
    assert len(repo.get_purchase_order("PO-OLD")) == 1


def test_success_count_matches_fetched_rows() -> None:
    """PASS criterion: after SUCCESS, count_po_items() == len(fetched rows)."""
    items = [
        {**_NEW_ITEM, "inventory_id": f"ITEM-{i}", "purchase_order": "PO-BIG"} for i in range(5)
    ]
    repo = FakeRepository()
    source = FakePurchaseOrderSource({"PO-BIG": items})

    result = refresh_all(source, repo, confirmed=True)

    assert result is RefreshResult.SUCCESS
    assert repo.count_po_items() == len(items)


def test_cancelled_result_is_distinct_from_empty_abort() -> None:
    """CANCELLED and EMPTY_ABORT are distinct enum members — callers can branch on them."""
    assert RefreshResult.CANCELLED is not RefreshResult.EMPTY_ABORT
    assert RefreshResult.CANCELLED is not RefreshResult.SUCCESS
    assert RefreshResult.EMPTY_ABORT is not RefreshResult.SUCCESS
