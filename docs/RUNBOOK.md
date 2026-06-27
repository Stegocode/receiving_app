# Operator Runbook

Daily operating procedures for the warehouse receiving desk and robot.
Keep this document next to the terminal; it is the first thing to read when
something goes wrong.

All file paths are named by their **config variable** (e.g. `LOG_DIR`,
`RECEIVE_SCREENSHOT_DIR`). Actual paths are set in `.env`.

---

## Daily start sequence

1. **Run the catalog refresh** — fetches open orders from the source portal
   and atomically rebuilds the local inventory catalog.

   ```
   receiving-refresh
   ```

   When prompted, type `YES` and press Enter to confirm. Any other input
   cancels without touching the database. The command prints the final item
   count on success:

   ```
   Refresh complete — 342 items in catalog.
   ```

   If the fetch fails (network error, login failure) the database is never
   modified and you will see an exception trace. Retry once the portal is
   reachable.

2. **Verify the count** — the printed item count should be consistent with
   the previous day's volume. An unexpectedly low count (e.g. single digits)
   suggests a fetch or filter problem.

3. **Start the scanner and/or robot** — see the sections below.

---

## Scanner desk operation

Launch the scanner UI:

```
receiving-app
```

**Scan flow:**

1. Enter or scan the purchase order number into the PO field, then press
   Enter or click Load. The application fetches the PO from the local catalog.
2. Scan the **model barcode**. The application enters the matching state.
3. Scan the **serial number barcode**. The application matches the unit,
   claims the inventory slot, posts the outcome to the board, and prints a
   label if the match succeeded.

**Switching PO by barcode:** a barcode prefixed `PO:` (e.g. `PO:12345`)
switches the locked purchase order without triggering a model match. Use this
when a label on the box encodes the PO number.

**Outcome colours:**
- **Green flash** — unit received and label printed.
- **Red flash** — no match found, or label printer error. Check the status log
  in the right panel for details.

**Claims** — each inventory slot is claimed when matched. If the process exits
mid-scan, the claim may remain set. On the next run the slot will be skipped
unless the claim is cleared manually (set `claimed_at = NULL` in the SQLite
database for the affected row in `receiving_inventory`).

---

## Receiving robot operation

Launch the headless robot:

```
receiving-robot
```

Press **Ctrl+C** to stop cleanly.

**What the robot does each pass:**

1. Polls the board's READY group.
2. For each item: validates required fields (PO number, inventory ID, model,
   serial). Items missing any field are moved to NO_MATCH immediately.
3. For each valid item: opens the portal receiving wizard, sets the location
   and WHSE location, finds the model row in the receiving grid, enters the
   serial number, and finalises.
4. On success: moves the board item to RECEIVED.
5. On no-match or wizard error: moves the board item to NO_MATCH.
6. Sleeps `POLL_INTERVAL_SECS` seconds, then repeats.

**Board group meanings:**

| Group | Meaning |
|---|---|
| READY | Item is queued; robot will attempt it next pass |
| RECEIVED | Portal wizard completed; item fully received |
| NO_MATCH | Model not found in the receiving grid, or required field missing |

**Items that error** (e.g. unexpected portal crash) are **not moved** — they
remain in READY and are retried on the next pass.

**Circuit breaker (kill switch):** if fewer than 50 % of attempts succeed
within a single pass (after at least 5 attempts), the robot logs
`robot_kill` and stops. This prevents runaway failures from corrupting board
state. Restart the robot after investigating the root cause.

---

## Reading the log

Logs are written to `LOG_DIR/receiving_app.log`, rotating at midnight with
30 days of retention.

Key log lines (all at INFO unless noted):

| Log key | Level | Meaning |
|---|---|---|
| `robot_start poll_interval_secs=N` | INFO | Robot launched |
| `receive_loop_start ready=N` | INFO | Pass started; N items in READY |
| `receive_loop_complete rcvd=N skipped=N` | INFO | Clean pass (PASS) |
| `receive_loop_partial rcvd=N no_match=N failed=N skipped=N` | WARN | Some items did not receive (PARTIAL) |
| `pass_complete rcvd=N no_match=N failed=N skipped=N` | INFO | Runner-level pass summary |
| `receive_loop_kill rcvd=N attempted=N` | ERROR | Circuit breaker tripped |
| `robot_kill msg=...` | ERROR | Robot stopped by circuit breaker |
| `robot_pass_error` | ERROR | Unhandled exception this pass (robot continues) |
| `robot_shutdown` | INFO | Robot stopped by Ctrl+C |

