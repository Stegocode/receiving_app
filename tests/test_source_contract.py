"""
Owns: contract tests for _parse_on_order_csv — pins the CSV column shape that
      PortalSource expects from the portal inventory export.
Must not: launch a browser, make network calls, or import adapters.db or services.
May import: pytest, pathlib, adapters.source._parse_on_order_csv, core.errors.

not_measured: live portal session behavior; login-flow or filter-checkbox changes;
              download-directory cleanup; download-filename pattern changes.

BUG-SOURCE-CSV-001 (reported, not fixed here — separate ticket): _parse_on_order_csv
does not validate that the required column headers "PO #" and "Model" are present.
If the portal renames either column, every row is silently returned with an empty
purchase_order or model_number rather than raising SourceError (Rule 4 violation).
Likewise, if "Inventory Id" is renamed, all rows are silently skipped and the caller
receives [] — indistinguishable from a genuinely empty export. These malformed-header
cases are NOT exercised below; adding them would expose a bug, not confirm a contract.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from adapters.source import _parse_on_order_csv
from core.errors import SourceError

# ── CSV helpers ───────────────────────────────────────────────────────────────

_CANONICAL_HEADER = "Inventory Id,PO #,Model,Category,Brand,Tags"

_CANONICAL_ROW = "INV-001,PO-2026-001,MDL-X,Furniture,BrandCo,promo"


def _write(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "inventory.csv"
    p.write_text(content, encoding="utf-8-sig")
    return p


# ── Well-formed canonical shape ───────────────────────────────────────────────


def test_canonical_csv_output_dict_has_exactly_7_keys(tmp_path: Path) -> None:
    """A well-formed row produces a dict with exactly the 7 expected field names."""
    p = _write(tmp_path, f"{_CANONICAL_HEADER}\n{_CANONICAL_ROW}\n")
    rows = _parse_on_order_csv(p)

    assert len(rows) == 1
    assert set(rows[0].keys()) == {
        "inventory_id",
        "purchase_order",
        "model_number",
        "description",
        "brand",
        "vendor",
        "tags",
    }


def test_canonical_csv_field_values_map_correctly(tmp_path: Path) -> None:
    """Each column maps to the correct output field name and value."""
    p = _write(tmp_path, f"{_CANONICAL_HEADER}\n{_CANONICAL_ROW}\n")
    row = _parse_on_order_csv(p)[0]

    assert row["inventory_id"] == "INV-001"
    assert row["purchase_order"] == "PO-2026-001"
    assert row["model_number"] == "MDL-X"
    assert row["description"] == "Furniture"
    assert row["brand"] == "BrandCo"
    assert row["tags"] == "promo"


def test_vendor_is_always_none_regardless_of_csv_content(tmp_path: Path) -> None:
    """vendor is hardcoded None — the portal CSV carries no Vendor column.

    Even if an extra 'Vendor' column is present, the output field is None
    because the parser does not read that column.
    """
    header = f"{_CANONICAL_HEADER},Vendor"
    row = "INV-002,PO-002,MDL-Y,Seating,AcmeCo,sale,Supplier Inc"
    p = _write(tmp_path, f"{header}\n{row}\n")
    result = _parse_on_order_csv(p)

    assert result[0]["vendor"] is None


# ── Category / Product Group fallback chain ───────────────────────────────────


def test_category_column_takes_priority_over_product_group(tmp_path: Path) -> None:
    """When both Category and Product Group are present, Category wins."""
    header = "Inventory Id,PO #,Model,Category,Product Group,Brand,Tags"
    row = "INV-003,PO-003,MDL-Z,Chairs,Seating,,,"
    p = _write(tmp_path, f"{header}\n{row}\n")
    result = _parse_on_order_csv(p)

    assert result[0]["description"] == "Chairs"


def test_product_group_used_when_category_is_absent(tmp_path: Path) -> None:
    """When Category column is absent but Product Group is present, Product Group is used."""
    header = "Inventory Id,PO #,Model,Product Group,Brand,Tags"
    row = "INV-004,PO-004,MDL-A,Sofas,,"
    p = _write(tmp_path, f"{header}\n{row}\n")
    result = _parse_on_order_csv(p)

    assert result[0]["description"] == "Sofas"


def test_product_group_used_when_category_cell_is_empty(tmp_path: Path) -> None:
    """When Category column is present but empty, Product Group provides the fallback."""
    header = "Inventory Id,PO #,Model,Category,Product Group,Brand,Tags"
    row = "INV-005,PO-005,MDL-B,,Tables,,"
    p = _write(tmp_path, f"{header}\n{row}\n")
    result = _parse_on_order_csv(p)

    assert result[0]["description"] == "Tables"


def test_description_is_none_when_neither_category_nor_product_group_present(
    tmp_path: Path,
) -> None:
    """When both Category and Product Group are absent from the CSV, description is None."""
    header = "Inventory Id,PO #,Model,Brand,Tags"
    row = "INV-006,PO-006,MDL-C,BrandX,tag1"
    p = _write(tmp_path, f"{header}\n{row}\n")
    result = _parse_on_order_csv(p)

    assert result[0]["description"] is None


# ── Optional fields: None vs empty string ─────────────────────────────────────


def test_empty_brand_cell_produces_none_not_empty_string(tmp_path: Path) -> None:
    """An empty Brand cell maps to None, not ''."""
    p = _write(tmp_path, f"{_CANONICAL_HEADER}\nINV-007,PO-007,MDL-D,Beds,,tag2\n")
    row = _parse_on_order_csv(p)[0]

    assert row["brand"] is None


def test_empty_tags_cell_produces_none_not_empty_string(tmp_path: Path) -> None:
    """An empty Tags cell maps to None, not ''."""
    p = _write(tmp_path, f"{_CANONICAL_HEADER}\nINV-008,PO-008,MDL-E,Desks,BrandY,\n")
    row = _parse_on_order_csv(p)[0]

    assert row["tags"] is None


# ── Row filtering ─────────────────────────────────────────────────────────────


def test_row_with_whitespace_only_inventory_id_is_skipped(tmp_path: Path) -> None:
    """A row whose Inventory Id is only whitespace is treated as absent and skipped."""
    content = (
        f"{_CANONICAL_HEADER}\n"
        "   ,PO-009,MDL-F,Chairs,BrandZ,\n"
        "INV-009,PO-009,MDL-F,Chairs,BrandZ,\n"
    )
    p = _write(tmp_path, content)
    rows = _parse_on_order_csv(p)

    assert len(rows) == 1
    assert rows[0]["inventory_id"] == "INV-009"


def test_inventory_id_value_is_whitespace_stripped(tmp_path: Path) -> None:
    """Leading/trailing whitespace in Inventory Id is stripped from the output."""
    p = _write(tmp_path, f"{_CANONICAL_HEADER}\n  INV-010  ,PO-010,MDL-G,Beds,BrandA,\n")
    row = _parse_on_order_csv(p)[0]

    assert row["inventory_id"] == "INV-010"


def test_purchase_order_value_is_whitespace_stripped(tmp_path: Path) -> None:
    """Leading/trailing whitespace in PO # is stripped."""
    p = _write(tmp_path, f"{_CANONICAL_HEADER}\nINV-011,  PO-011  ,MDL-H,Beds,BrandA,\n")
    row = _parse_on_order_csv(p)[0]

    assert row["purchase_order"] == "PO-011"


