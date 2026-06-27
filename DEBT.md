# DEBT

Tracked decisions deferred in this build. Each entry states what was deferred,
why, and the signal that should trigger resolving it.

---

CANONICAL SOURCE OF TRUTH: DEBT.md is the single authoritative record of deferred/known issues for
this repo. If another planning doc or audit disagrees with DEBT.md, DEBT.md wins and the other doc is
updated to match. Every confirmed deferred issue lands here.

---

[DEBT-T01] 2026-06-17 — Skeleton only, no logic.
All .py files in this commit are stubs. Business logic, port implementations,
and tests are implemented in T-02 through T-14.

[DEBT-CI01] 2026-06-17 — RESOLVED 2026-06-18 (T-02)
Canonical entry point declared as `receiving-app = "__main__:main"` in [project.scripts].
Startup gate added as `tests/test_config.py::test_startup_gate` — calls __main__.main()
in-process and asserts clean exit. `pythonpath` corrected to [".", "scripts"] so tests
can import config and core.* alongside conformance.

[DEBT-001] 2026-06-17 — `core/io_helpers.py` (atomic_write) deferred.
SQLite manages its own durability; no non-DB file-artifact write exists in v1.
Introduce atomic_write when/if a genuine non-DB file write appears (e.g. an export
or summary file).

[DEBT-T08-001] 2026-06-19 — LIVE-VERIFIED 2026-06-22 — `adapters/source.py` portal source validated live.
Full catalog fetch ran successfully (~4218 rows, ~43s). All selectors, timing constants,
CSV column names, and filter IDs confirmed against the live portal.
Note: the 43-second fetch duration is the trigger to evaluate a faster source strategy
(cookie-handoff or partial-export API) if refresh latency becomes a bottleneck.

[DEBT-T08-002] 2026-06-19 — fetch_order always scrapes all open orders and filters.
The portal has no single-PO endpoint; every fetch downloads the full on-order CSV.
If PO-level queries become available on the portal API, fetch_order can be optimised
to request only the target PO. Trigger: portal adds a filterable REST endpoint.

[DEBT-T08-003] 2026-06-19 — Screenshots omitted from ported adapter.
The oracle captures debug screenshots on key steps. The port omits this to avoid
hardcoding a screenshot directory path. Add screenshot capture when a SCREENSHOT_DIR
config var is introduced (T-12 observability ticket).
Trigger: T-12 adds LOG_DIR-relative screenshot path to config.

[DEBT-T11b-001] 2026-06-19 — LIVE-VERIFIED 2026-06-22 (Windows) — `adapters/ui/scanner_ui.py` manual entry mode and PO label printing validated live on Windows.
The Tk view and scanner adapters still require a display to construct; CI has no display environment
and no USB scanner hardware. Testable orchestration logic in adapters/ui/controller.py remains
fully covered by 4 unit tests. Wedge scanner (USB HID) not yet tested on this machine.
Trigger: any change to scanner_ui.py, scanner.py, or the scan state machine.

[DEBT-T11c-001] 2026-06-20 — dev mode (SOURCE_TYPE=fake, SINK_TYPE=null) is unit-tested but not end-to-end validated.
FakeSource and NullSink are individually tested (test_source.py, test_sink.py, test_factories.py).
The full running-app flow with SOURCE_TYPE=fake + SINK_TYPE=null has not been exercised
with a real UI session. Validate manually before relying on dev mode for onboarding or training.
Trigger: before dev mode is used as the default training environment.

[DEBT-T12-001] 2026-06-21 — LIVE-VERIFIED 2026-06-22 — `adapters/board.py` (BoardApiAdapter) validated live.
All group IDs, column IDs, mark_received, and mark_no_match confirmed against the live board.
Pagination not fully stress-tested (READY group < 500 items in this run).
(Previously REMEDIATED 2026-06-21 for column ID injection and gate hardening.)

