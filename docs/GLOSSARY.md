# Glossary

Domain vocabulary and technical terms for the warehouse receiving application.
Use this alongside the other docs — operator concepts appear first, then
board/status terms, then application and architecture terms.

---

## Domain Terms

### Barcode
A machine-readable product identifier scanned from a physical unit. The scanner
desk captures two barcodes per unit in sequence: the **model barcode** and the
**serial barcode**. Input is accepted from a USB HID wedge (barcode gun) or
manual keyboard entry.

### Catalog
The local SQLite copy of all open purchase order line items, rebuilt each morning
by `receiving-refresh`. The scanner app reads from the local catalog rather than
querying the upstream portal on every scan, so it works at desk speed after the
morning refresh completes.

### Claim
An atomic lock placed on a single inventory slot the moment a scan successfully
matches it. Implemented as a `claimed_at` timestamp written alongside the
receiving record in one database transaction (`claim_and_save`). A claimed slot
cannot be matched by any subsequent scan until the claim is manually cleared.

### Circuit Breaker
The robot's automatic kill switch. If fewer than 50 % of portal receiving
attempts in a single pass succeed (evaluated after at least 5 attempts), the
robot logs `robot_kill` and stops. Prevents a run of bad data from making
repeated failed portal requests. Restart the robot after investigating root cause.

### EAN-14
A 14-digit barcode format. Some scanners emit the 14-digit form of a
13-digit code (leading `0` prefix). Handling of this format during model
matching is deferred to a future normalization pass. See `core/matching.py`.

### Idempotency Key (`receiving_id`)
A stable SHA-256 hash of `po_number + inventory_id + barcode`, stored as the
`receiving_id` field on every receiving record. Any adapter that receives the
same `receiving_id` twice must treat the second call as a no-op. Ensures
crash-and-retry and network duplicate events never create duplicate records.

### Inventory Item / Inventory Slot
One line entry in the local catalog — a single unit of a product on a purchase
order. Each slot carries a unique `inventory_id`. Once claimed, a slot cannot be
matched again until the claim is manually cleared (see **Claim** above).

### `inventory_id`
A string identifier that uniquely identifies one slot in the local inventory
catalog. Assigned by the upstream purchase order portal; treated as opaque by
the application.

### Match Status (`match_status`)
The outcome field on every receiving record. One of four values:

| Value | Meaning |
|---|---|
| `received` | Barcode matched a catalog entry; unit claimed and label printed. |
| `no_match` | No catalog entry exactly matched the scanned barcode. |
| `needs_attention` | Matched but requires human review before completing. |
| `already_scanned` | Serial number already claimed on this PO — duplicate scan. |

### `no_match`
The scan outcome when the scanned barcode does not exactly match (normalized:
uppercase, spaces and hyphens stripped) any unclaimed catalog row on the locked
purchase order. The slot is not claimed; the outcome is posted to the NO MATCH
board group.

### `needs_attention`
A scan outcome that surfaces the item to a dedicated board group for human
review rather than auto-completing. Triggered by specific upstream conditions.

### `already_scanned`
The outcome when the scanned serial number exactly matches a serial already
claimed on this PO. The record is not saved or emitted again — the duplicate is
signalled to the operator only.

### Purchase Order (PO)
A formal authorization to receive a specific quantity of items. The scanner desk
is locked to one PO at a time. A barcode prefixed `PO:` (e.g. `PO:10001`)
switches the locked PO without triggering a model scan.

### `receiving_id`
See **Idempotency Key** above.

### Serial Number (`serial`)
The physical unit's serial number, typically scanned from a label on the
hardware. Used as the unique physical-unit discriminator for duplicate-scan
detection. A non-blank serial that matches a unit already claimed on this PO
produces `already_scanned` without saving or emitting again.

---

## Board Terms

### Board
The external task-board service used as a result sink and work queue. Items
move between groups as the system processes them. Connection details are set
in `.env` (`SINK_*` variables).

### READY Group
The board group from which the receiving robot polls items. An item in READY
is queued for the next robot pass. Configured via `SINK_READY_GROUP_ID`.

### RECEIVED Group
Items that have been successfully processed through the portal receiving wizard.
Configured via `SINK_RECEIVED_GROUP_ID`.

### NO MATCH Group
Items where the model could not be found in the portal's receiving grid, or a
required field (PO number, inventory ID, model, serial) was missing. Configured
via `SINK_NO_MATCH_GROUP_ID`.

