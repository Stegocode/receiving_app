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

```
cp .env.example .env
```

Open `.env` in a text editor and fill every line. The settings are grouped as
follows:

**Paths** — where the application stores its database, logs, and downloads:

| Setting | What it is |
|---|---|
| `DB_PATH` | Path to the SQLite inventory database file |
| `LOG_DIR` | Directory for log files and screenshots |
| `DOWNLOAD_DIR` | Directory for temporary download files |

**Purchase order source** — credentials for the portal that holds open orders:

| Setting | What it is |
|---|---|
| `SOURCE_BASE_URL` | Base URL of the purchase-order portal |
| `SOURCE_USERNAME` | Login username |
| `SOURCE_PASSWORD` | Login password |

**Result sink / board** — connection details for the board where outcomes are posted:

| Setting | What it is |
|---|---|
| `SINK_BASE_URL` | API base URL for the result board |
| `SINK_API_TOKEN` | API authentication token |
| `SINK_BOARD_ID` | ID of the receiving board |

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

**Receiving wizard** — location labels used when the robot completes a receipt:

| Setting | What it is |
|---|---|
| `RECEIVE_LOCATION` | Location label for the receiving wizard |
| `RECEIVE_WHSE_LOCATION` | WHSE location label |

**Optional settings** (defaults shown):

| Setting | Default | What it is |
|---|---|---|
| `POLL_INTERVAL_SECS` | `10` | Seconds the robot sleeps between passes |
| `RECEIVE_SCREENSHOT_DIR` | `LOG_DIR/screenshots` | Where the robot saves step screenshots |

The application checks every required setting on startup and lists any missing
values together so you can fix them all at once.

---

## 3. Daily start sequence

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

## 4. Scanner desk operation

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

## 5. Receiving robot operation

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

## 6. Reading the log

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

### 6. Scanner reads the wrong PO (locked to wrong purchase order)

**Symptom:** scans are matched against the wrong purchase order; labels print
with an incorrect PO number.

**Check:** the PO number shown in the top-left of the scanner UI.

**Action (two options):**
1. Type the correct PO number into the PO field and press Enter.
2. Scan a barcode prefixed `PO:` — for example, `PO:98765` — to switch the
   locked purchase order without triggering a model match.
