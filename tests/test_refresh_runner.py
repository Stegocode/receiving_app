"""
Owns: tests for refresh_runner._execute — exit codes and console messages.
Must not: import concrete adapters; must not read config or touch SQLite.
May import: pytest, refresh_runner, services.refresh, tests.fakes.

not_measured: main() I/O composition (input(), config.validate(), adapter construction).

PASS:   SUCCESS → exit code 0, message contains "complete".
CANCEL: CANCELLED → exit code 1, message does NOT contain "complete".
EMPTY:  EMPTY_ABORT → exit code 2, message does NOT contain "complete".
"""

from __future__ import annotations

import pytest

from refresh_runner import _execute
from tests.fakes.fake_db import FakeRepository
from tests.fakes.fake_source import FakePurchaseOrderSource

_ITEM = {
    "inventory_id": "ITEM-001",
    "purchase_order": "PO-001",
    "model_number": "MDL-001",
    "description": "",
    "brand": "",
    "vendor": "",
    "tags": "",
    "created_at": "2026-06-24T08:00:00",
}


def test_execute_success_exit_code(capsys: pytest.CaptureFixture[str]) -> None:
    """SUCCESS → exit code 0 and message contains 'complete'."""
    repo = FakeRepository()
    source = FakePurchaseOrderSource({"PO-001": [_ITEM]})

    code = _execute(source, repo, confirmed=True)

    assert code == 0
    out = capsys.readouterr().out
    assert "complete" in out.lower()


def test_execute_cancelled_exit_code(capsys: pytest.CaptureFixture[str]) -> None:
    """CANCELLED (confirmed=False) → exit code 1; message does NOT say 'complete'."""
    repo = FakeRepository()
    source = FakePurchaseOrderSource({"PO-001": [_ITEM]})

    code = _execute(source, repo, confirmed=False)

    assert code == 1
    out = capsys.readouterr().out
    assert "complete" not in out.lower()
    assert "cancel" in out.lower()


def test_execute_empty_abort_exit_code(capsys: pytest.CaptureFixture[str]) -> None:
    """EMPTY_ABORT → exit code 2; message does NOT say 'complete'; DB untouched."""
    repo = FakeRepository()
    repo.upsert_items([_ITEM])
    source = FakePurchaseOrderSource({})  # empty source → EMPTY_ABORT

    code = _execute(source, repo, confirmed=True)

    assert code == 2
    out = capsys.readouterr().out
    assert "complete" not in out.lower()
    assert "abort" in out.lower()
    assert repo.count_po_items() == 1  # DB untouched


def test_execute_exit_codes_are_distinct() -> None:
    """All three outcomes map to distinct exit codes."""
    from refresh_runner import _EXIT_CODES

    codes = list(_EXIT_CODES.values())
    assert len(codes) == len(set(codes)), "exit codes must be distinct"


def test_execute_success_reports_item_count(capsys: pytest.CaptureFixture[str]) -> None:
    """SUCCESS message includes the post-refresh item count."""
    items = [{**_ITEM, "inventory_id": f"ITEM-{i}"} for i in range(3)]
    repo = FakeRepository()
    source = FakePurchaseOrderSource({"PO-001": items})

    code = _execute(source, repo, confirmed=True)

    assert code == 0
    out = capsys.readouterr().out
    assert "3" in out
