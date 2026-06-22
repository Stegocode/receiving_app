"""
Owns: integration tests for the SQLite Repository adapter (adapters.db).
Must not: import adapters.sink or adapters.source.
May import: pytest, adapters.db, core.schema, core.errors, sqlite3, pathlib.

not_measured: Postgres behaviour, concurrent writes, very large datasets,
              WAL-mode crash recovery.
"""

import sqlite3

import pytest

import adapters.db
from adapters.db import SQLiteRepository
from core.errors import RepositoryError
from core.schema import ReceivingRecord


def _repo(tmp_path) -> SQLiteRepository:
    return SQLiteRepository(db_path=tmp_path / "test.db")


def _record(**kwargs) -> ReceivingRecord:
    defaults: dict = {
        "receiving_id": "REC-001",
        "purchase_order": "PO-001",
        "inventory_id": "INV-001",
        "model_number": "MDL-001",
        "product_category": "Furniture",
        "truck": "T1",
        "stop": "S1",
        "sales_order": "SO-001",
        "product_size": {"w": 30.0, "d": 20.0, "h": 10.0},
        "quantity": 1,
        "match_status": "received",
        "timestamp": "2026-06-19T10:00:00+00:00",
    }
    defaults.update(kwargs)
    return ReceivingRecord(**defaults)


def _item(**kwargs) -> dict:
    defaults: dict = {
        "inventory_id": "INV-001",
        "purchase_order": "PO-001",
        "model_number": "MDL-001",
        "description": None,
        "brand": None,
        "vendor": None,
        "tags": None,
    }
    defaults.update(kwargs)
    return defaults


# ── Migration runner ──────────────────────────────────────────────────────────


def test_migration_runner_fresh_db_sets_user_version_1(tmp_path):
    db_path = tmp_path / "test.db"
    SQLiteRepository(db_path=db_path)
    with sqlite3.connect(db_path) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert version == 1


def test_migration_runner_idempotent(tmp_path):
    db_path = tmp_path / "test.db"
    SQLiteRepository(db_path=db_path)
    SQLiteRepository(db_path=db_path)  # second construction — no-op
    with sqlite3.connect(db_path) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert version == 1


def test_migration_runner_applies_0002_fixture(tmp_path, monkeypatch):
    """With a temp schema dir containing 0001 + 0002, both are applied in order."""
    schema_dir = tmp_path / "schema"
    schema_dir.mkdir()
    (schema_dir / "0001_init.sql").write_text(
        "CREATE TABLE IF NOT EXISTS notes (id TEXT PRIMARY KEY, body TEXT);\n",
        encoding="utf-8",
    )
    (schema_dir / "0002_add_flag.sql").write_text(
        "ALTER TABLE notes ADD COLUMN flagged INTEGER NOT NULL DEFAULT 0;\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(adapters.db, "_SCHEMA_DIR", schema_dir)

    db_path = tmp_path / "test.db"
    SQLiteRepository(db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        cols = [row[1] for row in conn.execute("PRAGMA table_info(notes)").fetchall()]
    assert version == 2
    assert "flagged" in cols


def test_migration_runner_existing_v1_applies_0002_without_touching_rows(tmp_path, monkeypatch):
    """DB at version 1 with rows — adding 0002 applies the migration without losing rows."""
    schema_dir = tmp_path / "schema"
    schema_dir.mkdir()
    (schema_dir / "0001_init.sql").write_text(
        "CREATE TABLE IF NOT EXISTS notes (id TEXT PRIMARY KEY, body TEXT);\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(adapters.db, "_SCHEMA_DIR", schema_dir)

    db_path = tmp_path / "test.db"
    SQLiteRepository(db_path=db_path)  # applies 0001, user_version=1

    with sqlite3.connect(db_path) as conn:
        conn.execute("INSERT INTO notes (id, body) VALUES ('n1', 'hello')")

    # Add 0002 after the initial setup
    (schema_dir / "0002_add_flag.sql").write_text(
        "ALTER TABLE notes ADD COLUMN flagged INTEGER NOT NULL DEFAULT 0;\n",
        encoding="utf-8",
    )
    SQLiteRepository(db_path=db_path)  # should apply only 0002

    with sqlite3.connect(db_path) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        rows = conn.execute("SELECT id, body, flagged FROM notes").fetchall()
    assert version == 2
    assert len(rows) == 1
    assert rows[0][0] == "n1"
    assert rows[0][1] == "hello"
    assert rows[0][2] == 0  # new column default; existing row untouched


# ── Existing schema / CRUD tests ──────────────────────────────────────────────


def test_ensure_schema_idempotent(tmp_path):
    repo = _repo(tmp_path)
    repo._ensure_schema()  # second call — must not raise


def test_upsert_items_twice_produces_one_row(tmp_path):
    repo = _repo(tmp_path)
    repo.upsert_items([_item()])
    repo.upsert_items([_item()])
    rows = repo.get_purchase_order("PO-001")
    assert len(rows) == 1


def test_save_record_then_get_pending(tmp_path):
    repo = _repo(tmp_path)
    repo.save_record(_record())
    pending = repo.get_pending()
    assert len(pending) == 1
    assert pending[0]["receiving_id"] == "REC-001"
    assert pending[0]["emitted"] == 0


def test_was_emitted_false_then_true(tmp_path):
    repo = _repo(tmp_path)
    repo.save_record(_record())
    assert repo.was_emitted("REC-001") is False
    repo.mark_emitted("REC-001")
    assert repo.was_emitted("REC-001") is True


def test_mark_emitted_missing_raises(tmp_path):
    repo = _repo(tmp_path)
    with pytest.raises(RepositoryError):
        repo.mark_emitted("DOES-NOT-EXIST")


def test_save_record_twice_produces_one_row(tmp_path):
    repo = _repo(tmp_path)
    repo.save_record(_record())
    repo.save_record(_record())
    pending = repo.get_pending()
    assert len(pending) == 1


def test_save_record_after_emit_preserves_emitted(tmp_path):
    # save → emit → re-save: still one row AND was_emitted still True
    repo = _repo(tmp_path)
    repo.save_record(_record())
    repo.mark_emitted("REC-001")
    assert repo.was_emitted("REC-001") is True
    repo.save_record(_record())
    assert len(repo.get_pending()) == 0
    assert repo.was_emitted("REC-001") is True


def test_timestamp_round_trips(tmp_path):
    ts = "2026-06-19T10:00:00+00:00"
    repo = _repo(tmp_path)
    repo.save_record(_record(timestamp=ts))
    pending = repo.get_pending()
    assert pending[0]["timestamp"] == ts