[DEBT-T13-001] 2026-06-21 — `adapters/receiver.py` (PortalReceiver) is PORTED but live-untested.
CI has no browser binary, no portal credentials, and no live session. Tests exercise
FakeReceiver and the pure _model_matches predicate only. Validate the following against
the live portal before relying on PortalReceiver in production:
  - Login flow: email/password fill, Enter press, networkidle settle, re-login on /login redirect.
  - Step 1: purchase-orders?id={po} navigation, receive-btn click, receiving URL wait (15s timeout).
  - Step 2: select.apply-all-location option resolution by RECEIVE_LOCATION text, kendo JS set,
    onApplyAllLocation(0) button click, 3-second settle for WHSE options to load.
  - Step 3: select.apply-all-whse option resolution by RECEIVE_WHSE_LOCATION text (log available
    options), kendo JS set, onApplyAllWhseLocation(0) button click.
  - Step 4: tr.k-master-row grid scan — _model_matches against cell[3], TBR > 0 check in
    cell[7], qty input resolution (input.receiving-qty-input fallback to cell[8] input).
  - Grid pagination: .k-next-button / aria-label*=next / .k-i-arrow-e selector coverage,
    k-disabled and aria-disabled stop conditions, up to _MAX_GRID_PAGES pages.
  - Step 5 → 6: a[href='#next'] click, input.brand-serial-input fill (absent → not_found).
  - Step 7 → 8: second a[href='#next'] click, a[href='#finish'] click, .alert-danger /
    .alert.alert-error visibility check for finalize_error detection.
  - Browser session reuse: second receive_item call in the same session (no re-login expected).
  - close() idempotency: calling close() twice, and calling close() before any receive_item.
  - Screenshot capture: verify PNG files appear in RECEIVE_SCREENSHOT_DIR at each step.
Trigger: before the orchestrator (T-14) is run against the live board and portal;
run with real credentials and RECEIVE_LOCATION / RECEIVE_WHSE_LOCATION in a local .env.

[DEBT-T14-001] 2026-06-21 — receive_sync is unit-tested with fakes; integrated robot is live-untested.
services/receive_sync.py is fully covered by FakeBoard + FakeReceiver. The integrated robot
(real ReceivingBoard + real PortalReceiver + live portal + live board) has never been run end-to-end.
NOTE (T1-4a 2026-06-24): RECEIVE_KILL_THRESHOLD and MIN_ATTEMPTS_BEFORE_KILL replaced by
consecutive-failure escalation (CONSECUTIVE_FAILURE_KILL=2 — see DEBT-T1-4a-001). That threshold
is itself untuned.
DB reconciliation (cleaning up RECEIVED rows from the local SQLite store after a successful portal
receive) is also deferred — currently out of scope for the orchestrator.
Trigger: first live run of the full receiving robot with real credentials and a populated READY group.

[DEBT-T1-4a-001] 2026-06-24 — CONSECUTIVE_FAILURE_KILL=2 is untuned.
The 2-consecutive-failure kill threshold is an initial guess based on domain knowledge that one
failure is almost always transient (page not ready) and two in a row is almost certainly a systemic
automation problem. Validate and tune against real live-run failure patterns before relying on it
as an operational control. Trigger: first live run of the robot with a populated READY group and
real portal credentials.

[DEBT-T1-4a-002] 2026-06-24 — SyncStatusSQLiteStore._ensure_schema duplicates schema/0004_sync_status.sql.
adapters/db.py is at the 400-line gate_e limit, preventing the shared migration runner from being
extended to cover sync_status. SyncStatusSQLiteStore uses its own CREATE TABLE IF NOT EXISTS
directly. The schema definition is therefore declared twice (once in the SQL migration file, once in
the Python adapter). Resolve by splitting db.py when the Postgres migration is tackled
(DEBT-T15-003) and unifying both entry-points under a single migration runner.
Trigger: db.py split / Postgres migration work begins.

