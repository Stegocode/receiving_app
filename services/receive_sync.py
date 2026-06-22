"""
Owns: receive loop — poll the board, drive the executor for each ready item, route
      outcomes, trip the circuit breaker.
Must not: import concrete adapters; read environment variables; sleep or loop forever.
May import: core.errors, core.ports.

PASS criteria:    failed == 0 and no_match == 0 — all items received without error.
PARTIAL criteria: (failed > 0 or no_match > 0) and no kill triggered — completes, logs warnings.
KILL criteria:    received / attempted < RECEIVE_KILL_THRESHOLD after MIN_ATTEMPTS_BEFORE_KILL
                  attempted — SyncKillError raised immediately; remaining items left in READY.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from core.errors import ExecutorError, SyncKillError
from core.ports import ReceivingBoard, ReceivingExecutor

logger = logging.getLogger(__name__)

RECEIVE_KILL_THRESHOLD = 0.5
MIN_ATTEMPTS_BEFORE_KILL = 5


@dataclass
class ReceiveResult:
    """Operational counters for a single receive pass.

    attempted = received + no_match + failed; skipped items never reached the executor.
    not_measured: live portal/board integration, real browser timing, breaker
                  threshold tuning (see DEBT-T14-001).
    """

    received: int
    no_match: int
    failed: int
    skipped: int


def _is_valid(item: dict) -> bool:
    """Return False if any required field is missing or empty."""
    return all(item.get(k) for k in ("item_id", "po_number", "inventory_id", "model", "serial"))


def receive_pending(board: ReceivingBoard, executor: ReceivingExecutor) -> ReceiveResult:
    """Poll READY items and drive the executor for each.

    Returns ReceiveResult on PASS or PARTIAL. Raises SyncKillError on KILL.
    """
    items = board.poll_ready()
    received = no_match = failed = skipped = 0
    logger.info("receive_loop_start ready=%d", len(items))

    try:
        for item in items:
            if not _is_valid(item):
                item_id = item.get("item_id")
                if item_id:
                    board.mark_no_match(item_id)
                skipped += 1
                logger.warning(
                    "receive_invalid_item item_id=%s",
                    item.get("item_id", "unknown"),
                )
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
            except ExecutorError as exc:
                failed += 1
                logger.warning("receive_executor_error item_id=%s error=%s", item_id, exc)

            attempted = received + no_match + failed
            if (
                attempted >= MIN_ATTEMPTS_BEFORE_KILL
                and (received / attempted) < RECEIVE_KILL_THRESHOLD
            ):
                logger.error("receive_loop_kill rcvd=%d attempted=%d", received, attempted)
                raise SyncKillError(
                    f"receive aborted — {received}/{attempted} received, below "
                    f"{RECEIVE_KILL_THRESHOLD:.0%}; remaining items left READY"
                )
    finally:
        executor.close()

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
