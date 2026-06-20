"""
Owns: result sink adapter — posts receiving outcomes to the project management board.
Must not: import core.ports directly — implement the ResultSink protocol concretely.
May import: core.schema, core.errors, requests, logging, json, time.

Crash-safety invariant: a crash at any step in process_scan, on retry, neither
double-emits nor loses the record. The caller guards with was_emitted before calling
emit; this adapter deduplicates on receiving_id via an in-process _seen set.
"""
# Owns: result sink adapter.
# Must not: import core.ports directly; must not read environment variables directly.
# May import: core.schema, core.errors, requests, logging, json, time.

from __future__ import annotations

import json
import logging
import time

import requests

from core.errors import SinkError
from core.schema import ReceivingRecord

# Column IDs on the receiving board — structural constants from the board schema.
_STATUS_COL = "color_mm3yse8h"
_INVENTORY_ID_COL = "text_mm3y7rsn"
_MODEL_COL = "text_mm3yjwhf"

logger = logging.getLogger(__name__)


class ResultSinkAdapter:
    """Result sink backed by the project management board API.

    All credentials, the base URL, and group IDs are injected at construction;
    this class never reads config or environment variables directly.
    """

    def __init__(
        self,
        base_url: str,
        api_token: str,
        board_id: str,
        received_group_id: str,
        no_match_group_id: str,
        attention_group_id: str,
    ) -> None:
        self._base_url = base_url
        self._token = api_token
        self._board_id = board_id
        self._received_group_id = received_group_id
        self._no_match_group_id = no_match_group_id
        self._attention_group_id = attention_group_id
        self._seen: set[str] = set()

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        return {"Authorization": self._token, "Content-Type": "application/json"}

    def _post(self, query: str, variables: dict) -> dict:
        """Execute one GraphQL request; raise SinkError on any failure."""
        try:
            r = requests.post(
                self._base_url,
                json={"query": query, "variables": variables},
                headers=self._headers(),
                timeout=20,
            )
            r.raise_for_status()
        except requests.RequestException as exc:
            raise SinkError(
                "Result sink API request failed — check base URL, connectivity, "
                f"and token. Detail: {exc!r}"
            ) from exc
        try:
            data = r.json()
        except Exception as exc:
            raise SinkError(
                f"Result sink response parse failed — unexpected body. Detail: {exc!r}"
            ) from exc
        if "errors" in data:
            raise SinkError(
                "Result sink returned GraphQL errors — check board ID and token "
                f"scopes. Errors: {data['errors']}"
            )
        return data

    def _create_item(
        self,
        group_id: str,
        record: ReceivingRecord,
        status_label: str,
    ) -> None:
        column_values = json.dumps(
            {
                _INVENTORY_ID_COL: str(record.inventory_id),
                _MODEL_COL: str(record.model_number),
                _STATUS_COL: {"label": status_label},
            }
        )
        mutation = """
        mutation ($boardId: ID!, $groupId: String!, $itemName: String!, $columnValues: JSON!) {
          create_item(board_id: $boardId, group_id: $groupId,
                      item_name: $itemName, column_values: $columnValues) { id }
        }
        """
        self._post(
            mutation,
            {
                "boardId": str(self._board_id),
                "groupId": group_id,
                "itemName": str(record.purchase_order),
                "columnValues": column_values,
            },
        )

    # ── Port interface ─────────────────────────────────────────────────────────

    def emit(self, record: ReceivingRecord) -> None:
        """Create a board item for a completed receiving event.

        Idempotent on receiving_id — a repeat call is a silent no-op.
        Dispatches to the received group (match_status='received') or the
        no-match group (all other statuses).
        """
        if record.receiving_id in self._seen:
            return

        t0 = time.monotonic()
        logger.info(
            json.dumps(
                {
                    "event": "sink_emit",
                    "receiving_id": record.receiving_id,
                    "match_status": record.match_status,
                    "stage": "before",
                    "ms": 0,
                }
            )
        )

        if record.match_status == "received":
            self._create_item(self._received_group_id, record, "RECEIVED")
        else:
            self._create_item(self._no_match_group_id, record, "NO MATCH")

        self._seen.add(record.receiving_id)
        ms = round((time.monotonic() - t0) * 1000)
        logger.info(
            json.dumps(
                {
                    "event": "sink_emit",
                    "receiving_id": record.receiving_id,
                    "match_status": record.match_status,
                    "stage": "after",
                    "ms": ms,
                }
            )
        )

    def surface_attention(self, record: ReceivingRecord) -> None:
        """Create a board item in the attention group for manual review.

        Idempotent on receiving_id — a repeat call is a silent no-op.
        """
        if record.receiving_id in self._seen:
            return

        t0 = time.monotonic()
        logger.info(
            json.dumps(
                {
                    "event": "sink_surface_attention",
                    "receiving_id": record.receiving_id,
                    "match_status": record.match_status,
                    "stage": "before",
                    "ms": 0,
                }
            )
        )

        self._create_item(self._attention_group_id, record, "NEEDS ATTENTION")

        self._seen.add(record.receiving_id)
        ms = round((time.monotonic() - t0) * 1000)
        logger.info(
            json.dumps(
                {
                    "event": "sink_surface_attention",
                    "receiving_id": record.receiving_id,
                    "match_status": record.match_status,
                    "stage": "after",
                    "ms": ms,
                }
            )
        )
