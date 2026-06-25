"""
Owns: integration tests for SyncStatusSQLiteStore (adapters.sync_status_db).
Must not: import adapters.sink, adapters.source, or services.
May import: pytest, adapters.db, adapters.sync_status_db, core.schema, core.errors,
            sqlite3, pathlib.

not_measured: Postgres behaviour, concurrent writes, WAL-mode crash recovery.
"""

from __future__ import annotations

import sqlite3

from adapters.db import SQLiteRepository
from adapters.sync_status_db import SyncStatusSQLiteStore
from core.schema import SyncStatusRecord


def test_sync_status_migration_idempotent(tmp_path):
    """Creating SyncStatusSQLiteStore twice on the same DB is a no-op (idempotent).

    Verifies CREATE TABLE IF NOT EXISTS — running the schema twice must not raise.
    """
    db_path = tmp_path / "sync.db"
    SyncStatusSQLiteStore(db_path=db_path)
    SyncStatusSQLiteStore(db_path=db_path)  # second construction — no-op
    with sqlite3.connect(db_path) as conn:
        cols = [row[1] for row in conn.execute("PRAGMA table_info(sync_status)").fetchall()]
    assert "id" in cols
    assert "state" in cols
    assert "consecutive_failures" in cols


def test_sync_status_write_and_read(tmp_path):
    """write_sync_status upserts id=1; read_sync_status returns it."""
    store = SyncStatusSQLiteStore(db_path=tmp_path / "sync.db")
    record = SyncStatusRecord(
        state="running",
        last_outcome="none",
        consecutive_failures=0,
        stopped_reason="",
        updated_at="2026-06-24T10:00:00+00:00",
    )

    store.write_sync_status(record)
    result = store.read_sync_status()

    assert result is not None
    assert result.state == "running"
    assert result.last_outcome == "none"
    assert result.consecutive_failures == 0
    assert result.stopped_reason == ""


def test_sync_status_upsert_updates_existing_row(tmp_path):
    """Calling write_sync_status twice on id=1 updates rather than duplicates."""
    store = SyncStatusSQLiteStore(db_path=tmp_path / "sync.db")
    store.write_sync_status(SyncStatusRecord("running", "none", 0, "", "2026-06-24T10:00:00+00:00"))
    store.write_sync_status(
        SyncStatusRecord(
            "stopped", "kill", 2, "2 consecutive failures", "2026-06-24T10:01:00+00:00"
        )
    )

    result = store.read_sync_status()
    assert result is not None
    assert result.state == "stopped"
    assert result.last_outcome == "kill"
    assert result.consecutive_failures == 2

    # Only one row exists in the table (single-row semantics)
    db_path = tmp_path / "sync.db"
    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM sync_status").fetchone()[0]
    assert count == 1


def test_sync_status_read_returns_none_before_any_write(tmp_path):
    """read_sync_status returns None when no record has been written."""
    store = SyncStatusSQLiteStore(db_path=tmp_path / "sync.db")
    assert store.read_sync_status() is None


def test_sync_status_migration_0004_applied_by_sqlite_repository(tmp_path):
    """SQLiteRepository migration 0004 creates sync_status table alongside existing tables.

    Verifies the migration file applies cleanly on a fresh DB — the SyncStatusSQLiteStore
    and SQLiteRepository can share the same DB file without conflict.
    """
    db_path = tmp_path / "shared.db"
    SQLiteRepository(db_path=db_path)  # runs all migrations including 0004
    with sqlite3.connect(db_path) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        cols = [row[1] for row in conn.execute("PRAGMA table_info(sync_status)").fetchall()]
    assert version >= 4
    assert "consecutive_failures" in cols
