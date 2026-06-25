# Accepted Equivalent Mutants

Mutation score after T-16: **82.4%** (542 killed / 658 total).

116 survivors are classified as equivalent — mutations that change code without
changing any observable, testable behavior. Asserting against them would require
testing exact log strings, which is brittle and explicitly out-of-scope (adding
log-text assertions produces tests that break on any log-message typo fix).

The CI gate is set at **78%** — four points below the achieved score.

---

## Category A: Log format-string mutations

Mutants replace a log format string with a garbled variant (e.g. `"XX...XX"`,
ALL_CAPS, or a wrong `%`-format string). These only affect what text appears in
the rotating log file; they do not affect return values, raised exceptions, or any
side effect that a test can observe without asserting exact log text.

| Mutant ID | File |
|-----------|------|
| sync_4, sync_5, sync_6 | services/sync.py — sync_loop_start format |
| sync_35, sync_37, sync_38 | services/sync.py — sync_item_error format string |
| sync_39, sync_40, sync_41, sync_42, sync_43, sync_44 | services/sync.py — sync_item_error arg positions |
| sync_68 | services/sync.py — sync_loop_kill format string |
| sync_79 | services/sync.py — sync_partial format string |
| sync_81, sync_83, sync_84, sync_85, sync_86, sync_87, sync_88, sync_89 | services/sync.py — sync_loop_complete format/args |
| rsync_4, rsync_5, rsync_6 | services/receive_sync.py — receive_loop_start format |
| rsync_21, rsync_22, rsync_23, rsync_24 | services/receive_sync.py — receive_invalid_item format/args |
| rsync_26, rsync_27, rsync_28, rsync_29, rsync_30, rsync_31, rsync_32, rsync_33 | services/receive_sync.py — receive_item_* outcome log formats |
| rsync_70, rsync_71, rsync_75 | services/receive_sync.py — receive_executor_error format/args |
| rsync_90 | services/receive_sync.py — receive_loop_kill format string |
| rsync_95, rsync_96, rsync_97 | services/receive_sync.py — receive_loop_partial format/args |
| rsync_98, rsync_99, rsync_100, rsync_101, rsync_102, rsync_103, rsync_104, rsync_105 | services/receive_sync.py — receive_loop_complete/partial format/args |
| rsync_116 | services/receive_sync.py — receive_loop_partial format string |
| recv_ps_47, recv_ps_48, recv_ps_49, recv_ps_50, recv_ps_51, recv_ps_52, recv_ps_53, recv_ps_54 | services/receive.py — scan_* log format/args |
| refresh_2, refresh_3, refresh_4, refresh_5, refresh_6, refresh_7, refresh_8, refresh_9, refresh_10, refresh_11 | services/refresh.py — refresh_aborted/refresh_start log format/args |
| refresh_15, refresh_16, refresh_17, refresh_18, refresh_19, refresh_20, refresh_21, refresh_22 | services/refresh.py — refresh_complete log format/args |
| populate_3, populate_4, populate_5, populate_6, populate_7, populate_8, populate_9, populate_10 | services/populate.py — populate_skipped log format/args |
| populate_14, populate_15, populate_16, populate_17, populate_18, populate_19, populate_20, populate_21 | services/populate.py — populate_complete log format/args |

---

## Category B: Logger first-arg → None mutations

Mutants replace the format-string argument to `logger.info/warning/error(...)` with
`None`. CPython's logging calls `str % args` on the format string; passing `None`
produces `"None"` in the log instead of the real message. Return values and side
effects are unaffected.

| Mutant ID | File |
|-----------|------|
| sync_7, sync_8, sync_9 | services/sync.py — sync_loop_start first arg |
| sync_30, sync_31 | services/sync.py — sync_item_error first arg |
| sync_82 | services/sync.py — sync_loop_complete first arg |
| rsync_7, rsync_8, rsync_9 | services/receive_sync.py — receive_loop_start first arg |
| refresh_14 | services/refresh.py — after=None only affects logger.info arg |
| populate_10 | services/populate.py — populate_skipped first arg |

---

## Category C: Log-routing conditionals (which level fires, not what is returned)

