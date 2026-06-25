"""
Owns: header-validation tests for _parse_on_order_csv (BUG-SOURCE-CSV-001 fix).
Must not: import services, adapters.db, adapters.sink.
May import: pytest, pathlib, adapters.source, core.errors.

not_measured: live portal column drift confirmed against a real portal session;
              BOM encoding edge cases (utf-8-sig strips BOM before DictReader sees headers).
"""

from pathlib import Path

import pytest

from adapters.source import _parse_on_order_csv
from core.errors import SourceError

_VALID_HEADER = "Inventory Id,PO #,Model,Category,Brand,Tags"
_VALID_ROW = "INV-1,PO-001,MDL-A,Chair,Acme,"


def _write(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "test.csv"
    p.write_text(content, encoding="utf-8-sig")
    return p


def test_missing_model_column_raises_source_error(tmp_path: Path):
    """Missing 'Model' must raise SourceError naming the absent column."""
    p = _write(tmp_path, "Inventory Id,PO #,Category,Brand,Tags\nINV-1,PO-001,Chair,Acme,\n")
    with pytest.raises(SourceError, match="Model"):
        _parse_on_order_csv(p)


def test_missing_inventory_id_column_raises_source_error(tmp_path: Path):
    """Missing 'Inventory Id' must raise SourceError — NOT silently return []."""
    p = _write(tmp_path, "PO #,Model,Category,Brand,Tags\nPO-001,MDL-A,Chair,Acme,\n")
    with pytest.raises(SourceError, match="Inventory Id"):
        _parse_on_order_csv(p)


def test_missing_po_column_raises_source_error(tmp_path: Path):
    """Missing 'PO #' must raise SourceError naming the absent column."""
    p = _write(tmp_path, "Inventory Id,Model,Category,Brand,Tags\nINV-1,MDL-A,Chair,Acme,\n")
    with pytest.raises(SourceError, match=r"PO #"):
        _parse_on_order_csv(p)


def test_multiple_missing_columns_all_named_in_error(tmp_path: Path):
    """When several required columns are absent, all must appear in the SourceError message."""
    p = _write(tmp_path, "Category,Brand,Tags\nChair,Acme,\n")
    with pytest.raises(SourceError) as exc_info:
        _parse_on_order_csv(p)
    msg = str(exc_info.value)
    assert "Inventory Id" in msg
    assert "PO #" in msg
    assert "Model" in msg


def test_valid_headers_with_data_rows_parses_correctly(tmp_path: Path):
    """Regression guard: well-formed CSV still parses without error."""
    p = _write(tmp_path, f"{_VALID_HEADER}\n{_VALID_ROW}\n")
    rows = _parse_on_order_csv(p)
    assert len(rows) == 1
    assert rows[0]["inventory_id"] == "INV-1"
    assert rows[0]["purchase_order"] == "PO-001"
    assert rows[0]["model_number"] == "MDL-A"


def test_valid_headers_zero_data_rows_returns_empty_list(tmp_path: Path):
    """Headers-only CSV (genuinely empty export) returns [] without raising."""
    p = _write(tmp_path, f"{_VALID_HEADER}\n")
    rows = _parse_on_order_csv(p)
    assert rows == []


def test_optional_columns_absent_does_not_raise(tmp_path: Path):
    """Category, Brand, and Tags are optional — CSV without them must not raise."""
    p = _write(tmp_path, "Inventory Id,PO #,Model\nINV-1,PO-001,MDL-A\n")
    rows = _parse_on_order_csv(p)
    assert len(rows) == 1
    assert rows[0]["brand"] is None
    assert rows[0]["tags"] is None
    assert rows[0]["description"] is None
