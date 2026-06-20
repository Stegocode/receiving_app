"""
Owns: sync loop — poll pending records and emit them through the ResultSink port.
Must not: import concrete adapters; must not call console prompts or read environment variables.
May import: core.schema, core.errors, core.ports.

PASS criteria:    100% of pending items processed without error.
PARTIAL criteria: success rate >= KILL_THRESHOLD and < 100% — completes, logs warnings.
KILL criteria:    success rate < KILL_THRESHOLD — raises SyncKillError immediately.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from core.errors import SyncKillError
from core.ports import Repository, ResultSink
from core.schema import from_dict

logger = logging.getLogger(__name__)

KILL_THRESHOLD = 0.5


@dataclass
class SyncResult:
    """Operational counters for a single sync pass.

    processed = received + no_match + errors (total items attempted).
    not_measured: real network latency, real sink API responses, SQLite durability.
    """

    processed: int
    received: int
    no_match: int
    errors: int


def _process_item(item: dict, sink: ResultSink, repository: Repository) -> str:
    """Emit one pending item through the sink and mark it emitted.

    Returns match_status on success. Raises on any failure (caller counts errors).
    """
    record = from_dict(item)
    if record.match_status == "needs_attention":
        sink.surface_attention(record)
    else:
        sink.emit(record)
    repository.mark_emitted(record.receiving_id)
    return record.match_status


def sync_pending(repository: Repository, sink: ResultSink) -> SyncResult:
    """Emit all pending records through the sink.

    Returns SyncResult on PASS or PARTIAL. Raises SyncKillError on KILL.
    """
    pending = repository.get_pending()
    received = no_match = errors = 0
    logger.info("sync_loop_start pending=%d", len(pending))

    for item in pending:
        try:
            status = _process_item(item, sink, repository)
            if status == "received":
                received += 1
            else:
                no_match += 1
        except Exception as exc:
            errors += 1
            logger.warning(
                "sync_item_error receiving_id=%s error=%s",
                item.get("receiving_id", "unknown"),
                exc,
            )

    processed = len(pending)
    success_rate = (processed - errors) / processed if processed > 0 else 1.0
    result = SyncResult(processed=processed, received=received, no_match=no_match, errors=errors)

    if success_rate < KILL_THRESHOLD:
        logger.error("sync_loop_kill pd=%d err=%d", processed, errors)
        raise SyncKillError(
            f"sync aborted — {success_rate:.1%} success rate below "
            f"{KILL_THRESHOLD:.1%} threshold; {errors} of {processed} failed"
        )

    if errors > 0:
        logger.warning("sync_partial pd=%d err=%d", processed, errors)
    else:
        logger.info("sync_loop_complete pd=%d ok=%d", processed, received + no_match)

    return result
