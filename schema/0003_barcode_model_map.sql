-- Owns: schema migration 0003 — learned barcode-to-model mapping store.
-- Must not: contain any proprietary names in column or table names.

CREATE TABLE IF NOT EXISTS barcode_model_map (
    raw_barcode  TEXT PRIMARY KEY,   -- exact scanned string, byte-for-byte
    model_number TEXT NOT NULL,      -- confirmed model
    fuzzy_score  REAL,               -- diagnostic only; never used in lookup logic
    confirmed_at TEXT NOT NULL,      -- ISO timestamp of last confirmation
    source       TEXT NOT NULL       -- 'confirmed' or 'manual'
);
