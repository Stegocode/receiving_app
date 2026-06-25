"""
Owns: SQLite implementation of the SyncStatusStore port.
Must not: import services or other adapters.
May import: core.ports, core.schema, core.errors, sqlite3, config, logging, pathlib.

Boundary: single-writer; no concurrent access expected (robot is the sole writer).
"""
# DEBT-T1-4a-002 2026-06-24 — _ensure_schema here duplicates schema/0004_sync_status.sql.
# adapters/db.py is at the 400-line gate limit, preventing the shared migration runner
# from being extended.  Resolve by splitting db.py (DEBT-T15-003 covers the DB-layer
# refactor trigger); unify migration entry-points at that time.

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import config
from core.errors import RepositoryError
from core.schema import SyncStatusRecord

_log = logging.getLogger(__name__)

_CREATE_SYNC_STATUS = """
    CREATE TABLE IF NOT EXISTS sync_status (
        id                    INTEGER PRIMARY KEY DEFAULT 1,
        state                 TEXT NOT NULL,
        last_outcome          TEXT NOT NULL,
        consecutive_failures  INTEGER NOT NULL DEFAULT 0,
        stopped_reason        TEXT NOT NULL DEFAULT '',
        updated_at            TEXT NOT NULL
    );
"""


class SyncStatusSQLiteStore:
    """SQLite-backed SyncStatusStore.  Upserts id=1; single-row semantics."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path: Path = db_path if db_path is not None else config.DB_PATH
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        """Create sync_status table if absent.  Idempotent — CREATE TABLE IF NOT EXISTS."""
        try:
            conn = sqlite3.connect(self._db_path)
            try:
                conn.executescript(_CREATE_SYNC_STATUS)
            finally:
                conn.close()
        except sqlite3.Error as exc:
            raise RepositoryError(f"sync_status schema setup failed — {exc}") from exc

    def write_sync_status(self, record: SyncStatusRecord) -> None:
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO sync_status
                        (id, state, last_outcome, consecutive_failures,
                         stopped_reason, updated_at)
                    VALUES (1, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        state                = excluded.state,
                        last_outcome         = excluded.last_outcome,
                        consecutive_failures = excluded.consecutive_failures,
                        stopped_reason       = excluded.stopped_reason,
                        updated_at           = excluded.updated_at
                    """,
                    (
                        record.state,
                        record.last_outcome,
                        record.consecutive_failures,
                        record.stopped_reason,
                        record.updated_at,
                    ),
                )
            _log.info(
                "db_sync_status state=%s outcome=%s consec_fail=%d",
                record.state,
                record.last_outcome,
                record.consecutive_failures,
            )
        except sqlite3.Error as exc:
            raise RepositoryError(f"write_sync_status failed — {exc}") from exc

    def read_sync_status(self) -> SyncStatusRecord | None:
        try:
            with self._connect() as conn:
                cur = conn.execute("SELECT * FROM sync_status WHERE id = 1")
                row = cur.fetchone()
                if row is None:
                    return None
                d = dict(row)
                return SyncStatusRecord(
                    state=d["state"],
                    last_outcome=d["last_outcome"],
                    consecutive_failures=d["consecutive_failures"],
                    stopped_reason=d["stopped_reason"],
                    updated_at=d["updated_at"],
                )
        except sqlite3.Error as exc:
            raise RepositoryError(f"read_sync_status failed — {exc}") from exc
