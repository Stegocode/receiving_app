# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased] — fix/mutation-gate-integrity — 2026-06-26

### Fixed

**Mutation gate was passing vacuously (two stacked bugs)**
- `[tool.mutmut] also_copy` omitted `"schema"`, so migration `.sql` files were
  absent from the mutant sandbox. Every DB-backed test failed with
  "no such table: barcode_model_map", leaving all 1094 mutants "not checked"
  (exit code `None`).
- The inline CI scorer counted `None` exit codes as killed (`if code != 0`),
  and `mutmut run || true` swallowed the crash — a run that checked nothing
  reported 100% and cleared the 78% threshold.
- Real score once fixed: **78.8%** (862 killed / 232 survived / 1094 checked).

### Changed

- `pyproject.toml`: added `"schema"` to `[tool.mutmut] also_copy`.
- `scripts/mutation_score.py`: new committed scorer (extracted from inline YAML
  heredoc). Counts `None` exit codes as `not_checked`; asserts
  `checked == generated` and exits non-zero if any mutant is unchecked; computes
  `score = killed / checked`; prints killed/survived/not_checked counts.
- `.github/workflows/ci.yml`: removed `|| true` from `mutmut run`; replaced
  inline heredoc scorer with `python scripts/mutation_score.py`.
- `MUTATION.md`: updated to real post-fix run (78.8%, 232 survivors); added note
  that the gate was previously non-functional.
- `DEBT.md`: added `DEBT-MUTGATE-001` — 232 survivors need triage.

---

## [Unreleased] — fix/exact-model-match (T2b)

### Changed

**Fuzzy matching replaced with exact normalized match (T2b)**
- `core/matching.py`: removed `find_best_match`, `match_score`, `normalize`,
  `strip_ean14`, and the `difflib` import. Added `exact_model_match(a, b)` (delegates
  to `normalize_key`: case-fold + strip spaces/hyphens, then string equality) and
  `resolve_exact(barcode, candidates)` (returns the single exact match or `None` —
  never guesses). The two-tier `resolve_model` and `model_matches_barcode` from T2a
  are retained; `_norm_model` private helper deleted in favour of the shared
  `normalize_key` canonical normalizer.
- `services/receive.py`: rewired from `find_best_match` to `resolve_exact`. A scan
  that does not produce an exact match falls through to `no_match` unchanged.
- `adapters/receiver.py`: rewired `_model_matches` from fuzzy scoring (0.85 threshold
  + substring shortcuts) to `exact_model_match`. Substring shortcuts (`b in a`,
  `a in b`) deleted — they were the proximate cause of near-twin SKU collisions on
  the portal grid.

**Root cause:** near-twin model numbers (e.g. SHX78CM5N / SHP78CM5N) scored above
the 0.6 / 0.85 thresholds and caused a serial to be bound to the wrong catalog row
on a live PO. Exact normalized equality eliminates false-positive matches by
construction.

---

## [0.1.0] — 2026-06-22

Initial complete release: scanner desk application, catalog refresh utility,
and headless receiving robot. All adapters are ported and unit-tested with
fakes; live-portal integration is validated separately (see `DEBT.md`).

### Added

**Robot runner — poll loop and entry point (T-16.3)**
- `robot_runner.py`: entry point and `while True` poll loop for the receiving
  robot. Calls `receive_pending(board, executor)` each pass, logs
  `pass_complete` counters, breaks on `SyncKillError` (kill switch) or
  `KeyboardInterrupt`, logs pass-level exceptions and continues (mirrors the
  oracle loop structure). `executor.close()` guaranteed in a `finally` block.
- `receiving-robot` console script registered in `pyproject.toml`.

**Scanner data chain — claiming, serial, label fields (T-16.2)**
- `claimed_at` column added to `receiving_inventory` via schema migration
  `0002_claim_and_serial.sql`; prevents double-receives of the same unit.