# ── Multi-row and structural contracts ────────────────────────────────────────


def test_multiple_rows_all_returned(tmp_path: Path) -> None:
    """All non-empty-inventory-id rows are returned; order is preserved."""
    content = (
        f"{_CANONICAL_HEADER}\n"
        "INV-A,PO-A,MDL-1,Cat1,Br1,t1\n"
        "INV-B,PO-B,MDL-2,Cat2,Br2,t2\n"
        "INV-C,PO-C,MDL-3,Cat3,Br3,t3\n"
    )
    p = _write(tmp_path, content)
    rows = _parse_on_order_csv(p)

    assert len(rows) == 3
    assert [r["inventory_id"] for r in rows] == ["INV-A", "INV-B", "INV-C"]


def test_header_only_csv_returns_empty_list(tmp_path: Path) -> None:
    """A CSV with only a header row and no data rows returns []."""
    p = _write(tmp_path, f"{_CANONICAL_HEADER}\n")
    rows = _parse_on_order_csv(p)

    assert rows == []


def test_extra_unknown_columns_are_silently_ignored(tmp_path: Path) -> None:
    """Columns not in the expected set do not cause an error."""
    header = f"{_CANONICAL_HEADER},UnknownColumn,AnotherExtra"
    row = "INV-012,PO-012,MDL-I,Chairs,BrandQ,t5,extra1,extra2"
    p = _write(tmp_path, f"{header}\n{row}\n")
    rows = _parse_on_order_csv(p)

    assert len(rows) == 1
    assert "UnknownColumn" not in rows[0]
    assert rows[0]["inventory_id"] == "INV-012"


def test_utf8_bom_prefixed_csv_parses_first_column_correctly(tmp_path: Path) -> None:
    """A file with a UTF-8 BOM does not corrupt the first column header.

    Some spreadsheet tools export UTF-8 CSVs with a leading BOM (EF BB BF).
    The parser opens with encoding='utf-8-sig', which strips the BOM automatically.
    """
    p = tmp_path / "bom.csv"
    # Write raw BOM bytes followed by UTF-8 content — simulates an Excel-exported CSV.
    p.write_bytes(b"\xef\xbb\xbf" + f"{_CANONICAL_HEADER}\n{_CANONICAL_ROW}\n".encode())
    rows = _parse_on_order_csv(p)

    assert len(rows) == 1
    assert rows[0]["inventory_id"] == "INV-001"


# ── Fail-closed: OS / parse errors ────────────────────────────────────────────


def test_missing_file_raises_source_error_with_cause(tmp_path: Path) -> None:
    """A non-existent file raises SourceError (not OSError) with __cause__ set."""
    with pytest.raises(SourceError) as exc_info:
        _parse_on_order_csv(tmp_path / "does_not_exist.csv")
    assert exc_info.value.__cause__ is not None
