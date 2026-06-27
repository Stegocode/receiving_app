"""
Owns: receive loop — poll the board, drive the executor for each ready item, route
      outcomes, apply consecutive-failure escalation policy.
Must not: import concrete adapters; read environment variables; sleep or loop forever.
May import: core.errors, core.ports, core.schema.

PASS criteria:    failed == 0 and no_match == 0 — all items received without error.
PARTIAL criteria: failed > 0 or no_match > 0, no kill triggered — loop completed with warnings.
KILL criteria:    consecutive_failures >= CONSECUTIVE_FAILURE_KILL (2) with no success between
                  — SyncKillError raised immediately; both failing items set to needs_attention.

not_measured: live portal timing, real board API mutations, real browser behavior,
              CONSECUTIVE_FAILURE_KILL threshold tuning against live failure patterns.
              See DEBT.md [DEBT-T14-001, DEBT-T1-4a-001].

Boundary: single-writer; consecutive_failures counter is per-run (starts at 0, not persisted).
          Items are sorted ascending by numeric inventory_id before dispatch — the receiving
          system fills a model's open IDs lowest-first; serial must bind to the correct ID.
          Non-numeric inventory_ids log a warning and sort after all numeric items.
          Manual recovery: operator sets item status back to 'ready' to re-feed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from core.errors import ExecutorError, SyncKillError
from core.ports import ReceivingBoard, ReceivingExecutor, SyncStatusStore
from core.schema import SyncStatusRecord

logger = logging.getLogger(__name__)

CONSECUTIVE_FAILURE_KILL = 2


@dataclass
class ReceiveResult:
    """Operational counters for a single receive pass.

    attempted = received + no_match + failed; skipped items never reached the executor.
    not_measured: live portal/board integration, real browser timing, escalation threshold
                  tuning (see DEBT.md [DEBT-T14-001, DEBT-T1-4a-001]).
    """

    received: int
    no_match: int
    failed: int
    skipped: int


def _is_valid(item: dict) -> bool:
    """Return False if any required field is missing or empty."""
    return all(item.get(k) for k in ("item_id", "po_number", "inventory_id", "model", "serial"))


def _write_status(
    store: SyncStatusStore,
    state: str,
    last_outcome: str,
    consecutive_failures: int,
    stopped_reason: str,
) -> None:
    store.write_sync_status(
        SyncStatusRecord(
            state=state,
            last_outcome=last_outcome,
            consecutive_failures=consecutive_failures,
            stopped_reason=stopped_reason,
            updated_at=datetime.now(UTC).isoformat(),
        )
    )


def receive_pending(
    board: ReceivingBoard,
    executor: ReceivingExecutor,
    sync_status: SyncStatusStore,
) -> ReceiveResult:
    """Poll READY items, sort by numeric inventory_id ascending, and drive the executor.

    The receiving system fills a model's open inventory IDs lowest-first; serials must arrive in
    that same order so each serial binds to the correct ID.  Items whose inventory_id
    cannot be parsed as an integer log a warning and sort after all numeric items.

    PASS:    failed == 0 and no_match == 0 — all items received.
    PARTIAL: failed > 0 or no_match > 0, no kill — loop completed with warnings.
    KILL:    consecutive_failures >= CONSECUTIVE_FAILURE_KILL — SyncKillError raised;
             both failing items marked needs_attention before raise.

    not_measured: live portal timing, real board mutations, real browser behavior,
                  CONSECUTIVE_FAILURE_KILL threshold tuning. See DEBT.md [DEBT-T14-001,
                  DEBT-T1-4a-001].
    """
    items = board.poll_ready()

    def _id_sort_key(item: dict) -> tuple[int, int]:
        raw = item.get("inventory_id", "")
        try:
            return (0, int(raw))
        except (ValueError, TypeError):
            logger.warning(
                "receive_sort_non_numeric_id inventory_id=%r item_id=%s",
                raw,
                item.get("item_id", "unknown"),
            )
            return (1, 0)

    items = sorted(items, key=_id_sort_key)
    received = no_match = failed = skipped = 0
    consecutive_failures = 0
    logger.info("receive_loop_start ready=%d", len(items))
    _write_status(sync_status, "running", "none", 0, "")

    for item in items:
        if not _is_valid(item):
            item_id = item.get("item_id")
            if item_id:
                board.mark_no_match(item_id)
            skipped += 1
            logger.warning("receive_invalid_item item_id=%s", item.get("item_id", "unknown"))
            continue

        item_id = item["item_id"]
        try:
            outcome = executor.receive_item(
                item["po_number"], item["inventory_id"], item["model"], item["serial"]
            )
            if outcome == "received":
                board.mark_received(item_id)
                received += 1
            else:
                board.mark_no_match(item_id)
                no_match += 1
            consecutive_failures = 0
            _write_status(sync_status, "running", "success", 0, "")
        except ExecutorError as exc:
            board.mark_needs_attention(item_id)
            consecutive_failures += 1
            failed += 1
            logger.warning(
                "receive_executor_error item_id=%s consecutive_failures=%d error=%s",
                item_id,
                consecutive_failures,
                exc,
            )
            if consecutive_failures >= CONSECUTIVE_FAILURE_KILL:
                reason = (
                    f"{consecutive_failures} consecutive executor failures — "
                    "resolve automation issue before retrying"
                )
                _write_status(sync_status, "stopped", "kill", consecutive_failures, reason)
                logger.error(
                    "receive_loop_kill consecutive_failures=%d item_id=%s",
                    consecutive_failures,
                    item_id,
                )
                raise SyncKillError(
                    f"receive aborted — {consecutive_failures} consecutive executor failures; "
                    "items set to needs_attention; resolve automation issue before retrying"
                ) from exc
            _write_status(sync_status, "running", "failure", consecutive_failures, "")

    last_outcome = "failure" if failed > 0 else "success"
    _write_status(sync_status, "stopped", last_outcome, consecutive_failures, "")
    if failed == 0 and no_match == 0:
        logger.info("receive_loop_complete rcvd=%d skipped=%d", received, skipped)
    else:
        logger.warning(
            "receive_loop_partial rcvd=%d no_match=%d failed=%d skipped=%d",
            received,
            no_match,
            failed,
            skipped,
        )
    return ReceiveResult(received=received, no_match=no_match, failed=failed, skipped=skipped)
