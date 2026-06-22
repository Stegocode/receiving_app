# DEBT

Tracked decisions deferred in this build. Each entry states what was deferred,
why, and the signal that should trigger resolving it.

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

[DEBT-T08-001] 2026-06-19 — `adapters/source.py` is PORTED but live-untested.
CI has no browser binary, no credentials, and no live portal. The entire browser
pipeline is mocked in tests. Validate the following against the live portal before
declaring T-08 DONE:
  - Timing constants (_LOGIN_SETTLE_SECS, _POST_LOGIN_SECS, _FILTER_SETTLE_SECS,
    _NAV_SETTLE_SECS, _DOWNLOAD_TIMEOUT_SECS) — may need tuning per environment.
  - Login form selectors: By.NAME "email", By.NAME "password", By.XPATH submit button.
  - Filter checkbox IDs: "OpenFilter", "OnOrderFilter" — confirm these exist in the
    current portal version.
  - Location-save popup ID "save-current-location" — confirm absent/present behaviour.
  - Export button selector: //i[contains(@class,'fa-file-excel-o')]/.. — confirm class name.
  - Download filename keyword "serial-number-inventory" — confirm file naming convention.
  - CSV column names: "Inventory Id", "PO #", "Model", "Category", "Product Group",
    "Brand", "Tags" — confirm they match the current export format.
Trigger: before T-08 is considered production-ready; run with `playwright install`
/ chromedriver and real credentials in a local .env.

[DEBT-T08-002] 2026-06-19 — fetch_order always scrapes all open orders and filters.
The portal has no single-PO endpoint; every fetch downloads the full on-order CSV.
If PO-level queries become available on the portal API, fetch_order can be optimised
to request only the target PO. Trigger: portal adds a filterable REST endpoint.

[DEBT-T08-003] 2026-06-19 — Screenshots omitted from ported adapter.
The oracle captures debug screenshots on key steps. The port omits this to avoid
hardcoding a screenshot directory path. Add screenshot capture when a SCREENSHOT_DIR
config var is introduced (T-12 observability ticket).
Trigger: T-12 adds LOG_DIR-relative screenshot path to config.

[DEBT-T11b-001] 2026-06-19 — `adapters/ui/scanner_ui.py` and scanner adapters are not unit-tested in CI.
The Tk view and scanner adapters (WedgeScanner, ManualScanner) require a display and a real Tk root
to construct widgets. CI has no display environment and no USB scanner hardware. The testable
scan/print orchestration logic lives in adapters/ui/controller.py, which is fully tested (4 tests,
no Tk dependency). Validate the UI manually on macOS with a USB HID gun (wedge) and in manual mode.
Trigger: any change to scanner_ui.py, scanner.py, or the scan state machine.

[DEBT-T11c-001] 2026-06-20 — dev mode (SOURCE_TYPE=fake, SINK_TYPE=null) is unit-tested but not end-to-end validated.
FakeSource and NullSink are individually tested (test_source.py, test_sink.py, test_factories.py).
The full running-app flow with SOURCE_TYPE=fake + SINK_TYPE=null has not been exercised
with a real UI session. Validate manually before relying on dev mode for onboarding or training.
Trigger: before dev mode is used as the default training environment.

[DEBT-T12-001] 2026-06-21 — REMEDIATED 2026-06-21 (sink.py column IDs injected; real-ID gate added; errors test hardened). `adapters/board.py` (BoardApiAdapter) is PORTED but live-untested.
CI has no real API token, no live board, and no real group or column IDs. The entire API
pipeline is mocked in tests. Validate the following against the live board before
declaring T-12 DONE:
  - SINK_BOARD_ID, SINK_READY_GROUP_ID, SINK_RECEIVED_GROUP_ID, SINK_NO_MATCH_GROUP_ID —
    populate from the live board configuration.
  - SINK_INVENTORY_ID_COL, SINK_MODEL_COL, SINK_SERIAL_COL, SINK_STATUS_COL — confirm
    column IDs still valid against the current live board schema.
  - Verify poll_ready pagination: confirm cursor is returned and followed correctly when
    the READY group contains more than 500 items.
  - Verify mark_received: confirm move_item_to_group succeeds and change_column_value
    sets the status column to RECEIVED in the live board.
  - Verify mark_no_match: confirm move_item_to_group moves the item to the NO MATCH group.
Trigger: before T-13 (receive executor) is wired to a live board; run with real
credentials in a local .env pointing at the live board.

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
Additionally: RECEIVE_KILL_THRESHOLD (0.5) and MIN_ATTEMPTS_BEFORE_KILL (5) are untuned guesses —
validate and tune against real failure patterns on the first live run.
DB reconciliation (cleaning up RECEIVED rows from the local SQLite store after a successful portal
receive) is also deferred — currently out of scope for the orchestrator.
Trigger: first live run of the full receiving robot with real credentials and a populated READY group.

[DEBT-T09-001] 2026-06-19 — `adapters/sink.py` is PORTED but live-untested.
CI has no real API token, no live board, and no real group IDs. The entire API
pipeline is mocked in tests. Validate the following against the live board before
declaring T-09 DONE:
  - SINK_BASE_URL, SINK_BOARD_ID, SINK_RECEIVED_GROUP_ID, SINK_NO_MATCH_GROUP_ID,
    SINK_ATTENTION_GROUP_ID — populate from the oracle project .env (the sink API
    token, board ID, and group IDs from the oracle's result-sink client module).
  - Column IDs (_STATUS_COL, _INVENTORY_ID_COL, _MODEL_COL) — confirm still
    valid against the live board schema.
  - Verify that create_item with column_values JSON is accepted by the board API
    and items land in the expected groups.
Trigger: before T-09 is considered production-ready; run with real credentials in a
local .env pointing at the live board.

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
