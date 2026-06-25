"""
Owns: contract tests for _build_zpl and _zpl_safe — pins the ZPL output shape
      that the Zebra printer driver expects. Also covers _build_po_zpl sanitization.
Must not: open a real browser, spool to a real printer, or import adapters.db or services.
May import: pytest, adapters.printer (_build_zpl, _build_po_zpl, _zpl_safe), core.schema.

not_measured: live ZPL rendering on a physical Zebra printer (DEBT-T16.2-001);
              OS printer enumeration; win32print spool behavior; label crop/alignment
              as rendered on label stock; exact DPI mapping. These require a connected
              Zebra device to validate. ZebraPrinter.print_label and print_po_label
              call _build_zpl/_build_po_zpl, so these contracts cover the ZPL content
              produced; the spool path itself is not tested here.
"""

from __future__ import annotations

import pytest

from adapters.printer import _build_po_zpl, _build_zpl, _zpl_safe
from core.schema import ReceivingRecord

# ── Fixture helpers ───────────────────────────────────────────────────────────


def _make_record(**overrides: object) -> ReceivingRecord:
    defaults: dict = {
        "truck": "TRK-1",
        "stop": "S1",
        "sales_order": "SO-001",
        "model_number": "MDL-X",
        "product_category": "Furniture",
        "product_size": {"w": 24.0, "d": 18.0, "h": 36.0},
        "quantity": 1,
        "receiving_id": "rid-zpl-001",
        "timestamp": "2026-06-25T10:00:00",
        "match_status": "received",
        "purchase_order": "PO-2026-001",
        "inventory_id": "INV-001",
        "serial": "SN-12345",
        "brand": "BrandCo",
        "vendor": "",
        "tags": "promo",
    }
    defaults.update(overrides)
    return ReceivingRecord(**defaults)


# ── ZPL envelope ─────────────────────────────────────────────────────────────


def test_build_zpl_starts_with_xA_label_start() -> None:
    """ZPL label must begin with ^XA (Format Start command)."""
    zpl = _build_zpl(_make_record())
    assert zpl.startswith("^XA"), f"Expected ^XA at start, got: {zpl[:20]!r}"


def test_build_zpl_ends_with_xZ_label_end() -> None:
    """ZPL label must end with ^XZ followed by a newline (Format End command)."""
    zpl = _build_zpl(_make_record())
    assert zpl.rstrip("\n").endswith("^XZ"), f"Expected ^XZ at end, got: {zpl[-20:]!r}"


# ── Page dimensions — 4" × 3" at 203 DPI ─────────────────────────────────────


def test_build_zpl_page_width_is_4_inches_at_203_dpi() -> None:
    """^PW812 sets print width to 4 inches (812 dots at 203 DPI)."""
    zpl = _build_zpl(_make_record())
    assert "^PW812" in zpl, 'Missing ^PW812 (4" width at 203 DPI)'


def test_build_zpl_page_length_is_3_inches_at_203_dpi() -> None:
    """^LL609 sets label length to 3 inches (609 dots at 203 DPI)."""
    zpl = _build_zpl(_make_record())
    assert "^LL609" in zpl, 'Missing ^LL609 (3" length at 203 DPI)'


# ── Required field content ────────────────────────────────────────────────────


def test_build_zpl_description_is_model_dash_category() -> None:
    """The first text line is '{model_number} - {product_category}'."""
    zpl = _build_zpl(_make_record(model_number="MODTEST", product_category="CATTEST"))
    assert "MODTEST - CATTEST" in zpl


def test_build_zpl_brand_field_is_present() -> None:
    """Brand field appears as 'Brand: {brand}'."""
    zpl = _build_zpl(_make_record(brand="TestBrand"))
    assert "Brand: TestBrand" in zpl


def test_build_zpl_purchase_order_is_present() -> None:
    """Purchase Order field appears as 'Purchase Order: {po}'."""
    zpl = _build_zpl(_make_record(purchase_order="PO-CONTRACT-01"))
    assert "Purchase Order: PO-CONTRACT-01" in zpl


def test_build_zpl_model_number_field_is_present() -> None:
    """Model field appears as 'Model: {model_number}'."""
    zpl = _build_zpl(_make_record(model_number="MDL-CONTRACT"))
    assert "Model: MDL-CONTRACT" in zpl


def test_build_zpl_serial_field_is_present() -> None:
    """Serial number field appears as 'SN#: {serial}'."""
    zpl = _build_zpl(_make_record(serial="SN-CONTRACT-99"))
    assert "SN#: SN-CONTRACT-99" in zpl


