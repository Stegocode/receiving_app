"""
Owns: tests for the barcode_model_map persistence store (FakeRepository + SQLiteRepository).
Must not: import services.
May import: pytest, tests.fakes.fake_db, adapters.db, pathlib, sqlite3.

not_measured: concurrent writes, Postgres behaviour, barcode encoding edge cases beyond ASCII.
"""

import sqlite3

import pytest

from adapters.db import SQLiteRepository
from tests.fakes.fake_db import FakeRepository

# ── FakeRepository tests ──────────────────────────────────────────────────────


def test_fake_save_then_lookup_exact_returns_model() -> None:
    repo = FakeRepository()
    repo.save_barcode_mapping("12 WMB 78568GWWBB", "WMB568GWW", 0.87, "confirmed")
    assert repo.lookup_barcode_mapping("12 WMB 78568GWWBB") == "WMB568GWW"


def test_fake_lookup_one_char_different_returns_none() -> None:
    """SAFETY: one character off must not match — exact equality only, no fuzzy."""
    repo = FakeRepository()
    repo.save_barcode_mapping("12 WMB 78568GWWBB", "WMB568GWW", 0.87, "confirmed")
    assert repo.lookup_barcode_mapping("12 WMB 78568GWWBC") is None


def test_fake_upsert_last_write_wins() -> None:
    repo = FakeRepository()
    repo.save_barcode_mapping("12 WMB 78568GWWBB", "WMB568GWW", 0.87, "confirmed")
    repo.save_barcode_mapping("12 WMB 78568GWWBB", "WMB568GWW-B", 0.91, "manual")
    assert repo.lookup_barcode_mapping("12 WMB 78568GWWBB") == "WMB568GWW-B"


def test_fake_fuzzy_score_and_source_round_trip() -> None:
    repo = FakeRepository()
    repo.save_barcode_mapping("RAW-001", "MDL-A", 0.72, "manual")
    entry = repo._barcode_map["RAW-001"]
    assert entry["fuzzy_score"] == pytest.approx(0.72)
    assert entry["source"] == "manual"
    assert entry["confirmed_at"] is not None


def test_fake_lookup_unknown_returns_none() -> None:
    repo = FakeRepository()
    assert repo.lookup_barcode_mapping("NEVER-STORED") is None


# ── SQLiteRepository tests ────────────────────────────────────────────────────


def _repo(tmp_path) -> SQLiteRepository:  # type: ignore[no-untyped-def]
    return SQLiteRepository(db_path=tmp_path / "test.db")


def test_sqlite_save_then_lookup_exact_returns_model(tmp_path) -> None:
    repo = _repo(tmp_path)
    repo.save_barcode_mapping("12 WMB 78568GWWBB", "WMB568GWW", 0.87, "confirmed")
    assert repo.lookup_barcode_mapping("12 WMB 78568GWWBB") == "WMB568GWW"


def test_sqlite_lookup_one_char_different_returns_none(tmp_path) -> None:
    """SAFETY: one character difference must return None — exact string equality only."""
    repo = _repo(tmp_path)
    repo.save_barcode_mapping("12 WMB 78568GWWBB", "WMB568GWW", 0.87, "confirmed")
    assert repo.lookup_barcode_mapping("12 WMB 78568GWWBC") is None


def test_sqlite_upsert_last_write_wins(tmp_path) -> None:
    repo = _repo(tmp_path)
    repo.save_barcode_mapping("12 WMB 78568GWWBB", "WMB568GWW", 0.87, "confirmed")
    repo.save_barcode_mapping("12 WMB 78568GWWBB", "WMB568GWW-B", 0.91, "manual")
    assert repo.lookup_barcode_mapping("12 WMB 78568GWWBB") == "WMB568GWW-B"


def test_sqlite_upsert_no_duplicate_rows(tmp_path) -> None:
    """Upserting the same raw_barcode twice yields exactly one row, not two."""
    repo = _repo(tmp_path)
    repo.save_barcode_mapping("RAW-DUP", "MDL-X", 0.80, "confirmed")
    repo.save_barcode_mapping("RAW-DUP", "MDL-X", 0.85, "confirmed")
    with sqlite3.connect(tmp_path / "test.db") as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM barcode_model_map WHERE raw_barcode = 'RAW-DUP'"
        ).fetchone()[0]
    assert count == 1


def test_sqlite_fuzzy_score_and_source_round_trip(tmp_path) -> None:
    repo = _repo(tmp_path)
    repo.save_barcode_mapping("RAW-001", "MDL-A", 0.72, "manual")
    with sqlite3.connect(tmp_path / "test.db") as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT fuzzy_score, source, confirmed_at FROM barcode_model_map"
            " WHERE raw_barcode = 'RAW-001'"
        ).fetchone()
    assert row["fuzzy_score"] == pytest.approx(0.72)
    assert row["source"] == "manual"
    assert row["confirmed_at"] is not None


def test_sqlite_lookup_unknown_returns_none(tmp_path) -> None:
    repo = _repo(tmp_path)
    assert repo.lookup_barcode_mapping("NEVER-STORED") is None


def test_sqlite_migration_idempotent(tmp_path) -> None:
    """Two constructions on the same DB path must not raise."""
    _repo(tmp_path)
    _repo(tmp_path)


def test_sqlite_barcode_map_table_columns_present(tmp_path) -> None:
    """Migration 0003 creates barcode_model_map with all required columns."""
    db_path = tmp_path / "test.db"
    SQLiteRepository(db_path=db_path)
    with sqlite3.connect(db_path) as conn:
        cols = [row[1] for row in conn.execute("PRAGMA table_info(barcode_model_map)").fetchall()]
    for col in ("raw_barcode", "model_number", "fuzzy_score", "confirmed_at", "source"):
        assert col in cols, f"barcode_model_map.{col} missing after migration"
