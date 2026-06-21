"""
Owns: regression tests for conformance gate_a — banned-name matching and
      real-ID enforcement.
Must not: perform I/O against git; must not import adapters;
          must not call conformance.tracked_files() or write to disk.
May import: pytest, pathlib.Path, conformance (banned_name_hit, _BANNED_REAL_IDS,
            gate_a, FAILURES); monkeypatches conformance.read.

not_measured: full gate_a integration against a real git tree.
"""

from pathlib import Path

import conformance
import pytest
from conformance import _BANNED_REAL_IDS, FAILURES, banned_name_hit, gate_a

# ── fixture ───────────────────────────────────────────────────────────────────


@pytest.fixture
def clean_failures():
    """Clear the conformance FAILURES list before and after each test."""
    FAILURES.clear()
    yield FAILURES
    FAILURES.clear()


# ── exact-case hits ───────────────────────────────────────────────────────────


def test_client_name_in_content_exact():
    assert banned_name_hit("Bas" + "co", "client is Bas" + "co appliances", "some/file.py")


def test_source_vendor_name_in_path_exact():
    assert banned_name_hit("Home" + "Source", "", "adapters/home" + "source.py")


# ── case-insensitive hits (the regression) ───────────────────────────────────


def test_sink_vendor_name_lowercase_in_path():
    """Lowercase vendor filename must be caught case-insensitively."""
    assert banned_name_hit("Mon" + "day", "", "adapters/" + "mon" + "day.py")


def test_source_vendor_name_lowercase_in_content():
    """Lowercase vendor word in file body must be caught case-insensitively."""
    assert banned_name_hit(
        "Home" + "Source", "scrapes home" + "source portal", "adapters/source.py"
    )


def test_sink_vendor_name_uppercase_in_path():
    assert banned_name_hit("Mon" + "day", "", "adapters/MON" + "DAY.py")


def test_client_name_mixed_case_in_content():
    assert banned_name_hit("Bas" + "co", "BAS" + "CO Appliances", "config.py")


# ── true-negatives (clean content must not be flagged) ───────────────────────


def test_clean_file_not_flagged():
    assert not banned_name_hit("Mon" + "day", "result sink adapter", "adapters/sink.py")


def test_clean_path_not_flagged():
    assert not banned_name_hit("Home" + "Source", "purchase order source", "adapters/source.py")


# ── _BANNED_REAL_IDS membership ──────────────────────────────────────────────


def test_column_id_fragment_is_in_banned_list():
    assert ("mm" + "3y") in _BANNED_REAL_IDS


def test_board_numeric_id_fragment_is_in_banned_list():
    assert ("184160" + "41666") in _BANNED_REAL_IDS


# ── gate_a integration: real-ID enforcement ───────────────────────────────────


def test_gate_a_flags_column_hash_fragment_in_content(monkeypatch, clean_failures):
    """gate_a records a failure when file content contains the column hash fragment."""
    monkeypatch.setattr(conformance, "read", lambda _path: "col_" + "mm" + "3y" + "se8h")
    gate_a([Path("dummy.py")])
    assert clean_failures, "Expected gate_a to flag the column hash fragment"
    assert any("real board ID fragment" in msg for msg in clean_failures)


def test_gate_a_clean_content_no_column_hash_failure(monkeypatch, clean_failures):
    """gate_a records no failure when content contains no real-ID fragment."""
    monkeypatch.setattr(conformance, "read", lambda _path: "result sink adapter, no ids here")
    gate_a([Path("clean.py")])
    assert not clean_failures


def test_gate_a_flags_numeric_board_id_in_content(monkeypatch, clean_failures):
    """gate_a records a failure when file content contains the numeric board ID."""
    monkeypatch.setattr(conformance, "read", lambda _path: "board_id = " + "184160" + "41666")
    gate_a([Path("dummy.py")])
    assert clean_failures, "Expected gate_a to flag the numeric board ID fragment"
    assert any("real board ID fragment" in msg for msg in clean_failures)


def test_gate_a_clean_content_no_numeric_id_failure(monkeypatch, clean_failures):
    """gate_a records no failure when content contains no numeric board ID."""
    monkeypatch.setattr(conformance, "read", lambda _path: "board_id = 99999999999")
    gate_a([Path("clean.py")])
    assert not clean_failures