[DEBT-T09-001] 2026-06-19 — LIVE-VERIFIED 2026-06-22 — `adapters/sink.py` sink adapter verified live against the real board.
All group IDs and column IDs confirmed. create_item accepted by the board API; items
land in the correct groups with correct column values. Root cause of earlier 401 errors
identified as SINK_BASE_URL being set to the web board URL instead of the API endpoint
(documented in GETTING_STARTED troubleshooting).

[DEBT-T15-001] 2026-06-21 — Plain-text logging; no machine-parseable output yet.
Logs are written as human-readable text to a rotating file (receiving_app.log). If a
downstream WMS, monitoring system, or log aggregator requires structured output, switch
setup_logging to a JSON formatter and consider dated sub-folders under LOG_DIR.
Trigger: integration with a log aggregator or WMS that needs parseable log lines.

[DEBT-T15-002] 2026-06-21 — No retry budget in portal adapters.
adapters/source.py (PortalSource) and adapters/receiver.py (PortalReceiver) abort on
transient failures with no retry. A single network hiccup raises SourceError / ExecutorError
immediately. Future: configurable retry count with exponential backoff, injected at
construction time so unit tests remain fast (no sleep).
Trigger: first live run reveals transient portal failures that a retry would have recovered.

[DEBT-T15-003] 2026-06-21 — Single Repository implementation (SQLite only).
SQLiteRepository is the only implementation of the Repository port. For production scale or
multi-writer access, a Postgres adapter behind the same port is needed.
Trigger: dataset outgrows SQLite, multi-writer access is required, or production moves to a
managed database (e.g. Neon Postgres).

[DEBT-T16.1-002] 2026-06-22 — SQLiteRepository._connect() connections never explicitly closed; ResourceWarnings in Python 3.13.
The with self._connect() as conn: pattern throughout SQLiteRepository commits/rolls back on __exit__ but never calls
conn.close(). Python 3.13's GC issues ResourceWarnings for unclosed sqlite3.Connection objects. Functional correctness
is unaffected (SQLite auto-closes at GC). Fix: add explicit conn.close() after each with block or adopt a single
long-lived connection per method. Deferred as pre-existing pattern; _ensure_schema was fixed in T-16.1 (uses try/finally).
Trigger: Python 3.13+ upgrade or CI run with -W error::ResourceWarning.

[DEBT-T16.1-001] 2026-06-22 — replace_po_items atomicity is connection-level, not WAL-safe under concurrent writers.
SQLiteRepository.replace_po_items uses a single sqlite3.connect() context manager (DELETE + bulk INSERT in one implicit transaction),
which is atomic for the single-writer case. Under concurrent writers or WAL mode, a second writer between connections would see an
empty window during the DELETE phase. Acceptable for single-writer SQLite (DEBT-T15-003 tracks the Postgres migration).
Trigger: multi-writer access or WAL-mode deployment.

[DEBT-T15-004] 2026-06-21 — Mixed log-call styles across adapters (cosmetic only).
Three styles coexist: extra={} (receiver.py), %-format strings (receive_sync.py), and
logger.info(json.dumps({...})) (sink.py, board.py). All styles are now fully rendered in the
log file: _ContextFormatter appends extra={} fields as key=value pairs, and json.dumps strings
appear verbatim in the message. The gap is cosmetic (inconsistent call convention), not functional.
Standardize on one structured style (extra={} preferred) in a future cleanup pass.
Trigger: adding a log aggregator or formatter that expects one call convention.

[DEBT-T16.2-001] 2026-06-22 — PARTIAL-VERIFIED 2026-06-22 — ZebraPrinter (adapters/printer.py) live-printed a PO label successfully.
win32print spool path, ZPL generation, _find_zebra_printer(), and PRINTER_TYPE=zebra config
switch confirmed for the PO label code path. Receiving label (separate ZPL generation path)
is still unverified — validate before relying on ZebraPrinter for the receiving workflow.
Trigger: before the scanner is used in production receiving with label printing enabled.

