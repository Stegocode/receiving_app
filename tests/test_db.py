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


def test_migration_runner_fresh_db_reaches_version_4_with_all_columns(tmp_path):
    """Fresh DB applies 0001–0004 migrations; user_version==4.

    Schema/0002 columns (po_inventory.claimed_at, receiving_items.serial),
    schema/0003 table (barcode_model_map), and schema/0004 table (sync_status)
    must all be present — kills any mutation that drops a migration file or one
    of the ALTER TABLE / CREATE TABLE statements.
    """
    db_path = tmp_path / "test.db"
    SQLiteRepository(db_path=db_path)
    with sqlite3.connect(db_path) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        po_cols = [row[1] for row in conn.execute("PRAGMA table_info(po_inventory)").fetchall()]
        ri_cols = [row[1] for row in conn.execute("PRAGMA table_info(receiving_items)").fetchall()]
        bm_cols = [
            row[1] for row in conn.execute("PRAGMA table_info(barcode_model_map)").fetchall()
        ]
        ss_cols = [row[1] for row in conn.execute("PRAGMA table_info(sync_status)").fetchall()]
    assert version == 4
    assert "claimed_at" in po_cols, "po_inventory.claimed_at missing — 0002 migration not applied"
    assert "serial" in ri_cols, "receiving_items.serial missing — 0002 migration not applied"
    assert "raw_barcode" in bm_cols, (
        "barcode_model_map.raw_barcode missing — 0003 migration not applied"
    )
    assert "consecutive_failures" in ss_cols, "sync_status missing — 0004 migration not applied"


def test_migration_runner_idempotent(tmp_path):
    db_path = tmp_path / "test.db"
    SQLiteRepository(db_path=db_path)
    SQLiteRepository(db_path=db_path)  # second construction — no-op
    with sqlite3.connect(db_path) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert version == 4


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


def test_save_record_serial_round_trips(tmp_path):
    """serial stored in save_record is readable from get_pending."""
    repo = _repo(tmp_path)
    repo.save_record(_record(serial="SN-TEST-9876"))
    pending = repo.get_pending()
    assert pending[0]["serial"] == "SN-TEST-9876"


# ── Claiming tests ────────────────────────────────────────────────────────────


def test_unclaimed_for_po_returns_all_rows_when_none_claimed(tmp_path):
    """unclaimed_for_po returns all rows when none have claimed_at set."""
    repo = _repo(tmp_path)
    repo.upsert_items(
        [
            _item(inventory_id="INV-001", purchase_order="PO-001", model_number="MDL-A"),
            _item(inventory_id="INV-002", purchase_order="PO-001", model_number="MDL-A"),
        ]
    )
    rows = repo.unclaimed_for_po("PO-001")
    assert len(rows) == 2
    assert all(r["claimed_at"] is None for r in rows)


def test_unclaimed_for_po_excludes_claimed_rows(tmp_path):
    """After claiming INV-001, unclaimed_for_po must not include it.

    Kills any mutation that drops the AND claimed_at IS NULL filter.
    """
    repo = _repo(tmp_path)
    repo.upsert_items(
        [
            _item(inventory_id="INV-001", purchase_order="PO-001", model_number="MDL-A"),
            _item(inventory_id="INV-002", purchase_order="PO-001", model_number="MDL-A"),
        ]
    )
    repo.claim("INV-001", "2026-06-22T10:00:00")
    rows = repo.unclaimed_for_po("PO-001")
    assert len(rows) == 1
    assert rows[0]["inventory_id"] == "INV-002"


def test_claim_sets_claimed_at(tmp_path):
    """claim() sets claimed_at on the target row."""
    repo = _repo(tmp_path)
    repo.upsert_items([_item(inventory_id="INV-001", purchase_order="PO-001")])
    repo.claim("INV-001", "2026-06-22T10:00:00")
    rows = repo.get_purchase_order("PO-001")
    assert len(rows) == 1
    assert rows[0]["claimed_at"] == "2026-06-22T10:00:00"