- Serial number field wired through `ReceivingRecord`, SQLite repository,
  result sink adapter, and label printer (ZPL output).
- Brand, tags, and vendor fields added to the schema and label.
- ZPL label printer (`adapters/printer.py`) ported from the oracle; Zebra
  printer selected via `PRINTER_TYPE=zebra`.
- PO-barcode switching wired into the scanner UI (`PO:` prefix intercepts
  without triggering a model match).

**DB migration runner and refresh safety (T-16.1)**
- `adapters/db.py` migration runner: reads `PRAGMA user_version`, applies
  pending `schema/000N_*.sql` files in order, advances the version atomically.
  Idempotent: re-runs apply nothing.
- `replace_po_items()` added to the `Repository` port; `refresh_all` rewritten
  to fetch-first, empty-guard, then replace atomically. A failed or empty fetch
  never wipes the catalog.
- `receiving-refresh` console script and `refresh_runner.py` entry point.

**Test suite quality gates (T-16)**
- pytest coverage gate: `--cov=core --cov=services --cov=config
  --cov-fail-under=95` (achieved 99.5 %).
- Mutation testing (`mutmut`) scoped to `core/` and `services/`; score gate
  78 % (achieved 82.4 %). Accepted survivors documented in `MUTATION.md`.

**Observability and logging (T-15)**
- `core/logging_setup.py`: `setup_logging(log_dir)` wires a midnight-rotating
  file handler (`receiving_app.log`, 30-day retention) to the root logger.
- `_ContextFormatter` appends `extra={}` fields as `key=value` pairs so
  structured log calls render fully in plain-text output.
- Structured log events added to all boundary crossings (`db`, `board`,
  `receiver`, `receive_sync`).

**Receive-sync orchestrator and circuit breaker (T-14)**
- `services/receive_sync.py`: `receive_pending(board, executor)` — one poll
  pass that drives the executor for every READY item, routes outcomes, and
  trips a mid-loop circuit breaker (`SyncKillError`) when
  `received / attempted < 0.5` after five attempts.
- `ReceiveResult` dataclass (received, no\_match, failed, skipped counters).

**Portal receiving executor (T-13)**
- `adapters/receiver.py`: `PortalReceiver` — sync Playwright adapter that
  drives the eight-step portal receiving wizard (navigate, set location, set
  WHSE, find model row by fuzzy match, set qty, enter serial, finalise).
  Lazy browser session; idempotent `close()`.
- `FakeReceiver`: in-memory stub; outcomes keyed by inventory ID.
- `make_receiver()` factory; `RECEIVER_TYPE`, `RECEIVE_LOCATION`,
  `RECEIVE_WHSE_LOCATION`, `RECEIVE_SCREENSHOT_DIR` config vars.

**Result sink board adapter (T-12)**
- `adapters/board.py`: `BoardApiAdapter` — paginated GraphQL poll of the READY
  group; `mark_received` (move + set status column); `mark_no_match` (move).
- `FakeBoard`: in-memory dev/test adapter returned by `make_board("fake")`.
- Five new config vars: `SINK_READY_GROUP_ID` and four board column IDs.
- Conformance gate extended with a real-ID fragment check.

**Banned-name scrub (SCRUB)**
- Banned names and real IDs moved from `conformance.py` into a gitignored
  `.conformance-banned` file; CI provisions it from a repository secret.
  Gate skips with a stderr warning when the file is absent locally.

**Tkinter scanner UI and dev mode (T-11b, T-11c)**
- `adapters/ui/scanner_ui.py`: `ReceivingUI` — Tkinter desk application.
  Tk-free `__init__`; all widget construction deferred to `run()`.
  State machine: IDLE → MID\_SCAN → MATCHING. PO-barcode switching.
- `adapters/ui/scan_states.py`: colours, fonts, state/flash/alarm helpers.
  Lazy `winsound` import guarded by `sys.platform == "win32"`.
- `adapters/ui/controller.py`: `handle_scan()` — scan/print orchestration,
  Tk-free and fully unit-tested.
