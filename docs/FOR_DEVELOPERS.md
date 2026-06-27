# Developer Guide

Architecture, gate stack, dev mode, and how to extend the system. See
[CONTRIBUTING.md](../CONTRIBUTING.md) for branch and commit conventions.

---

## Architecture

The codebase follows a strict three-layer hexagonal structure. Dependencies
point **inward only**:

```
┌──────────────────────────────────────────────────┐
│  adapters/   edge — DB, portal, board API,       │
│              scanner, printer, Tkinter UI        │
│  ┌────────────────────────────────────────────┐  │
│  │  services/   orchestration                │  │
│  │  ┌──────────────────────────────────────┐ │  │
│  │  │  core/   pure domain logic           │ │  │
│  │  │  no I/O, no framework deps           │ │  │
│  │  └──────────────────────────────────────┘ │  │
│  └────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────┘
```

- **core/** — error taxonomy, port protocols, schema (versioned + validated),
  and barcode-matching logic. No imports outside stdlib.
- **services/** — orchestration. Coordinates core via injected ports. No
  adapter imports.
- **adapters/** — concrete implementations. Know about core; never imported by
  core or services.

### Ports vs. adapters — the swappable seam

`core/ports.py` defines `@runtime_checkable` Protocol classes for every I/O
boundary: `Repository`, `PurchaseOrderSource`, `ResultSink`, `ReceivingBoard`,
`ReceivingExecutor`, `Scanner`, `Printer`. Services depend only on the
protocol; the concrete adapter is injected at the composition root.

This is the primary extension seam. The purchase-order source adapter, for
example, could be backed by a different data-fetching implementation (such as
one that reads from a local data-management tool rather than scraping the
portal) simply by writing a new class that satisfies `PurchaseOrderSource` and
wiring it into `make_source()`. No service or core code changes.

### Enforcement

Dependency direction is mechanically checked on every run:

- **import-linter** — three contracts in `pyproject.toml` forbid outward
  imports; violation fails the gate.
- **conformance gate** — `gate_c` checks boundary marker comments (`# Owns:` /
  `# Must not:` / `# May import:`) in every module in `core/`, `services/`,
  and `adapters/`. A module missing its markers fails the gate.

---

## File map

```
core/
  errors.py         typed error taxonomy (ConfigError, SyncKillError, etc.)
  ports.py          Protocol classes for every I/O boundary
  schema.py         ReceivingRecord dataclass; validate_record(); SCHEMA_VERSION
  matching.py       exact_model_match(), resolve_exact(), model_matches_barcode(), resolve_model()
  logging_setup.py  setup_logging(log_dir) — midnight-rotating handler

services/
  receive.py        process_scan() — scan orchestration, claim guard, emit
  receive_sync.py   receive_pending() — one poll pass; circuit breaker at 50 %
  sync.py           sync_pending() — PASS / PARTIAL / KILL bands
  populate.py       populate_po() — idempotent PO load into repo
  refresh.py        refresh_all() — fetch-first, atomic replace

adapters/
  board.py          BoardApiAdapter (GraphQL); make_board(); FakeBoard
  db.py             SQLiteRepository; migration runner (PRAGMA user_version)
  printer.py        PreviewPrinter / ZebraPrinter (ZPL via win32print); make_printer()
  receiver.py       PortalReceiver (Playwright sync); FakeReceiver; make_receiver()
  scanner.py        WedgeScanner / ManualScanner; make_scanner()
  sink.py           ResultSinkAdapter / NullSink; make_sink()
  source.py         PortalSource (Selenium + CSV) / FakeSource; make_source()
  ui/
    scanner_ui.py   ReceivingUI — Tkinter desk app; state machine IDLE→MID_SCAN→MATCHING
    controller.py   handle_scan() — Tk-free scan/print orchestration
    scan_states.py  colours, fonts, flash/alarm helpers

schema/
  0001_init.sql               initial schema
  0002_claim_and_serial.sql   claimed_at, serial, brand, tags, vendor

scripts/
  conformance.py    14-gate mechanical check (see conformance section below)

config.py           single config source; validate() checks all required vars
scanner_runner.py   composition root for receiving-app (build_app + main)
refresh_runner.py   composition root for receiving-refresh
robot_runner.py     composition root for receiving-robot (poll loop)
```

---

## Gate stack

Run these in order before every commit. All must be green.

```bash
# 1. Lint
ruff check .

# 2. Format
ruff format --check .

# 3. Types
mypy core services adapters config.py

# 4. Import direction
lint-imports

# 5. Conformance (14 gates)
python scripts/conformance.py

# 6. Tests + coverage
pytest --cov=core --cov=services --cov=config --cov-fail-under=95 -q
```

**Coverage scope:** `core/`, `services/`, and `config.py` only. Adapter
integration tests require live infrastructure and are excluded from the
coverage gate; they run against real systems separately.

**Conformance gates** (`scripts/conformance.py`):
- `gate_a` — banned terms (client/vendor/operator names, real IDs). Reads from
  `.conformance-banned` (gitignored locally; provisioned via CI secret).
  Skipped locally if the file is absent; enforced in CI.
- `gate_b` — no absolute paths in tracked files.
- `gate_c` — boundary markers (`# Owns:` / `# Must not:` / `# May import:`)
  in every module under `core/`, `services/`, `adapters/`.
- `gate_d` — env reads only in `config.py`.
- `gate_e` — no source file over ~400 lines, no function over ~60 lines.
- `gate_g` — `SCHEMA_VERSION` declared in `core/schema.py`.
- `gate_h` — `DEBT.md` exists and is non-empty.
- `gate_i` — `.env.example` exists and covers all vars in `config.py`.
- `gate_j` — `.gitignore` covers `.env`, `__pycache__`, and the banned-terms file.
- `gate_k` — no committed `__pycache__` directories.
- `gate_l` — no string-built SQL (f-string or % formatting into a query).
- `gate_m` — `MatchNotFoundError` not used (replaced by the `no_match` outcome path).
- `gate_n` — no `input()` calls in `services/`.
- `gate_o` — no telemetry singletons in `core/`.

**Mutation testing** (run separately, not in the pre-commit gate):

```bash
mutmut run
mutmut results
```

Scoped to `core/` and `services/`. Score target ≥ 78 %. Accepted survivors
are documented in `MUTATION.md`.

---

## Dev / test mode

Switch any adapter to a fake by setting the corresponding `*_TYPE` variable
in `.env`. All fakes are in-memory and require no live infrastructure.

| Variable | `portal` / `graphql` / `wedge` / `zebra` | `fake` / `null` / `manual` / `preview` |
|---|---|---|
| `SOURCE_TYPE` | scrapes the PO portal via Selenium | reads `FAKE_SOURCE_DATA` JSON fixture |
| `SINK_TYPE` | posts to the board via GraphQL | logs outcomes, no network call |
| `RECEIVER_TYPE` | drives the portal wizard via Playwright | in-memory stub keyed by inventory ID |
| `SCANNER_TYPE` | reads from USB HID wedge | keyboard text field |
| `PRINTER_TYPE` | prints ZPL to Zebra printer | opens HTML label in browser |

To run completely offline (scanner UI):

```
SOURCE_TYPE=fake
SINK_TYPE=null
SCANNER_TYPE=manual
PRINTER_TYPE=preview
```

To run the robot offline:

```
RECEIVER_TYPE=fake
SINK_TYPE=null
```

Run the test suite:

```bash
pytest        # all tests
pytest -q     # quiet
pytest -k receive_sync   # target one module
```

---

## Adding a new adapter

1. **Define the port** (if one does not exist) — add a `Protocol` class to
   `core/ports.py` with the methods the service needs.

2. **Write the adapter** in `adapters/` — implement the protocol. Add the
   boundary marker comment block at the top (`# Owns:` / `# Must not:` /
   `# May import:`).

3. **Write a fake** in `tests/fakes/` (or alongside the adapter) that
   satisfies the same protocol for testing.

4. **Register in the factory** — add a branch to the `make_*()` function in
   the adapter module so the new type is selectable via a `*_TYPE` config
   variable.

5. **Add a config var** (if needed) — add it to `config.py` and `.env.example`.

6. **Write tests** using the fake, not the real adapter. Coverage gate is
   measured over `core/` and `services/` — adapter tests are in
   `tests/test_*.py` but excluded from the coverage requirement.

7. **Record live-testing status** in `DEBT.md` if the adapter cannot be
   integration-tested locally (see existing entries for the pattern).
