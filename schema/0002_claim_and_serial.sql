-- Owns: schema migration 0002 — claiming and serial tracking columns.
-- Must not: contain any proprietary names in column or table names.

ALTER TABLE po_inventory    ADD COLUMN claimed_at TEXT;   -- NULL = unclaimed; set on first model match
ALTER TABLE receiving_items ADD COLUMN serial     TEXT;   -- serial number scanned with the unit
