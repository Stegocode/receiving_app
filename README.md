# receiving-app

A portable warehouse receiving automation with three operating modes: an
interactive barcode-scanning desk application, a morning catalog-rebuild
utility, and a headless receiving robot. All three share a single `.env`
configuration file and a layered, dependency-injected architecture that keeps
business logic testable without any live infrastructure.

---

## What it does

**Scanner application** (`receiving-app`) — accepts barcode input from a USB
HID wedge or manual keyboard entry. Scans a model barcode followed by a serial
barcode; the application matches the unit against open purchase order lines in a
local catalog, claims the inventory slot to prevent double-receives, posts the
outcome (received / no-match / needs-attention) to a result sink board, and
prints a label on success. A barcode prefixed `PO:` switches the locked
purchase order without triggering a match.

**Catalog refresh** (`receiving-refresh`) — fetches all open purchase order
data from the purchase order source portal and atomically replaces the local
SQLite inventory catalog. If the portal fetch fails or returns zero rows, the
existing catalog is left untouched — no data is lost on failure.

**Receiving robot** (`receiving-robot`) — polls a configurable READY group on
the result sink board, drives each item through the portal's multi-step
receiving wizard, then moves the item to RECEIVED or NO_MATCH. A circuit
breaker halts the loop automatically if the per-pass success rate drops below
50 % after five attempts.

---

## Architecture

Three layers; dependencies point inward only:

```
┌──────────────────────────────────────────────┐
│  adapters/   edge layer — DB, portal,        │
│              board API, scanner, printer, UI │
│  ┌──────────────────────────────────────┐    │
│  │  services/   orchestration          │    │
│  │  ┌──────────────────────────────┐   │    │
│  │  │  core/   pure domain logic  │   │    │
│  │  │  no I/O, no framework       │   │    │
│  │  └──────────────────────────────┘   │    │
│  └──────────────────────────────────────┘    │
└──────────────────────────────────────────────┘
```

- **core/** — error taxonomy, port protocols, schema (with validator), and
  barcode-matching logic. No imports outside stdlib.
- **services/** — orchestration (receive, sync, populate, refresh,
  receive\_sync). Coordinates core via injected ports. No adapter imports.
- **adapters/** — concrete implementations: SQLite repository, purchase order
  source portal scraper, result sink board API client, portal receiving wizard,
  barcode scanner, label printer, Tkinter UI.

Dependency direction is mechanically enforced by
[import-linter](https://import-linter.readthedocs.io) and the conformance gate
(`python scripts/conformance.py`). Neither core nor services can import
adapters; the compiler catches violations before merge.

---

## Setup

**Requirements:** Python ≥ 3.11. WinPython is the recommended distribution on
Windows.

```
pip install -e ".[dev]"
playwright install chromium   # needed for portal adapters (source + receiver)
```

**Configuration:**

```
cp .env.example .env
# then open .env and fill every value
```

See `.env.example` for the full variable list with descriptions. The required
groups are:

| Group | Variables |
|---|---|
| Paths | `DB_PATH`, `LOG_DIR`, `DOWNLOAD_DIR` |
| Purchase order source | `SOURCE_BASE_URL`, `SOURCE_USERNAME`, `SOURCE_PASSWORD` |
| Result sink / board | `SINK_BASE_URL`, `SINK_API_TOKEN`, `SINK_BOARD_ID` |
| Board groups | `SINK_RECEIVED_GROUP_ID`, `SINK_NO_MATCH_GROUP_ID`, `SINK_ATTENTION_GROUP_ID`, `SINK_READY_GROUP_ID` |
| Board columns | `SINK_INVENTORY_ID_COL`, `SINK_MODEL_COL`, `SINK_SERIAL_COL`, `SINK_STATUS_COL` |
| Receiving wizard | `RECEIVE_LOCATION`, `RECEIVE_WHSE_LOCATION` |
| Mode switches | `SCANNER_TYPE`, `PRINTER_TYPE`, `SOURCE_TYPE`, `SINK_TYPE`, `RECEIVER_TYPE` |
| Optional | `POLL_INTERVAL_SECS` (default 10), `RECEIVE_SCREENSHOT_DIR` (default `LOG_DIR/screenshots`) |

`config.validate()` is the first call in every entry point. It reads `.env`,
checks every required variable in one pass, and lists all missing values
together so you fix them all at once.

---

## Running

```bash
receiving-app        # scanner desk UI (Tkinter)
receiving-refresh    # morning catalog rebuild — prompts "Type YES to confirm"
receiving-robot      # headless receiving robot — Ctrl+C to stop
```

`receiving-app` and `receiving-robot` log to `LOG_DIR/receiving_app.log`
(rotating daily, 30-day retention). The receiving robot also writes per-step
screenshots to `RECEIVE_SCREENSHOT_DIR`.

---

## Dev / test mode

Set these switches in `.env` to run without any live portal or board:

```
SOURCE_TYPE=fake        # reads FAKE_SOURCE_DATA JSON instead of scraping
SINK_TYPE=null          # logs outcomes instead of posting to the board API
RECEIVER_TYPE=fake      # in-memory receive stub instead of Playwright wizard
SCANNER_TYPE=manual     # keyboard text field instead of USB HID wedge
PRINTER_TYPE=preview    # opens an HTML label in the browser instead of printing
```

**Run the test suite:**

```bash
pytest                  # all tests
pytest -q               # quiet
```

**Full gate sequence (run before every commit):**

```bash
ruff check .
ruff format --check .
mypy core services adapters config.py
lint-imports
python scripts/conformance.py
pytest --cov=core --cov=services --cov=config --cov-fail-under=95 -q
```

Coverage is measured over `core/`, `services/`, and `config.py` (the
unit-testable layers). The mutation score gate (`mutmut`) is run separately in
CI.

---

## Project layout

```
core/               domain logic — errors, ports, schema, matching
services/           orchestration — receive, sync, populate, refresh, receive_sync
adapters/           edge adapters
  board.py          result sink board API client (GraphQL)
  db.py             SQLite repository + migration runner
  printer.py        label printer (preview / Zebra)
  receiver.py       portal receiving wizard (Playwright sync)
  scanner.py        barcode scanner (wedge / manual)
  sink.py           result sink adapter (graphql / null)
  source.py         purchase order source scraper (portal / fake)
  ui/               Tkinter scanner desk UI + controller
schema/             SQL migration files (applied in version order at startup)
tests/              test suite and fakes (FakeBoard, FakeReceiver, etc.)
scripts/            conformance gate
config.py           single config source — read env, validate, expose typed accessors
.env.example        template for required configuration
DEBT.md             deferred decisions ledger
```

See `docs/RUNBOOK.md` for daily operating procedures and failure recovery.