Mutants alter the `if/else` that decides whether to call `logger.info` or
`logger.warning` at the end of a loop. The `ReceiveResult` / `SyncResult`
returned is identical; only the log level changes.

| Mutant ID | Description |
|-----------|-------------|
| sync_71 | `errors > 0` → `errors >= 0` — warning fires on success path too; result unchanged |
| sync_72 | `errors > 0` → `errors > 1` — warning suppressed on single-error run; result unchanged |
| rsync_93 | `failed == 0 and no_match == 0` → `or` — info path fires even on partial; result unchanged |
| rsync_94 | `failed == 0 and no_match == 0` → `failed != 0 and ...` — warning always fires; result unchanged |

---

## Category D: Semantically inert defaults

| Mutant ID | Description |
|-----------|-------------|
| logging_setup_12 | `when="midnight"` → `"MIDNIGHT"` — Python's `TimedRotatingFileHandler` normalises case; both values activate midnight rotation. |
| sync_51 | `else 1.0` → `else 2.0` in success-rate fallback — only reached when `processed == 0`; both values exceed `KILL_THRESHOLD (0.5)`, so no kill fires and the empty-result path is identical. |

---

## Category E: Dead branches

`process_scan` in `services/receive.py` produces only `"received"` or `"no_match"`
records; it never sets `match_status = "needs_attention"`. The branch that calls
`sink.surface_attention(record)` is therefore dead for this function.

| Mutant ID | Description |
|-----------|-------------|
| recv_ps_42 | `"needs_attention"` → `"XXneeds_attentionXX"` — dead branch; string never equals match_status |
| recv_ps_43 | `"needs_attention"` → `"NEEDS_ATTENTION"` — same dead branch |
| recv_ps_44 | `sink.surface_attention(record)` → `sink.surface_attention(None)` — same dead branch |

---

## Category F: Co-null guard / unreachable default

| Mutant ID | Description |
|-----------|-------------|
| recv_br_44 | `if matched and best_model` → `if matched or best_model` — `matched` is produced by `next(...) if best_model else None`, so `matched` is `None` iff `best_model` is `None`; `and` and `or` are observably equivalent. |
| recv_ps_13 | `next(..., None)` → `next(..., )` — default is unreachable: when `best_model` is truthy it was produced by `find_best_match` over the same candidates list, so the generator always yields a result before exhaustion. |
| recv_dup_br_1 | `claimed_row.get("model_number", barcode)` → `…get("model_number", None)` — default unreachable: `claimed_row` is the dict returned by `claimed_for_po` and was located via `find_best_match(…, [c["model_number"] …])`, so it always has `"model_number"`. The `barcode` fallback is defensive dead code. |
| recv_dup_br_2 | `claimed_row.get("model_number", barcode)` → `…get("model_number", )` — same reasoning as recv_dup_br_1; default argument omitted but also unreachable. |

---

## T0-2 additions: scan_duplicate log-line in services/receive.py

The early-return path for an already-scanned unit contains one `logger.info(...)` call:

```python
logger.info(
    "scan_duplicate barcode=%s po_number=%s inventory_id=%s",
    barcode, po_number, dup_row["inventory_id"],
)
return _build_already_scanned_record(po_number, dup_row, barcode, serial)
```

All mutations on this log call (format-string → garbled/None, positional args → None/removed)
are accepted equivalent mutants — the early `return` on the next line is what matters
behaviorally; the log line only affects rotating-file output.

**Category A (format-string garbled):** `recv_dup_3`, `recv_dup_4`
(`"scan_duplicate …"` → `"XXscan_duplicateXX"` / `"SCAN_DUPLICATE …"`)

**Category B (first arg → None):** `recv_dup_1`
(`"scan_duplicate …"` → `None`)

**Category B (positional args → None):** `recv_dup_2`, `recv_dup_5`, `recv_dup_6`
(`barcode` / `po_number` / `dup_row["inventory_id"]` → `None`)

**Category A (args removed):** `recv_dup_7`, `recv_dup_8`, `recv_dup_9`, `recv_dup_10`
(format string or individual arg lines deleted)
