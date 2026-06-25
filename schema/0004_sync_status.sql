-- Owns: sync_status table — single-row robot loop audit trail.
-- Must not: contain any proprietary names in column or table names.

CREATE TABLE IF NOT EXISTS sync_status (
    id                    INTEGER PRIMARY KEY DEFAULT 1,
    state                 TEXT NOT NULL,
    last_outcome          TEXT NOT NULL,
    consecutive_failures  INTEGER NOT NULL DEFAULT 0,
    stopped_reason        TEXT NOT NULL DEFAULT '',
    updated_at            TEXT NOT NULL
);
