"""
Owns: tests for PortalSource adapter, FakePurchaseOrderSource test fake,
      and FakeSource dev adapter.
Must not: launch a real browser, open a network connection, or import adapters.db.
May import: pytest, unittest.mock, contextlib, json, adapters.source,
            tests.fakes.fake_source, core.ports, core.errors.

not_measured: end-to-end scrape against the live portal; CSV column-name drift;
              login-flow changes; filter-checkbox ID changes; download filename
              pattern changes. All require a live portal session to validate.
              See DEBT.md [DEBT-T08-*].
"""

import json
import logging
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from adapters.source import PortalSource, _guard_download_dir, _parse_on_order_csv
from core.errors import SourceError
from core.ports import PurchaseOrderSource
from tests.fakes.fake_source import FakePurchaseOrderSource

# ── Fixture helpers ───────────────────────────────────────────────────────────

_FIXTURE: dict[str, list[dict]] = {
    "PO-001": [
        {
            "inventory_id": "INV-001",
            "purchase_order": "PO-001",
            "model_number": "MDL-A",
            "description": "Chair",
            "brand": "Acme",
            "vendor": None,
            "tags": None,
        }
    ],
    "PO-002": [
        {
            "inventory_id": "INV-002",
            "purchase_order": "PO-002",
            "model_number": "MDL-B",
            "description": None,
            "brand": None,
            "vendor": None,
            "tags": None,
        }
    ],
}


def _src(tmp_path: Path) -> PortalSource:
    return PortalSource(
        base_url="http://mock-portal",
        username="test_user",
        password="test_pass",
        download_dir=tmp_path / "downloads",
    )


def _stub_pipeline(stack: ExitStack, rows: list[dict], tmp_path: Path) -> None:
    """Register all browser-pipeline stubs into an ExitStack."""
    stack.enter_context(patch("adapters.source._build_driver", return_value=MagicMock()))
    stack.enter_context(patch("adapters.source._login"))
    stack.enter_context(patch("adapters.source._apply_on_order_filter"))
    stack.enter_context(patch("adapters.source._trigger_export"))
    stack.enter_context(patch("adapters.source._wait_for_csv", return_value=tmp_path / "fake.csv"))
    stack.enter_context(patch("adapters.source._parse_on_order_csv", return_value=rows))


# ── FakePurchaseOrderSource tests ─────────────────────────────────────────────


def test_fake_satisfies_protocol():
    fake = FakePurchaseOrderSource(_FIXTURE)
    assert isinstance(fake, PurchaseOrderSource)


def test_fake_fetch_order_known():
    fake = FakePurchaseOrderSource(_FIXTURE)
    rows = fake.fetch_order("PO-001")
    assert len(rows) == 1
    assert rows[0]["inventory_id"] == "INV-001"


def test_fake_fetch_order_unknown():
    fake = FakePurchaseOrderSource(_FIXTURE)
    assert fake.fetch_order("PO-UNKNOWN") == []


def test_fake_fetch_all_open_orders():
    fake = FakePurchaseOrderSource(_FIXTURE)
    rows = fake.fetch_all_open_orders()
    assert len(rows) == 2
    ids = {r["inventory_id"] for r in rows}
    assert ids == {"INV-001", "INV-002"}


# ── PortalSource error-wrapping tests ─────────────────────────────────────────


def test_browser_launch_error_is_wrapped_as_source_error(tmp_path: Path):
    """_build_driver raising must surface as SourceError with __cause__ set."""
    src = _src(tmp_path)
    with (
        patch("adapters.source._build_driver", side_effect=RuntimeError("no Chrome binary")),
        pytest.raises(SourceError) as exc_info,
    ):
        src.fetch_all_open_orders()
    assert isinstance(exc_info.value.__cause__, RuntimeError)


def test_login_error_is_wrapped_as_source_error(tmp_path: Path):
    """_login raising must surface as SourceError; driver.quit() called on failure."""
    mock_driver = MagicMock()
    with (
        patch("adapters.source._build_driver", return_value=mock_driver),
        patch("adapters.source._login", side_effect=ConnectionError("timeout")),
        pytest.raises(SourceError) as exc_info,
    ):
        _src(tmp_path).fetch_all_open_orders()
    assert isinstance(exc_info.value.__cause__, ConnectionError)
    mock_driver.quit.assert_called_once()


def test_parse_error_is_wrapped_as_source_error(tmp_path: Path):
    """_parse_on_order_csv raising SourceError must propagate unchanged."""
    mock_driver = MagicMock()
    with (
        patch("adapters.source._build_driver", return_value=mock_driver),
        patch("adapters.source._login"),
        patch("adapters.source._apply_on_order_filter"),
        patch("adapters.source._trigger_export"),
        patch("adapters.source._wait_for_csv", return_value=tmp_path / "f.csv"),
        patch("adapters.source._parse_on_order_csv", side_effect=SourceError("bad csv")),
        pytest.raises(SourceError),
    ):
        _src(tmp_path).fetch_all_open_orders()


