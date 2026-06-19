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