- `adapters/scanner.py`: `WedgeScanner` (USB HID hidden Entry) and
  `ManualScanner`; `make_scanner()` factory; `SCANNER_TYPE` config var.
- `adapters/printer.py`: `PreviewPrinter` (HTML in browser) and `ZebraPrinter`
  (ZPL via win32print); `make_printer()` factory; `PRINTER_TYPE` config var.
- `FakeSource` (reads JSON fixture at `FAKE_SOURCE_DATA`) and `NullSink` (log
  only) complete the dev-mode pairing with `SOURCE_TYPE=fake` / `SINK_TYPE=null`.

**Core services — receive, sync, populate, refresh (T-10)**
- `services/receive.py`: `process_scan()` — deterministic `receiving_id`
  (SHA-256 hash), crash-safe step order (save → guard → emit → mark), routing
  to `sink.emit()` or `sink.surface_attention()`.
- `services/sync.py`: `sync_pending()` — PASS / PARTIAL / KILL bands;
  `SyncResult` counters; post-loop circuit breaker at `KILL_THRESHOLD = 0.5`.
- `services/populate.py`: `populate_po()` — idempotent; skips source fetch if
  rows already exist for the PO.
- `services/refresh.py`: `refresh_all(confirmed=bool)` — no-op when
  `confirmed=False`; atomic fetch-and-replace; no console prompts.

**Purchase order source and result sink adapters (T-08, T-09)**
- `adapters/source.py`: `PortalSource` (Selenium scraper, CSV export) and
  `FakeSource`; `make_source()` factory; `SOURCE_TYPE`, `SOURCE_BASE_URL`,
  `SOURCE_USERNAME`, `SOURCE_PASSWORD`, `DOWNLOAD_DIR`, `FAKE_SOURCE_DATA`.
- `adapters/sink.py`: `ResultSinkAdapter` (GraphQL API) and `NullSink`;
  `make_sink()` factory; idempotent on `receiving_id`; audit log on state
  transitions only.

**SQLite repository (T-07)**
- `adapters/db.py`: `SQLiteRepository` — six-method `Repository` port
  implementation. `ON CONFLICT DO UPDATE` upsert (Postgres-portable).
  Schema: `receiving_items` and `po_inventory` tables.

**Core domain — schema, matching, errors, ports (T-03 through T-06)**
- `core/schema.py`: `ReceivingRecord` dataclass (`SCHEMA_VERSION = 1`);
  `validate_record()`, `from_dict()`, `to_dict()`, `migrate()`.
- `core/matching.py`: `strip_ean14()`, `normalize()`, `match_score()`,
  `find_best_match()` — fuzzy matching with SequenceMatcher (≥ 0.85 threshold).
- `core/errors.py`: typed error taxonomy —`ConfigError`, `ValidationError`,
  `SourceError`, `SinkError`, `RepositoryError`, `SyncKillError`,
  `PrinterError`, `ScannerError`, `BoardError`, `ExecutorError`.
- `core/ports.py`: `Repository`, `PurchaseOrderSource`, `ResultSink`,
  `ReceivingBoard`, `ReceivingExecutor`, `Scanner`, `Printer` protocols
  (all `@runtime_checkable`).

**Configuration and entry points (T-01, T-02)**
- `config.py`: single config source; `validate()` reads `.env`, checks all
  required variables in one pass, exposes typed module-level accessors.
  `ConfigError` lists every missing variable.
- `__main__.py`: composition root `build_app()` + `main()`.
- `.env.example`: template with descriptions for all variables.
- `scripts/conformance.py`: 14-gate mechanical conformance check (banned names,
  absolute paths, boundary markers, env-read isolation, file size, schema
  version, debt ledger, `.env.example`, `.gitignore`, no `__pycache__`,
  no string-built SQL, no `MatchNotFoundError`, no `input()` in services,
  no telemetry singletons).
