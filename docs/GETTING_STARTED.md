# Getting Started — Operator Guide

This guide covers everything a warehouse or office operator needs to install the
application, run it daily, and recover from common failures. No programming
knowledge required.

All file paths are referred to by their **setting name** (e.g. `LOG_DIR`,
`RECEIVE_SCREENSHOT_DIR`). The actual paths are set in your `.env` file.

---

## 1. Installation

**You need:** Python 3.11 or newer. On Windows, [WinPython](https://winpython.github.io/)
is the recommended distribution.

Open a terminal in the project folder and run:

```
pip install -e ".[dev]"
playwright install chromium
```

The second command installs the headless browser used by the portal adapters.
You only need to run it once.

---

## 2. Configuration

Copy the example configuration file and fill in your values:

```bash
cp .env.example .env          # Unix / macOS
Copy-Item .env.example .env   # Windows PowerShell
```

Open `.env` in a text editor and fill every line. The settings are grouped as
follows:

**Paths** — where the application stores its database, logs, and downloads.
All three must be **absolute paths**. The application creates `LOG_DIR`,
`DOWNLOAD_DIR`, and the parent directory of `DB_PATH` automatically on first
start — you do not need to create them manually.

| Setting | What it is |
|---|---|
| `DB_PATH` | Path to the SQLite database file (created automatically; its parent directory is also created automatically) |
| `LOG_DIR` | Absolute path to the directory for rotating log files (created automatically) |
| `DOWNLOAD_DIR` | Absolute path to a scratch directory for portal download files (created automatically) |

**Purchase order source** — credentials for the portal that holds open orders:

| Setting | What it is |
|---|---|
| `SOURCE_BASE_URL` | Base URL of the purchase-order portal |
| `SOURCE_USERNAME` | Login username |
| `SOURCE_PASSWORD` | Login password |

**Result sink / board** — connection details for the board where outcomes are posted.
`SINK_BASE_URL` must be the **API endpoint URL**, not the board's web browser URL
(e.g. `https://api.your-board-provider.com/v2`, not `https://your-board-provider.com/boards/12345`).
Using the web URL will cause 401 Unauthorized errors.

| Setting | What it is |
|---|---|
| `SINK_BASE_URL` | API endpoint URL for the result board service (no trailing slash) |
| `SINK_API_TOKEN` | API authentication token for the result board |
| `SINK_BOARD_ID` | Numeric board ID on the result board service |

**Board groups** — IDs of the board groups that items move between:

| Setting | What it is |
|---|---|
| `SINK_READY_GROUP_ID` | Items queued for the robot |
| `SINK_RECEIVED_GROUP_ID` | Successfully received items |
| `SINK_NO_MATCH_GROUP_ID` | Items that could not be matched |
| `SINK_ATTENTION_GROUP_ID` | Items that need human review |

**Board columns** — IDs of the columns the application reads and writes:

| Setting | What it is |
|---|---|
| `SINK_INVENTORY_ID_COL` | Column holding the inventory ID |
| `SINK_MODEL_COL` | Column holding the model name |
| `SINK_SERIAL_COL` | Column holding the serial number |
| `SINK_STATUS_COL` | Column holding the status value |

**How to find your board's group and column IDs**

Run the following GraphQL query against `SINK_BASE_URL` with the header
`Authorization: <SINK_API_TOKEN>`. Replace `YOUR_BOARD_ID` with the numeric value of
`SINK_BOARD_ID`:

```graphql
{
  boards(ids: [YOUR_BOARD_ID]) {
    groups { id title }
    columns { id title type }
  }
}
```

Map each result to the matching variable:

| Variable | What to look for in the response |
|---|---|
| `SINK_READY_GROUP_ID` | The `groups` entry whose `title` is your READY group |
| `SINK_RECEIVED_GROUP_ID` | The `groups` entry whose `title` is your RECEIVED group |
| `SINK_NO_MATCH_GROUP_ID` | The `groups` entry whose `title` is your NO MATCH group |
| `SINK_ATTENTION_GROUP_ID` | The `groups` entry whose `title` is your ATTENTION group |
| `SINK_INVENTORY_ID_COL` | The `columns` entry for the inventory ID field |
| `SINK_MODEL_COL` | The `columns` entry for the model name field |
| `SINK_SERIAL_COL` | The `columns` entry for the serial number field |
| `SINK_STATUS_COL` | The `columns` entry with `type: "color"` — the status/color column |

The status column (`SINK_STATUS_COL`) must have label options named exactly **READY**,
**RECEIVED**, **NO MATCH**, and **ATTENTION** in the board's column settings.
The application writes these labels by name.

**Receiving wizard** — location labels used when the robot completes a receipt:

| Setting | What it is |
|---|---|
| `RECEIVE_LOCATION` | Location label for the receiving wizard |
| `RECEIVE_WHSE_LOCATION` | WHSE location label |

**Adapter switches** — control which mode each component runs in:

| Setting | Dev value | Live value | What it controls |
|---|---|---|---|
| `SOURCE_TYPE` | `fake` | `portal` | Where PO data comes from: JSON fixture or live portal scraper |
| `SINK_TYPE` | `null` | `graphql` | Where results are posted: nowhere (log only) or live board API |
| `RECEIVER_TYPE` | `fake` | `portal` | How portal receiving is performed: simulated or live portal wizard |
| `SCANNER_TYPE` | `manual` | `wedge` | How barcodes are entered: text box or USB HID barcode gun |
| `PRINTER_TYPE` | `preview` | `zebra` | How labels are printed: browser window or physical Zebra printer |

All switches default to their live values when omitted from `.env`. Set them to their
dev values when validating a new install without live credentials (see
[First-run validation](#3-first-run-validation) below).

> `PRINTER_TYPE` accepts only `preview` or `zebra` — there is no `fake` value for the printer.

**Secret handling**

The `.env` file contains credentials that grant access to live systems. Apply
these practices before deploying:

- **Restrict file permissions.** On Unix/macOS: `chmod 600 .env`. On Windows,
  use Properties → Security to restrict read access to the current user only.
- **Use least-privilege accounts.** `SOURCE_USERNAME` / `SOURCE_PASSWORD`
  needs only read access to open purchase orders. `SINK_API_TOKEN` needs only
  write access to the receiving board groups. Do not use an admin account or a
  token with broader permissions than required.
- **Rotate credentials on a schedule.** Treat `SOURCE_PASSWORD` and
  `SINK_API_TOKEN` as short-lived. Rotate them according to your organisation's
  policy and immediately on any suspected exposure.
- **Never commit `.env` to version control.** Enforced by `.gitignore` and the
  conformance gate (`gate_j`). The `.env.example` template (committed, no real
  values) is the safe reference for what variables are required.

---

**Optional settings** (defaults shown):

| Setting | Default | What it is |
|---|---|---|
| `POLL_INTERVAL_SECS` | `10` | Seconds the robot sleeps between passes |
| `RECEIVE_SCREENSHOT_DIR` | `LOG_DIR/screenshots` | Where the robot saves receiving wizard screenshots |
| `FAKE_SOURCE_DATA` | `test_data/pos.json` | JSON fixture file used when `SOURCE_TYPE=fake` |

The application checks every required setting on startup and lists any missing
values together so you can fix them all at once.

---

## 3. First-run validation

### Setup sequence

Complete these steps in order on a fresh install:

1. **Install Python 3.11 or newer** — on Windows, [WinPython](https://winpython.github.io/)
   is the recommended distribution.

2. **Install dependencies:**
   ```
   pip install -e ".[dev]"
   playwright install chromium
   ```

3. **Copy `.env.example` to `.env`** and fill in every value.
   See [Configuration](#2-configuration) above for descriptions.

### Validation checklist (dev/fake mode)

Before connecting to live systems, confirm the install works using fake adapters
that need no credentials. Add these lines to `.env` (or set them as environment variables):

```
SOURCE_TYPE=fake
SINK_TYPE=null
RECEIVER_TYPE=fake
SCANNER_TYPE=manual
PRINTER_TYPE=preview
```

> `PRINTER_TYPE` only accepts `preview` or `zebra` — there is no `fake` value.

Then run each command and verify the expected result:

**Step 1 — Catalog refresh**
```
receiving-refresh
```
Type `YES` at the prompt. On success:
```
Refresh complete — N items in catalog.
```
A small number matching the fixture file is expected. This confirms `SOURCE_TYPE=fake` is working.

**Step 2 — Scanner UI**
```
receiving-app
```
Enter `PO:10001` in the PO field and press Enter to load the fixture purchase order.
Then type any model number, press Enter, then type any serial number and press Enter.
A MATCH or NO_MATCH result confirms the scanner flow is wired correctly.
Close the window when done.

**Step 3 — Receiving robot**
```
receiving-robot
```
You should see a poll-loop start message. Press **Ctrl+C** to stop cleanly.
This confirms `SINK_TYPE=null` and `RECEIVER_TYPE=fake` are selected correctly.

**If all three commands run without errors, your install is correct.**

### Switching to live mode

Once dev-mode validation passes, update `.env` to the live values:

```
SOURCE_TYPE=portal
SINK_TYPE=graphql
RECEIVER_TYPE=portal
SCANNER_TYPE=wedge
PRINTER_TYPE=zebra
```

Fill in all `SOURCE_*`, `SINK_*`, and `RECEIVE_*` settings with real values, then re-run
`receiving-refresh` to confirm a live catalog load.

---

## 4. Daily start sequence

### Step 1 — Refresh the catalog

Every morning, fetch the latest open orders from the purchase-order portal
and rebuild the local inventory catalog:

```
receiving-refresh
```

The application prints a confirmation prompt:

```
============================================================
  Catalog Refresh — wipe and rebuild from open orders
============================================================
Type YES to confirm wipe and rebuild:
```

Type `YES` (uppercase) and press Enter to proceed. Anything else cancels
without touching the database.

On success you will see:

```
Refresh complete — 342 items in catalog.
```

**Safety stop:** if the portal is unreachable or the login fails, the fetch
fails before any data is written. The existing catalog is left intact — no
records are lost on a failed refresh. Fix the problem (see
[Failure scenarios](#failure-scenarios) below) and re-run.

### Step 2 — Verify the item count

The printed item count should be consistent with the previous day's volume.
A count of single digits when you expect hundreds suggests a fetch or filter
problem — do not start scanning until you investigate.

### Step 3 — Start the scanner and/or robot

See the sections below for each mode.

---

## 5. Scanner desk operation

Launch the scanner UI:

```
receiving-app
```

### Scan flow

1. Enter or scan the purchase order number into the PO field, then press
   Enter or click Load. The application loads the PO from the local catalog.
2. Scan the **model barcode**. The application enters the matching state.
3. Scan the **serial number barcode**. The application matches the unit,
   claims the inventory slot to prevent a duplicate receive, posts the
   outcome to the board, and prints a label on success.

### Switching PO by barcode

A barcode prefixed `PO:` — for example, `PO:12345` — switches the locked
purchase order without triggering a model match. Use this when the box label
encodes the PO number as a barcode.

### Outcome indicators

- **Green flash** — unit received and label printed.
- **Red flash** — no match found, or label printer error. Check the status
  panel on the right for details.

### Claimed slots

Each inventory slot is marked as claimed when matched, preventing the same
unit from being received twice. If the application exits mid-scan, a claim
may remain set. On the next run, that slot will be skipped. To clear a stuck
claim, set `claimed_at = NULL` for the affected row in the
`receiving_inventory` table of the SQLite database at `DB_PATH`.

---

## 6. Receiving robot operation

The robot works through the board automatically without a screen. Launch it:

```
receiving-robot
```

Press **Ctrl+C** to stop cleanly.

### What happens each pass

1. The robot fetches all items from the board's READY group.
2. Each item is checked for required fields (PO number, inventory ID, model,
   serial). Items with missing fields are moved to NO_MATCH immediately.
3. For each valid item, the robot opens the portal receiving wizard, finds
   the model row, enters the serial number, and completes the receipt.
4. On success: the item moves to RECEIVED.
5. On no-match or wizard error: the item moves to NO_MATCH.
6. The robot sleeps `POLL_INTERVAL_SECS` seconds and repeats.

### Board group meanings

| Group | Meaning |
|---|---|
| READY | Item is queued — the robot will attempt it next pass |
| RECEIVED | Portal wizard completed — item fully received |
| NO_MATCH | Model not found in the receiving grid, or a required field was missing |

### Items that error

If the portal crashes mid-item or an unexpected error occurs, the item is
**not moved** — it stays in READY and is retried on the next pass.

### Circuit breaker (kill switch)

If fewer than 50 % of attempts in a single pass succeed (after at least 5
attempts), the robot logs `robot_kill` and stops. This prevents a run of
bad data from making dozens of failed portal requests. Restart the robot
after you have investigated.

---

## 7. Reading the log

Logs are written to `LOG_DIR/receiving_app.log`. The file rotates at midnight
and the last 30 days are kept.

Key log lines:

| Log key | Level | Meaning |
|---|---|---|
| `robot_start poll_interval_secs=N` | INFO | Robot launched |
| `receive_loop_start ready=N` | INFO | Pass started; N items in READY |
| `receive_loop_complete rcvd=N skipped=N` | INFO | Clean pass — all items received |
| `receive_loop_partial rcvd=N no_match=N failed=N skipped=N` | WARN | Some items did not receive |
| `pass_complete rcvd=N no_match=N failed=N skipped=N` | INFO | Runner-level pass summary |
| `receive_loop_kill rcvd=N attempted=N` | ERROR | Circuit breaker tripped |
| `robot_kill msg=...` | ERROR | Robot stopped by circuit breaker |
| `robot_pass_error` | ERROR | Unhandled exception this pass (robot retries next pass) |
| `robot_shutdown` | INFO | Robot stopped cleanly by Ctrl+C |

The robot also saves step-by-step screenshots from the receiving wizard to
`RECEIVE_SCREENSHOT_DIR` (default: `LOG_DIR/screenshots`). Each screenshot is
named `{inventory_id}_{step}.png`. These are the first thing to check when a
specific item fails.

---

## Failure scenarios

### 1. Portal login fails during refresh or robot pass

**Symptom:** an exception trace in the terminal (for `receiving-refresh`) or a
`robot_pass_error` line in the log (for the robot). The traceback will mention
"login", "networkidle", `SourceError`, or `ExecutorError`. The database is not
modified; the robot retries next pass.

**Check:**
- The portal URL is reachable from this machine.
- `SOURCE_USERNAME` and `SOURCE_PASSWORD` in `.env` are correct and the
  account is not locked.
- If the portal URL has changed, update `SOURCE_BASE_URL` in `.env`.

**Action:** fix credentials or connectivity, then restart the command.

---

### 2. Catalog refresh fetch fails — database not wiped

**Symptom:** `receiving-refresh` exits with an exception trace before printing
"Refresh complete". The existing catalog is intact.

**Why:** the application uses a fetch-first safety contract — the catalog is
only replaced after a successful fetch. A failed or empty fetch never empties
the database.

**Check:** same as scenario 1 (portal reachable, credentials valid).

**Action:** resolve the connectivity or login issue, then re-run
`receiving-refresh`.

---

### 3. Robot kill switch trips (`robot_kill` in log)

**Symptom:** the robot stops mid-run. The log shows a `robot_kill` line with
`rcvd=N attempted=M` where `N/M < 0.5`.

**Check:**
- Review `receive_loop_partial` and `receive_executor_error` lines above the
  kill line to identify which items failed.
- Check the screenshots in `RECEIVE_SCREENSHOT_DIR` for the failing inventory
  IDs.
- Common causes: portal session expired, receiving grid layout changed, model
  name on the board does not match any row in the portal's receiving grid.

**Action:** resolve the root cause, correct or move stuck items on the board,
then restart `receiving-robot`.

---

### 4. Item lands in NO_MATCH

**Symptom:** an item appears in the NO_MATCH board group instead of RECEIVED.

**Check:** the log will show a `receive_loop_partial` line with `no_match > 0`.
Check the screenshots for that inventory ID (steps `04a_grid_before_search` and
`04_qty_set`) to see whether the model row was found.

**Causes:**
- The model string on the board item does not fuzzy-match any row in the
  receiving grid (match threshold is 0.85). Update the model field on the
  board item to match the portal's exact spelling.
- All grid rows for that model have TBR quantity = 0 (already fully received).
  Verify in the portal.
- A required field (PO number, inventory ID, model, or serial) is blank on the
  board item — the robot moves these to NO_MATCH without attempting the portal.

**Action:** correct the board item data and move it back to READY, or close
the item if the unit is genuinely not on the PO.

---

### 5. Zebra printer is offline or not found

**Symptom:** the scanner UI shows a "print_failed" status (red). The receiving
record has already been saved in the database and posted to the board —
only the label print failed.

**Check:**
- `PRINTER_TYPE` in `.env` is set to `zebra`.
- The printer is powered on, connected, and the driver is installed.
- As a temporary workaround, set `PRINTER_TYPE=preview` — the label will
  open in a browser window instead of printing.

**Action:** fix the printer. You can re-print the label by re-scanning the
same barcode sequence — the receive record is idempotent (the database will
not create a duplicate entry). Verify that your board deduplicates re-posts
before doing this in a live environment.

---

### 6. `PRINTER_TYPE` rejected at startup

**Symptom:** The application fails to start with a config validation error:
```
PRINTER_TYPE — got 'fake', must be one of ['preview', 'zebra'].
```

**Cause:** `PRINTER_TYPE` only accepts `preview` or `zebra`. There is no `fake` value —
use `preview` (opens a browser window) during development and testing.

**Action:** Set `PRINTER_TYPE=preview` in `.env`.

---

### 7. Sink returns 401 Unauthorized

**Symptom:** `receiving-app` or `receiving-robot` raises a 401 error when posting results
to the board.

**Check:**
- `SINK_BASE_URL` must be the **API endpoint**, not the web board URL.
  For example, `https://api.your-board-provider.com/v2` — not `https://your-board-provider.com/boards/12345`.
  The web URL will always return 401 when used as an API endpoint.
- `SINK_API_TOKEN` must be a valid API token, not a user password.

**Action:** Correct `SINK_BASE_URL` and `SINK_API_TOKEN` in `.env`.

---

### 8. Zebra printer not found

**Symptom:** The scanner UI shows `print_failed` in the status panel. The log shows a
`print_error` line with a message like "no Zebra printer found".

**Cause:** The printer adapter searches for an installed printer whose driver name contains
certain keywords. If the installed Windows printer name does not contain those keywords, the
printer is not found.

**Check:**
- Open **Settings → Bluetooth & devices → Printers & scanners** on the receiving machine.
- Note the exact driver name shown for the Zebra printer.

**Action:** If the driver name does not match, this currently requires a code change —
the search list is hardcoded (tracked as DEBT-PRINTER-001). As a temporary workaround,
set `PRINTER_TYPE=preview` to continue receiving while the search list is updated.
The receiving record is already saved; the only thing that failed was the label print.

---

### 9. Config validation errors at startup

**Symptom:** The application refuses to start and prints a list of problems, for example:
```
Configuration invalid — fix these in .env before starting:
  DB_PATH — required but not set. See .env.example for description.
  SINK_BOARD_ID — required but not set. See .env.example for description.
```

**Action:** Each line names the exact variable that is missing or invalid. Open `.env`,
locate each listed variable, and fill in or correct its value. Re-run the command —
validation runs again on every start.

---

### 10. `receiving-app` ImportError on an old checkout

**Symptom:** Running `receiving-app` raises:
```
ImportError: No module named '__main__'
```

**Cause:** This was a known issue on checkouts before PR #28. The entry point was renamed
from `__main__` to `scanner_runner`.

**Action:** Pull the latest code and re-run `pip install -e ".[dev]"`.

---

### 11. Scanner reads the wrong PO (locked to wrong purchase order)

**Symptom:** scans are matched against the wrong purchase order; labels print
with an incorrect PO number.

**Check:** the PO number shown in the top-left of the scanner UI.

**Action (two options):**
1. Type the correct PO number into the PO field and press Enter.
2. Scan a barcode prefixed `PO:` — for example, `PO:98765` — to switch the
   locked purchase order without triggering a model match.