[DEBT-PRINTER-001] 2026-06-22 — ZebraPrinter printer-name search list is HARDCODED in adapters/printer.py.
_find_zebra_printer() matches installed printer names against hardcoded keyword terms. If the
installed Zebra driver name on a new machine does not contain those keywords, the printer is
silently not found and the scan fails at print time. Must be made configurable (e.g. a
PRINTER_NAME env var with a fallback search list) before the app is shared as a generic
template or deployed to machines with differently-named drivers.
Trigger: before sharing as a generic template or deploying to a new machine with a Zebra printer.

[DEBT-SETUP-001] 2026-06-22 — Interactive setup wizard deferred (issue #27 long-term).
A guided setup wizard (step-by-step env var entry with inline validation feedback) was
requested in issue #27. The near-term fix is the expanded GETTING_STARTED.md (first-run
validation checklist + env var reference). The wizard is deferred until the receiving robot
is hardened and the docs have been validated with at least one new-hire onboarding.
Trigger: second new-hire setup attempt reveals the docs are still insufficient.

[DEBT-NAMING-001] 2026-06-22 — Internal match_status value "received" is semantically misleading.
In services/ and core/, the scan outcome "received" means "matched and ready for the robot to
portal-receive" — it does not mean the item has been physically received at the portal.
The routing was corrected in the prior PR (items route to READY on the board); the internal
name was deliberately left unchanged to avoid a broad rename mid-sprint.
Rename received → ready in a dedicated cleanup PR to align with the domain meaning.
Trigger: any refactor that touches match_status or the scan/receive state machine.

[DEBT-BOARD-001] 2026-06-23 — board.mark_received is a NON-ATOMIC two-call sequence.
adapters/board.py mark_received() issues two separate API mutations: move_item_to_group (to the
RECEIVED group), THEN change_column_value (set status to RECEIVED). If the second call fails, the
item sits in the RECEIVED group with a blank/wrong status and nothing reconciles it. This is the same
partial-write class that was fixed at the DB layer by claim_and_save (T0-1/DEBT-ATOMICITY-001), but
it is unaddressed at the board boundary. The board is the operational ledger, so a half-applied
mark_received leaves a visibly-wrong row. Fix options: combine into a single mutation if the board
API supports moving + setting status atomically; OR set status FIRST then move (so a failure leaves
the item in its prior group with correct status, which is more recoverable than RECEIVED-with-blank);
OR add a reconciliation pass that detects RECEIVED-group items with missing status. Trigger: before
relying on board state as the authoritative received-ledger, or first observed half-applied row.

[DEBT-MATCH-001] 2026-06-23 — identical-model rows may under-claim under concurrent scanners.
In services/receive.py process_scan, after resolve_exact returns a model, the matched row is chosen
via next((c for c in candidates if c["model_number"] == best_model), None) — it always takes the
FIRST matching unclaimed row. For a single scanner this is fine: each claim removes that row from
unclaimed_for_po, so the next scan of the same model finds the next row. The risk is CONCURRENT
scanners: two scanners reading unclaimed_for_po before either claims could both select the same first
row, and the AND claimed_at IS NULL guard means the second claim silently no-ops — under-receiving by
one unit with no error surfaced. Masked today by single-scanner staging. Fix: have the claim path
detect a no-op claim (zero rows updated) and retry against the next unclaimed row, or select+lock a
distinct row per scan. Related: DEBT-T16.1-001 (WAL/concurrent-writer). Trigger: before running more
than one scanner against the same PO concurrently.

[DEBT-MATCH-002] 2026-06-26 — barcode_model_map.fuzzy_score column is a misnomer post-exact-match.
The barcode_model_map table (schema migration 0003) stores a fuzzy_score column that was meaningful
under the old difflib threshold-based matcher. After T2b replaced fuzzy matching with exact normalized
equality, the column name is misleading — the system no longer produces or uses similarity scores.
The column schema and the ReceivingMapStore port's fuzzy_score parameter are intentionally left
unchanged in this ticket (out of scope, no migration). Resolve the naming mismatch in the
SCHEMA_VERSION reconciliation ticket (see DEBT-SCHEMA-VER-001). Trigger: before SCHEMA_VERSION or
SQLite user_version is advanced again; rename fuzzy_score to match_score or drop it if unused.

