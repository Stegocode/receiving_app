# receiving-app

A portable warehouse receiving automation with three operating modes: an
interactive barcode-scanning desk application, a morning catalog-rebuild
utility, and a headless receiving robot.

> **Independent tool.** This project automates interactions with third-party
> systems. It is not affiliated with or endorsed by the upstream
> purchase-order portal vendor or the result-board vendor.

---

## Who should read what

| You are… | Start here |
|---|---|
| Warehouse or office operator | [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md) |
| Developer working on the code | [docs/FOR_DEVELOPERS.md](docs/FOR_DEVELOPERS.md) |
| Contributor | [CONTRIBUTING.md](CONTRIBUTING.md) |

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

## Quickstart

**Requirements:** Python ≥ 3.11. WinPython is the recommended distribution on
Windows.

```
pip install -e ".[dev]"
playwright install chromium   # needed for portal adapters (source + receiver)
cp .env.example .env          # then fill every value
```

```bash
receiving-app        # scanner desk UI (Tkinter)
receiving-refresh    # morning catalog rebuild — prompts "Type YES to confirm"
receiving-robot      # headless receiving robot — Ctrl+C to stop
```

Full setup instructions and daily operating procedures:
[docs/GETTING_STARTED.md](docs/GETTING_STARTED.md).

---

## Architecture

Three layers; dependencies point inward only: a pure **core** (domain logic,
no I/O) → **services** (orchestration) → **adapters** (edge: DB, portal,
board API, scanner, printer, UI). The adapters are swappable behind their port
protocols — the core and services layers are unaware of which concrete adapter
is wired in. Dependency direction is enforced mechanically by import-linter and
the conformance gate. Full detail in [docs/FOR_DEVELOPERS.md](docs/FOR_DEVELOPERS.md).

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

See [docs/RUNBOOK.md](docs/RUNBOOK.md) for the quick daily reference card once
you are set up.
