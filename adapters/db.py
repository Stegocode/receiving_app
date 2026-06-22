"""
Owns: SQLite implementation of the Repository port.
Must not: import services or other adapters.
May import: core.ports, core.schema, core.errors, sqlite3, config, json, logging, pathlib, re.
"""
# Owns: SQLite implementation of the Repository port.
# Must not: import services or other adapters.
# May import: core.ports, core.schema, core.errors, sqlite3, config, json, logging, pathlib, re.

from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import config
from core.errors import RepositoryError
from core.schema import ReceivingRecord

_log = logging.getLogger(__name__)
_SCHEMA_DIR = Path(__file__).parent.parent / "schema"
_MIGRATION_RE = re.compile(r"^(\d{4})_")


def _pending_migrations(schema_dir: Path, current_version: int) -> list[tuple[int, Path]]:
    """Return (version, path) pairs for every migration not yet applied, in ascending order."""
    pending = []
    for path in schema_dir.glob("*.sql"):
        m = _MIGRATION_RE.match(path.name)
        if m:
            ver = int(m.group(1))
            if ver > current_version:
                pending.append((ver, path))
    return sorted(pending)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class SQLiteRepository:
    """SQLite-backed Repository. Portable to Postgres via ON CONFLICT DO UPDATE."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path: Path = db_path if db_path is not None else config.DB_PATH
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        """Apply all unapplied migrations in schema/ in ascending order.

        Uses PRAGMA user_version as the applied-version marker.  Each migration
        runs inside a single BEGIN/COMMIT block so the version bump is atomic
        with the schema change.  Idempotent: a second call applies nothing when
        user_version already equals the highest available migration.
        """
        try:
            conn = sqlite3.connect(self._db_path)
            try:
                current_version: int = conn.execute("PRAGMA user_version").fetchone()[0]
            finally:
                conn.close()
            for ver, path in _pending_migrations(_SCHEMA_DIR, current_version):
                migration_sql = path.read_text(encoding="utf-8")
                ver_pragma = "PRAGMA user_version = " + str(ver) + ";"
                script = "BEGIN;\n" + migration_sql + "\n" + ver_pragma + "\nCOMMIT;"
                conn = sqlite3.connect(self._db_path)
                try:
                    conn.executescript(script)
                finally:
                    conn.close()
                _log.info("db_migration_applied version=%d path=%s", ver, path.name)
        except sqlite3.Error as exc:
            raise RepositoryError(f"Schema setup failed — {exc}") from exc

    def get_purchase_order(self, po_number: str) -> list[dict]:
        try:
            with self._connect() as conn:
                cur = conn.execute(
                    "SELECT * FROM po_inventory WHERE purchase_order = ?",
                    (po_number,),
                )
                return [dict(row) for row in cur.fetchall()]
        except sqlite3.Error as exc:
            raise RepositoryError(f"get_purchase_order failed — {exc}") from exc

    def upsert_items(self, items: list[dict]) -> None:
        try:
            with self._connect() as conn:
                for item in items:
                    conn.execute(
                        """
                        INSERT INTO po_inventory
                            (inventory_id, purchase_order, model_number,
                             description, brand, vendor, tags, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(inventory_id) DO UPDATE SET
                            purchase_order = excluded.purchase_order,
                            model_number   = excluded.model_number,
                            description    = excluded.description,
                            brand          = excluded.brand,
                            vendor         = excluded.vendor,
                            tags           = excluded.tags
                        """,
                        (
                            item["inventory_id"],
                            item["purchase_order"],
                            item["model_number"],
                            item.get("description"),
                            item.get("brand"),
                            item.get("vendor"),
                            item.get("tags"),
                            item.get("created_at", _now_iso()),
                        ),
                    )
            _log.info("db_upsert count=%d", len(items))
        except sqlite3.Error as exc:
            raise RepositoryError(f"upsert_items failed — {exc}") from exc

    def save_record(self, record: ReceivingRecord) -> None:
        """Insert or update a receiving record.

        On conflict (same receiving_id): updates domain columns and updated_at,
        but never touches emitted or created_at — a re-save cannot un-emit a record.
        """
        try:
            now = _now_iso()
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO receiving_items
                        (receiving_id, purchase_order, inventory_id, model_number,
                         product_category, truck, stop, sales_order, product_size,
                         quantity, match_status, timestamp, emitted, created_at,
                         updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, NULL)
                    ON CONFLICT(receiving_id) DO UPDATE SET
                        purchase_order   = excluded.purchase_order,
                        inventory_id     = excluded.inventory_id,
                        model_number     = excluded.model_number,
                        product_category = excluded.product_category,
                        truck            = excluded.truck,
                        stop             = excluded.stop,
                        sales_order      = excluded.sales_order,
                        product_size     = excluded.product_size,
                        quantity         = excluded.quantity,
                        match_status     = excluded.match_status,
                        timestamp        = excluded.timestamp,
                        updated_at       = ?
                    """,
                    (
                        record.receiving_id,
                        record.purchase_order,
                        record.inventory_id,
                        record.model_number,
                        record.product_category,
                        record.truck,
                        record.stop,
                        record.sales_order,
                        json.dumps(record.product_size),
                        record.quantity,
                        record.match_status,
                        record.timestamp,
                        now,  # created_at (new rows only)
                        now,  # updated_at in DO UPDATE
                    ),
                )
            _log.info("db_save_record receiving_id=%s", record.receiving_id)
        except sqlite3.Error as exc:
            raise RepositoryError(f"save_record failed — {exc}") from exc

    def get_pending(self) -> list[dict]:
        try:
            with self._connect() as conn:
                cur = conn.execute("SELECT * FROM receiving_items WHERE emitted = 0")
                rows = []
                for row in cur.fetchall():
                    d = dict(row)
                    if d.get("product_size"):
                        d["product_size"] = json.loads(d["product_size"])
                    rows.append(d)
                return rows
        except sqlite3.Error as exc:
            raise RepositoryError(f"get_pending failed — {exc}") from exc

    def mark_emitted(self, receiving_id: str) -> None:
        try:
            with self._connect() as conn:
                cur = conn.execute(
                    "UPDATE receiving_items SET emitted = 1, updated_at = ? WHERE receiving_id = ?",
                    (_now_iso(), receiving_id),
                )
                if cur.rowcount == 0:
                    raise RepositoryError(
                        f"mark_emitted failed — receiving_id '{receiving_id}' not found;"
                        " commit the record before marking it emitted"
                    )
        except sqlite3.Error as exc:
            raise RepositoryError(f"mark_emitted failed — {exc}") from exc

    def was_emitted(self, receiving_id: str) -> bool:
        try:
            with self._connect() as conn:
                cur = conn.execute(
                    "SELECT emitted FROM receiving_items WHERE receiving_id = ?",
                    (receiving_id,),
                )
                row = cur.fetchone()
                return bool(row["emitted"]) if row else False
        except sqlite3.Error as exc:
            raise RepositoryError(f"was_emitted failed — {exc}") from exc

    def clear_po_items(self) -> None:
        try:
            with self._connect() as conn:
                conn.execute("DELETE FROM po_inventory")
        except sqlite3.Error as exc:
            raise RepositoryError(f"clear_po_items failed — {exc}") from exc

    def replace_po_items(self, items: list[dict]) -> None:
        """Wipe po_inventory and reload atomically — no window where catalog is empty."""
        try:
            with self._connect() as conn:
                conn.execute("DELETE FROM po_inventory")
                for item in items:
                    conn.execute(
                        """
                        INSERT INTO po_inventory
                            (inventory_id, purchase_order, model_number,
                             description, brand, vendor, tags, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(inventory_id) DO UPDATE SET
                            purchase_order = excluded.purchase_order,
                            model_number   = excluded.model_number,
                            description    = excluded.description,
                            brand          = excluded.brand,
                            vendor         = excluded.vendor,
                            tags           = excluded.tags
                        """,
                        (
                            item["inventory_id"],
                            item["purchase_order"],
                            item["model_number"],
                            item.get("description"),
                            item.get("brand"),
                            item.get("vendor"),
                            item.get("tags"),
                            item.get("created_at", _now_iso()),
                        ),
                    )
            _log.info("db_replace_po_items count=%d", len(items))
        except sqlite3.Error as exc:
            raise RepositoryError(f"replace_po_items failed — {exc}") from exc

    def count_po_items(self) -> int:
        try:
            with self._connect() as conn:
                cur = conn.execute("SELECT COUNT(*) FROM po_inventory")
                row = cur.fetchone()
                return int(row[0]) if row else 0
        except sqlite3.Error as exc:
            raise RepositoryError(f"count_po_items failed — {exc}") from exc