Step-by-step screenshots from the receiving wizard are written to
`RECEIVE_SCREENSHOT_DIR` (default: `LOG_DIR/screenshots`). Each screenshot is
named `{inventory_id}_{step}.png`. Check these first when a specific item
fails.

---

## Failure scenarios

### 1. Portal login fails during refresh or robot pass

**Symptom:** exception or `SourceError` / `ExecutorError` in the log with
"login" or "networkidle" in the traceback. The refresh exits without touching
the database. The robot logs `robot_pass_error` and retries next pass.

**Check:**
- Portal is reachable from this machine.
- `SOURCE_USERNAME` and `SOURCE_PASSWORD` in `.env` are correct and the
  account is not locked.
- If the portal URL changed, update `SOURCE_BASE_URL` in `.env`.

**Action:** fix credentials or connectivity, then restart.

---

### 2. Catalog refresh fetch fails — database not wiped

**Symptom:** `receiving-refresh` prints an exception trace. The existing
catalog is intact (this is by design — the fetch-first, wipe-second safety
contract means a failed fetch never empties the DB).

**Check:** same as scenario 1 above (portal reachable, credentials valid).

**Action:** resolve the network or login issue, then re-run `receiving-refresh`.

---

### 3. Robot kill switch trips (`robot_kill` in log)

**Symptom:** robot stops mid-run; `robot_kill` line in log with
`rcvd=N attempted=M` where `N/M < 0.5`.

**Check:**
- Review the `receive_loop_partial` or `receive_executor_error` lines above
  the kill line to see which items failed.
- Check screenshots in `RECEIVE_SCREENSHOT_DIR` for the failing inventory IDs.
- Common causes: portal session expired, receiving grid layout changed,
  model mismatch (model in board does not appear in the PO receiving grid).

**Action:** resolve the root cause, move stuck items on the board as needed,
then restart `receiving-robot`.

---

### 4. Item lands in NO_MATCH

**Symptom:** an item appears in the NO_MATCH board group instead of RECEIVED.

**Check:** `receive_loop_partial` log line shows `no_match > 0`. The most
recent screenshot for that inventory ID (step `04a_grid_before_search` and
`04_qty_set`) will show whether the model row was found.

**Causes:**
- Model string in the board item does not exactly match (normalized: uppercase,
  spaces/hyphens stripped) any row in the receiving grid. Update the model
  field on the board item to match the portal's spelling exactly.
- All grid rows for that model have TBR quantity = 0 (already fully received).
  Verify in the portal.
- Required field (PO number, inventory ID, model, or serial) is blank on the
  board item — the robot skips these directly to NO_MATCH.

**Action:** correct the board item data and move it back to READY, or mark it
closed if the unit is genuinely not in the PO.

---

### 5. Zebra printer is offline or not found

**Symptom:** scanner UI shows "print_failed" status (red, no label printed).
The receiving record **is already saved** in the database and posted to the
board — only the label is missing.

**Check:**
- `PRINTER_TYPE` in `.env` is set to `zebra`.
- The printer is powered on, connected, and the driver is installed.
- Run the suite with `PRINTER_TYPE=preview` as a temporary workaround — the
  label will open in a browser window instead.

**Action:** fix the printer, then re-print the label by re-scanning the same
barcode sequence (the record is idempotent — re-scanning posts a duplicate to
the board's deduplication layer but does not create a double DB entry; verify
board behaviour manually).

---

### 6. Scanner reads the wrong PO (locked to wrong purchase order)

**Symptom:** scans are being matched against the wrong purchase order. Labels
print with an incorrect PO number.

**Check:** the PO number shown in the top-left of the scanner UI.

**Action (two options):**
1. Type the correct PO number into the PO field and press Enter.
2. Scan a barcode prefixed `PO:` — for example, `PO:98765` — to switch the
   locked PO without triggering a match.