def test_credentials_are_injected_not_hardcoded(tmp_path: Path):
    """PortalSource must pass the constructor credentials to _login unchanged."""
    captured: dict = {}

    def capture_login(_driver, _wait, _url, username: str, password: str) -> None:
        captured["username"] = username
        captured["password"] = password
        raise RuntimeError("stop here")  # abort after capture

    mock_driver = MagicMock()
    src = PortalSource(
        base_url="http://mock",
        username="injected_user",
        password="injected_pass",
        download_dir=tmp_path / "dl",
    )
    with (
        patch("adapters.source._build_driver", return_value=mock_driver),
        patch("adapters.source._login", side_effect=capture_login),
        pytest.raises(SourceError),
    ):
        src.fetch_all_open_orders()

    assert captured.get("username") == "injected_user"
    assert captured.get("password") == "injected_pass"


def test_fetch_all_emits_start_and_complete_log_events(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    """fetch_all_open_orders must emit start and complete log records."""
    rows = [{"inventory_id": "INV-X", "purchase_order": "PO-X", "model_number": "M"}]

    with ExitStack() as stack:
        _stub_pipeline(stack, rows, tmp_path)
        stack.enter_context(caplog.at_level(logging.INFO, logger="adapters.source"))
        result = _src(tmp_path).fetch_all_open_orders()

    assert result == rows
    messages = [r.getMessage() for r in caplog.records]
    assert any("start" in m for m in messages)
    assert any("complete" in m for m in messages)


def test_fetch_order_filters_by_po_number(tmp_path: Path):
    """fetch_order must return only rows for the requested PO."""
    all_rows = [
        {"purchase_order": "PO-001", "inventory_id": "A"},
        {"purchase_order": "PO-002", "inventory_id": "B"},
    ]

    with ExitStack() as stack:
        _stub_pipeline(stack, all_rows, tmp_path)
        result = _src(tmp_path).fetch_order("PO-001")

    assert len(result) == 1
    assert result[0]["inventory_id"] == "A"


def test_fetch_order_emits_start_and_complete_log_events(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    rows = [{"purchase_order": "PO-001", "inventory_id": "INV-1", "model_number": "M"}]

    with ExitStack() as stack:
        _stub_pipeline(stack, rows, tmp_path)
        stack.enter_context(caplog.at_level(logging.INFO, logger="adapters.source"))
        _src(tmp_path).fetch_order("PO-001")

    messages = [r.getMessage() for r in caplog.records]
    assert any("start" in m for m in messages)
    assert any("complete" in m for m in messages)


# ── _parse_on_order_csv unit tests (no browser) ───────────────────────────────


def test_parse_csv_skips_rows_without_inventory_id(tmp_path: Path):
    csv_content = (
        "Inventory Id,PO #,Model,Category,Brand,Tags\n,PO-001,M1,Cat,,\nINV-1,PO-001,M2,Cat,,\n"
    )
    p = tmp_path / "test.csv"
    p.write_text(csv_content, encoding="utf-8-sig")
    rows = _parse_on_order_csv(p)
    assert len(rows) == 1
    assert rows[0]["inventory_id"] == "INV-1"


def test_parse_csv_uses_product_group_fallback(tmp_path: Path):
    csv_content = (
        "Inventory Id,PO #,Model,Category,Product Group,Brand,Tags\nINV-2,PO-1,M,,Sofas,,\n"
    )
    p = tmp_path / "test.csv"
    p.write_text(csv_content, encoding="utf-8-sig")
    rows = _parse_on_order_csv(p)
    assert rows[0]["description"] == "Sofas"


def test_parse_csv_missing_file_raises_source_error(tmp_path: Path):
    with pytest.raises(SourceError) as exc_info:
        _parse_on_order_csv(tmp_path / "missing.csv")
    assert exc_info.value.__cause__ is not None


def test_parse_csv_returns_correct_field_names(tmp_path: Path):
    csv_content = "Inventory Id,PO #,Model,Category,Brand,Tags\nINV-9,PO-9,MDL-9,Beds,Brand9,t1\n"
    p = tmp_path / "test.csv"
    p.write_text(csv_content, encoding="utf-8-sig")
    rows = _parse_on_order_csv(p)
    assert rows[0]["inventory_id"] == "INV-9"
    assert rows[0]["purchase_order"] == "PO-9"
    assert rows[0]["model_number"] == "MDL-9"
    assert rows[0]["description"] == "Beds"
    assert rows[0]["brand"] == "Brand9"
    assert rows[0]["vendor"] is None
    assert rows[0]["tags"] == "t1"


# ── FakeSource (dev-mode adapter) tests ───────────────────────────────────────

_FAKE_ROWS = [
    {
        "inventory_id": "INVT-001",
        "purchase_order": "10001",
        "model_number": "NT-2000A",
        "description": "Executive Desk",
        "brand": "Novatech",
        "vendor": None,
        "tags": None,
        "truck": "TRK-01",
        "stop": "01",
        "sales_order": "SO-50001",
        "product_category": "Desks",
        "product_size": {"w": 60, "d": 30, "h": 30},
        "quantity": 1,
    },
    {
        "inventory_id": "INVT-002",
        "purchase_order": "10002",
        "model_number": "CF-450",
        "description": "Guest Chair",
        "brand": "Crestfield",
        "vendor": None,
        "tags": None,
        "truck": "TRK-02",
        "stop": "01",
        "sales_order": "SO-50002",
        "product_category": "Seating",
        "product_size": {"w": 24, "d": 22, "h": 38},
        "quantity": 4,
    },
]


def test_fake_source_fetch_order_returns_matching_rows(tmp_path: Path):
    """FakeSource.fetch_order returns rows for the requested PO only."""
    from adapters.source import FakeSource

    fixture = tmp_path / "pos.json"
    fixture.write_text(json.dumps(_FAKE_ROWS), encoding="utf-8")
    src = FakeSource(fixture)
    rows = src.fetch_order("10001")
    assert len(rows) == 1
    assert rows[0]["inventory_id"] == "INVT-001"
    assert rows[0]["model_number"] == "NT-2000A"


def test_fake_source_field_mapping_includes_full_line_item_set(tmp_path: Path):
    """FakeSource rows include the full line-item field set consumed by process_scan."""
    from adapters.source import FakeSource

    fixture = tmp_path / "pos.json"
    fixture.write_text(json.dumps(_FAKE_ROWS), encoding="utf-8")
    src = FakeSource(fixture)
    rows = src.fetch_order("10001")
    row = rows[0]
    assert row["truck"] == "TRK-01"
    assert row["sales_order"] == "SO-50001"
    assert row["product_category"] == "Desks"
    assert row["product_size"] == {"w": 60, "d": 30, "h": 30}
    assert row["quantity"] == 1


def test_fake_source_fetch_all_returns_all_rows(tmp_path: Path):
    """FakeSource.fetch_all_open_orders returns every row across all POs."""
    from adapters.source import FakeSource

    fixture = tmp_path / "pos.json"
    fixture.write_text(json.dumps(_FAKE_ROWS), encoding="utf-8")
    src = FakeSource(fixture)
    rows = src.fetch_all_open_orders()
    assert len(rows) == 2
    ids = {r["inventory_id"] for r in rows}
    assert ids == {"INVT-001", "INVT-002"}


def test_fake_source_missing_file_raises_source_error(tmp_path: Path):
    """FakeSource raises SourceError (with cause) when the JSON file is absent."""
    from adapters.source import FakeSource

    src = FakeSource(tmp_path / "nonexistent.json")
    with pytest.raises(SourceError) as exc_info:
        src.fetch_order("10001")
    assert exc_info.value.__cause__ is not None


# ── Download-dir safety guard ─────────────────────────────────────────────────


@pytest.mark.parametrize("unsafe", [Path.home(), Path("/")])
def test_guard_rejects_unsafe_paths(unsafe: Path):
    """_guard_download_dir raises SourceError for home dir and filesystem root."""
    with pytest.raises(SourceError, match="safety check"):
        _guard_download_dir(unsafe.resolve())


def test_guard_accepts_normal_subdir(tmp_path: Path):
    """_guard_download_dir does not raise for a normal tmp_path subdirectory."""
    _guard_download_dir((tmp_path / "downloads").resolve())


def test_unsafe_download_dir_raises_before_browser_launch():
    """PortalSource raises SourceError for unsafe DOWNLOAD_DIR before touching the browser."""
    src = PortalSource("http://x", "u", "p", Path.home())
    with (
        patch("adapters.source._build_driver") as mock_driver,
        pytest.raises(SourceError, match="safety check"),
    ):
        src.fetch_all_open_orders()
    mock_driver.assert_not_called()


def test_cleanup_scopes_delete_to_export_files(tmp_path: Path):
    """Pattern-scoped cleanup: .csv and .crdownload deleted; unrelated .txt survives."""
    dl = tmp_path / "downloads"
    dl.mkdir()
    csv1 = dl / "serial-number-inventory.csv"
    csv2 = dl / "stale.csv"
    crdown = dl / "partial.crdownload"
    unrelated = dl / "important.txt"
    for f, content in [(csv1, "a"), (csv2, "b"), (crdown, "c"), (unrelated, "keep")]:
        f.write_text(content)

    with ExitStack() as stack:
        _stub_pipeline(stack, [], tmp_path)
        PortalSource("http://x", "u", "p", dl).fetch_all_open_orders()

    assert not csv1.exists(), ".csv should be deleted"
    assert not csv2.exists(), "stale .csv should be deleted"
    assert not crdown.exists(), ".crdownload should be deleted"
    assert unrelated.exists(), "unrelated .txt must survive"