[DEBT-SCHEMA-VER-001] 2026-06-24 — SCHEMA_VERSION in core/schema.py and SQLite user_version can drift.
core/schema.py declares SCHEMA_VERSION = 2 (ReceivingRecord shape version). The SQLite DB tracks a
separate version via PRAGMA user_version (now 3 after migration 0003 added barcode_model_map). Two
independent counters with no cross-check — if one advances without the other, the gap is silent.
Potential Rule 5 / Rule 8 concern (single source of truth; schema as a contract). Decision needed:
UNIFY if both counters represent the same concept, or explicitly RENAME and document them as distinct
concerns (record-shape version vs. DB migration level). Pre-existing gap — predates the barcode-map
PR; that PR only made the discrepancy visible by bumping user_version to 3 while SCHEMA_VERSION
stayed at 2.
Trigger: before either counter advances again; resolve in a focused PR touching core/schema.py and
possibly migration/validation logic — not a rider on an unrelated PR.

[DEBT-MUTGATE-001] 2026-06-26 — 221 mutation survivors need triage after gate was blind.
The mutation gate was non-functional (schema/ not copied into the mutant sandbox), so all
mutants generated while the gate was broken were never actually tested. The real score is
79.2% (839 killed / 221 survived / 1060 checked) — above the 78% threshold but sensitive
to runner speed (see below). The 221 survivors include both genuine equivalents and
potentially killable gaps from code merged while the gate was blind. They must be triaged
to separate accepted equivalents from gaps that need new tests. The old 151-survivor
classification in MUTATION.md was produced under the broken gate and should be treated as
a starting point only, not authoritative.
Priority — timeout-killed mutants must be converted to assertion-kills first: survivors
killed only by timeout (e.g. an infinite-loop mutant in model_matches_barcode where the
forward-walk advance is mutated to a no-op) are the gate's primary flake risk. Add a test
that makes a non-advancing walk produce a wrong answer the suite catches, so the mutant
dies on an assertion, not a clock. Until then the score can flip below 78% on a slow
runner with no code change.
Why: code merged during the blind period was never mutation-tested; the survivor count
roughly doubled (116 → 221) compared to the last honest run. Timeout-killed mutants
additionally make the score non-deterministic across runner speeds.
How to apply: before the next matching/services change, run a dedicated triage pass —
convert timeout-killed survivors to assertion-kills first, then categorise the remainder
by category (log-format, inert default, dead branch, killable gap) and add tests for any
killable gaps. Trigger: next PR touching core/ or services/, or a dedicated cleanup pass.

[BUG-SOURCE-CSV-001] 2026-06-25 — _parse_on_order_csv (adapters/source.py) does not validate required CSV headers.
If the portal renames "PO #", "Model", or "Inventory Id", the parser silently degrades: a renamed
"PO #" or "Model" column causes every row to return with an empty purchase_order or model_number
(caller receives plausible-looking but wrong data); a renamed "Inventory Id" column causes every row
to be skipped and the caller receives [] — indistinguishable from a genuinely empty export. Both
outcomes are fail-open and violate Constitution Rule 4 (fail closed, deny by default). Found while
writing T5-13 contract tests (tests/test_source_contract.py); not fixed there — that ticket adds
tests only. Fix: at the start of _parse_on_order_csv, inspect reader.fieldnames after reading the
header and raise SourceError if any required column ("Inventory Id", "PO #", "Model") is absent.
Trigger: before the portal CSV export format is considered stable for production; or immediately if
a live fetch returns 0 rows unexpectedly (may be a silent column-rename, not a genuine empty order).