def test_build_zpl_tags_field_is_present() -> None:
    """Tags field appears as 'Tags: {tags}'."""
    zpl = _build_zpl(_make_record(tags="contract-tag"))
    assert "Tags: contract-tag" in zpl


def test_build_zpl_inventory_id_text_field_is_present() -> None:
    """Inventory ID field appears as 'Inventory ID: {inventory_id}'."""
    zpl = _build_zpl(_make_record(inventory_id="INV-CONTRACT-01"))
    assert "Inventory ID: INV-CONTRACT-01" in zpl


# ── Barcode contract ──────────────────────────────────────────────────────────


def test_build_zpl_barcode_wraps_inventory_id_in_guard_chars() -> None:
    """The Code 128 barcode data is '%{inventory_id}%' — the % chars are Code 128 guard bytes.

    If these guard characters change or the inventory_id is omitted, the Zebra
    scanner will not be able to scan the label barcode back into the system.
    """
    zpl = _build_zpl(_make_record(inventory_id="INV-BARCODE-42"))
    assert "%INV-BARCODE-42%" in zpl, (
        "Barcode guard chars missing — expected '%INV-BARCODE-42%' in ZPL"
    )


def test_build_zpl_inventory_id_also_appears_as_large_text_below_barcode() -> None:
    """The inventory_id appears in the large centred text block below the barcode."""
    zpl = _build_zpl(_make_record(inventory_id="INV-LARGE-77"))
    # Guard chars appear in the barcode command; without them this is the large-text occurrence
    occurrences = zpl.count("INV-LARGE-77")
    assert occurrences >= 2, (
        f"Expected inventory_id at least twice (barcode + large text), found {occurrences}"
    )


# ── _zpl_safe: ZPL control-character sanitization ────────────────────────────


def test_zpl_safe_strips_caret_from_field_data() -> None:
    """^ is a ZPL command prefix; it must be removed from field values.

    Leaving ^ in a field value would start an unintended ZPL command mid-label,
    corrupting the print output or silently altering the layout.
    """
    assert _zpl_safe("INV^001") == "INV001"


def test_zpl_safe_strips_tilde_from_field_data() -> None:
    """~ is a ZPL command prefix; it must be removed from field values."""
    assert _zpl_safe("INV~001") == "INV001"


def test_zpl_safe_replaces_ampersand_with_plus() -> None:
    """& is the ZPL newline escape; it is replaced with + to avoid unintended newlines."""
    assert _zpl_safe("Brand & Co") == "Brand + Co"


def test_zpl_safe_leaves_normal_alphanumeric_unchanged() -> None:
    """Normal alphanumeric strings pass through _zpl_safe unchanged."""
    assert _zpl_safe("INV-001") == "INV-001"
    assert _zpl_safe("PO-2026-042") == "PO-2026-042"


def test_zpl_safe_handles_none_as_empty_string() -> None:
    """_zpl_safe(None) returns '' — guards against None field values in records."""
    assert _zpl_safe(None) == ""


# ── Sanitization applied to ZPL output ───────────────────────────────────────


def test_build_zpl_inventory_id_with_caret_is_sanitized_in_barcode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An inventory_id containing ^ has the caret stripped before it appears in ZPL.

    A raw ^ in the barcode ^FD command would start an unintended ZPL sub-command,
    producing an unreadable barcode or label.
    """
    zpl = _build_zpl(_make_record(inventory_id="INV^CARET"))
    assert "INV^CARET" not in zpl, "Raw ^ must not appear in ZPL output"
    assert "INVCARET" in zpl or "%INVCARET%" in zpl


def test_build_zpl_serial_with_tilde_is_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    """A serial containing ~ has the tilde stripped before it appears in ZPL."""
    zpl = _build_zpl(_make_record(serial="SN~TILDE"))
    assert "SN~TILDE" not in zpl, "Raw ~ must not appear in ZPL output"
    assert "SNTILDE" in zpl


# ── _build_po_zpl: sanitization contract (complements test_printer.py) ────────


def test_build_po_zpl_po_number_with_caret_is_sanitized() -> None:
    """A PO number containing ^ has the caret stripped from the ZPL output."""
    zpl = _build_po_zpl("PO^BAD")
    assert "PO^BAD" not in zpl
    assert "POBAD" in zpl


def test_build_po_zpl_barcode_starts_with_po_prefix() -> None:
    """The PO barcode data starts with 'PO:' followed by the (sanitized) PO number."""
    zpl = _build_po_zpl("PO-CONTRACT-99")
    assert "PO:PO-CONTRACT-99" in zpl