def test_claim_is_guarded_against_double_claiming(tmp_path):
    """Claiming an already-claimed row (AND claimed_at IS NULL) is a silent no-op.

    The second claim() call must not update claimed_at to a different value.
    Kills any mutation that removes the AND claimed_at IS NULL guard from the
    UPDATE statement — without the guard, the second call overwrites the timestamp.
    """
    repo = _repo(tmp_path)
    repo.upsert_items([_item(inventory_id="INV-001", purchase_order="PO-001")])
    repo.claim("INV-001", "2026-06-22T10:00:00")
    repo.claim("INV-001", "2026-06-22T11:00:00")  # second attempt — must be a no-op
    rows = repo.get_purchase_order("PO-001")
    assert rows[0]["claimed_at"] == "2026-06-22T10:00:00", (
        "second claim() overwrote claimed_at — AND claimed_at IS NULL guard is missing"
    )


def test_claim_only_targets_matching_inventory_id(tmp_path):
    """claim("INV-001") must not affect INV-002 on the same PO."""
    repo = _repo(tmp_path)
    repo.upsert_items(
        [
            _item(inventory_id="INV-001", purchase_order="PO-001"),
            _item(inventory_id="INV-002", purchase_order="PO-001"),
        ]
    )
    repo.claim("INV-001", "2026-06-22T10:00:00")
    rows = repo.get_purchase_order("PO-001")
    inv002 = next(r for r in rows if r["inventory_id"] == "INV-002")
    assert inv002["claimed_at"] is None


def test_unclaimed_for_po_returns_empty_when_all_claimed(tmp_path):
    """After claiming all rows, unclaimed_for_po returns empty list."""
    repo = _repo(tmp_path)
    repo.upsert_items([_item(inventory_id="INV-001", purchase_order="PO-001")])
    repo.claim("INV-001", "2026-06-22T10:00:00")
    rows = repo.unclaimed_for_po("PO-001")
    assert rows == []


# ── claim_and_save (T0-1 atomicity) ──────────────────────────────────────────


def test_claim_and_save_writes_both_claim_and_record(tmp_path):
    """claim_and_save commits the inventory claim and the receiving record together.

    Mutation kill targets:
      - removing the UPDATE po_inventory call → unclaimed_for_po still returns the row
      - removing the INSERT receiving_items call → get_pending() returns empty
    Both assertions must pass for the method to be correct.
    """
    repo = _repo(tmp_path)
    repo.upsert_items([_item()])
    record = _record()

    repo.claim_and_save("INV-001", "2026-06-22T10:00:00", record)

    # Inventory row is now claimed
    rows = repo.unclaimed_for_po("PO-001")
    assert rows == [], "inventory row must be claimed after claim_and_save"

    po_rows = repo.get_purchase_order("PO-001")
    assert po_rows[0]["claimed_at"] == "2026-06-22T10:00:00"

    # Receiving record is saved
    pending = repo.get_pending()
    assert len(pending) == 1
    assert pending[0]["receiving_id"] == "REC-001"


def test_claim_and_save_preserves_claimed_at_is_null_guard(tmp_path):
    """A second claim_and_save on an already-claimed row does not overwrite claimed_at.

    The AND claimed_at IS NULL guard in the UPDATE must be present: a concurrent
    scan that races to claim the same row after it is already claimed must be a
    no-op on the claim, while the record upsert still succeeds.

    Mutation kill target: removing AND claimed_at IS NULL causes the second call
    to overwrite claimed_at to '2026-06-22T11:00:00', failing the equality check.
    """
    repo = _repo(tmp_path)
    repo.upsert_items([_item()])

    repo.claim_and_save("INV-001", "2026-06-22T10:00:00", _record())
    repo.claim_and_save("INV-001", "2026-06-22T11:00:00", _record())  # second call — guard fires

    po_rows = repo.get_purchase_order("PO-001")
    assert po_rows[0]["claimed_at"] == "2026-06-22T10:00:00", (
        "second claim_and_save overwrote claimed_at — AND claimed_at IS NULL guard is missing"
    )


def test_claim_and_save_record_idempotent_on_conflict(tmp_path):
    """Re-calling claim_and_save with the same receiving_id upserts without error.

    ON CONFLICT(receiving_id) DO UPDATE must not raise; emitted is preserved.
    """
    repo = _repo(tmp_path)
    repo.upsert_items([_item()])
    repo.claim_and_save("INV-001", "2026-06-22T10:00:00", _record())
    repo.mark_emitted("REC-001")

    # Re-save (retry scenario) — emitted must be preserved
    repo.claim_and_save("INV-001", "2026-06-22T10:00:00", _record())

    assert repo.was_emitted("REC-001") is True
    assert len(repo.get_pending()) == 0
