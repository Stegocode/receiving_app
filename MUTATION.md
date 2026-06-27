# Accepted Equivalent Mutants

Mutation score after fix/exact-model-match (T2b): **79.2%** (850 killed / 223 survived / 1073 checked / 0 not_checked).

> **Gate was previously non-functional** (fixed in fix/mutation-gate-integrity, PR #60):
> `[tool.mutmut] also_copy` omitted `"schema"`, so DB-backed tests failed inside the
> mutant sandbox with "no such table: barcode_model_map", leaving all mutants "not
> checked". The old CI scorer counted `None` exit codes as killed and `mutmut run || true`
> hid the crash — every run reported 100% while checking nothing.
> Fixed: `"schema"` added to `also_copy`; scorer rewritten; `|| true` removed.

T2b code changes that shift the mutant pool: deleted `find_best_match`, `match_score`,
`normalize`, `strip_ean14`, `_norm_model`, and the `difflib` import from
`core/matching.py`; added `exact_model_match` and `resolve_exact` (both using the
shared `normalize_key` canonical normalizer from T2a/PR #60). Pool size and score
are updated from the real T2b run below.

The score is approximate and drifts run-to-run because some mutants are killed by
timeout rather than assertion, making it sensitive to runner speed; the durable
invariants the gate enforces are **score >= 78%** and **not_checked == 0**.
The CI gate is set at **78%** — the threshold must not be softened.

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
| x_process_scan__mutmut_16 (was recv_ps_13) | `next(..., None)` → `next(..., )` — default is unreachable: when `best_model` is truthy it was returned by `resolve_exact` from the deduplicated candidates list, so the generator always yields a result before exhaustion. |
| recv_dup_br_1 | `claimed_row.get("model_number", barcode)` → `…get("model_number", None)` — default unreachable: `claimed_row` is found via `next(c for c in claimed if c["model_number"] == barcode)`, so it always has `"model_number"`. The `barcode` fallback is defensive dead code. |
| recv_dup_br_2 | `claimed_row.get("model_number", barcode)` → `…get("model_number", )` — same reasoning as recv_dup_br_1; default argument omitted but also unreachable. |
| recv_dup_br_3 | `claimed_row.get("model_number", barcode)` → `…get(None, barcode)` — key mutated to None; `.get(None, barcode)` returns `barcode`, which equals `claimed_row["model_number"]` by the exact-match invariant (`c["model_number"] == barcode` was the selection criterion). Observable value identical. |
| recv_dup_br_4 | `claimed_row.get("model_number", barcode)` → `…get("XXmodel_numberXX", barcode)` — garbled key; fallback returns `barcode` = `model_number` (same as recv_dup_br_3 reasoning). |
| recv_dup_br_5 | `claimed_row.get("model_number", barcode)` → `…get("MODEL_NUMBER", barcode)` — wrong-case key; dict keys are lowercase, fallback returns `barcode` = `model_number` (same reasoning). |

---

## Category G: Exact-match normalizer case direction (T2b addition)

| Mutant ID | Description |
|-----------|-------------|
| x__norm_model__mutmut_9 | `s.upper()` → `s.lower()` in `_norm_model` — both sides of every comparison go through `_norm_model`, so uppercasing and lowercasing are equivalent: the normalized forms always agree. Observable only if a caller compared one normalized string against a hardcoded case-literal, which nothing does. |
| x_resolve_model__mutmut_13 | `candidates=[]` → `` (omit kwarg) in `MatchResult(AUTO, ...)` — `candidates` has `field(default_factory=list)` whose value is `[]`; passing `candidates=[]` explicitly and omitting it are identical. |

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

---

## Category G: Two-tier resolver equivalents (core/matching.py — PR 2a)

Two survivors from the two-tier resolver are unkillable without testing implementation
rather than behavior.

| Mutant | Mutation | Why equivalent |
|--------|----------|----------------|
| normalize_key (case) | `s.lower()` → `s.upper()` | `normalize_key` is only ever called to compare two keys for equality (`normalize_key(m) == barcode_key`). Uppercasing both sides produces identical comparisons — no observable difference. |
| resolve_model AUTO branch | `candidates=[]` omitted | `MatchResult.candidates` defaults to `field(default_factory=list)`, so omitting the kwarg yields an identical empty list. Any test asserting `r.candidates == []` passes either way. |
| resolve_model PROPOSE branch | `candidates=[]` omitted | Same reasoning as the AUTO branch — `MatchResult.candidates` defaults to `[]`, so the kwarg is redundant. Identical observable behavior. |