### ATTENTION Group
Items that need human review. The scanner app moves `needs_attention` records
here. Configured via `SINK_ATTENTION_GROUP_ID`.

### TBR (To Be Received)
Quantity remaining to receive for a model row in the portal's receiving grid.
The robot skips model rows where TBR = 0 (already fully received).

---

## Application and Architecture Terms

### Adapter
A concrete implementation of a port, living in `adapters/`. Adapters are the
only layer permitted to perform I/O (network, disk, hardware, UI). Swappable
behind their port interface without changing any service or core code.

### Composition Root
The entry-point module (`scanner_runner.py`, `robot_runner.py`,
`refresh_runner.py`) where concrete adapters are constructed and injected into
services. The only place that knows which adapter is wired in at runtime.

### Conformance Gate
The mechanical enforcement script at `scripts/conformance.py`. Runs 14 gates
on all tracked files: banned terms, absolute paths, boundary markers, config
isolation, file size, schema version, debt ledger presence, SQL injection
prevention, and more. Every gate must be green before a commit is accepted.

### Fake Adapter
An in-memory stub that satisfies a port protocol without touching live
infrastructure. Selected via `*_TYPE=fake` / `null` / `manual` / `preview` in
`.env`. All fakes live in `tests/fakes/` or alongside their adapter and are
used by the test suite as well as for local development without credentials.

### Exact Normalized Match
The matching strategy used to compare a scanned barcode string against a model
string. Both sides are normalized identically — converted to uppercase and stripped
of all spaces and hyphens — then compared for string equality. No scoring or
thresholds; a match is exact equality on the normalized form, or no match.

| Context | Function | Location |
|---|---|---|
| Catalog matching (scanner app) | `resolve_exact()` | `core/matching.py` |
| Portal grid matching (robot) | `_model_matches()` via `exact_model_match()` | `adapters/receiver.py` |

### Port
A `@runtime_checkable Protocol` class in `core/ports.py` defining the interface
for one I/O boundary. Services depend only on ports; concrete adapters are
injected at the composition root. Current ports: `Repository`,
`PurchaseOrderSource`, `ResultSink`, `ReceivingBoard`, `ReceivingExecutor`,
`Scanner`, `Printer`, `SyncStatusStore`.

### Receiving Record (`ReceivingRecord`)
The output contract — a dataclass in `core/schema.py` (schema version 2). Carries
all information about one scan event: PO number, inventory ID, model number,
serial, match status, timestamp, product dimensions, brand, and more. Validated
on construction via `validate_record()`; migrated forward via `migrate()`.

### Result Sink
The `ResultSink` port — the external system where receiving outcomes are posted.
The live implementation calls a board API; the null sink logs and discards. See
`adapters/sink.py`.

### Robot
The headless automation (`receiving-robot`). Polls the board's READY group,
drives each item through the portal receiving wizard (`ReceivingExecutor`), and
moves it to RECEIVED or NO MATCH. Runs until Ctrl+C or the circuit breaker trips.

### `SCHEMA_VERSION`
An integer constant in `core/schema.py` (currently `2`) that identifies the
current data schema revision. The database adapter runs forward migrations
automatically on startup up to this version.

### Scanner Desk Application
The interactive Tkinter UI (`receiving-app`). Accepts barcode input from a USB
HID wedge or keyboard. Displays scan state and outcomes in real-time. State
machine: IDLE → MID_SCAN → MATCHING.

### `SyncStatusRecord`
A single-row audit record in the database tracking the robot's current
operational state: `running` / `stopped`, last outcome (`none` / `success` /
`failure` / `kill`), consecutive failure count, and stop reason. Written on run
start, each item outcome, and stop. Read by any monitoring tool that checks robot
health.

---

## Configuration Terms

### Adapter Type Switch
Each adapter has a `*_TYPE` environment variable (`SOURCE_TYPE`, `SINK_TYPE`,
`RECEIVER_TYPE`, `SCANNER_TYPE`, `PRINTER_TYPE`) selecting the live or
development implementation at startup, without code changes.

### `.env`
The local configuration file, copied from `.env.example` and filled with
site-specific values. Never committed to version control (enforced by `.gitignore`
and conformance `gate_j`). All required variables are validated on startup; the
application lists every problem and refuses to start until they are fixed.

### `.env.example`
A committed template listing every configuration variable with blank values and
descriptions. Conformance `gate_i` verifies this file is tracked and covers all
variables declared in `config.py`.
