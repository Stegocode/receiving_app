"""
Owns: ReceivingBoard implementations — BoardApiAdapter (GraphQL API), FakeBoard
      (in-memory dev/test mode), and make_board() factory.
Must not: import core.ports directly; must not import services, adapters.db,
          or adapters.sink; must not read environment variables directly.
May import: core.errors, requests, logging, json.
"""
# Owns: BoardApiAdapter, FakeBoard, make_board().
# Must not: import core.ports directly; must not import services, adapters.db,
#           adapters.sink; must not read environment variables directly.
# May import: core.errors, requests, logging, json.

from __future__ import annotations

import json
import logging

import requests

from core.errors import BoardError

logger = logging.getLogger(__name__)

# ── GraphQL operation strings ─────────────────────────────────────────────────

_QUERY_READY_FIRST = """
    query ($boardId: ID!, $groupId: String!) {
      boards(ids: [$boardId]) {
        groups(ids: [$groupId]) {
          items_page(limit: 500) {
            cursor
            items { id name column_values { id text } }
          }
        }
      }
    }
"""

_QUERY_READY_NEXT = """
    query ($cursor: String!) {
      next_items_page(cursor: $cursor, limit: 500) {
        cursor
        items { id name column_values { id text } }
      }
    }
"""

_MUTATION_MOVE = """
    mutation ($itemId: ID!, $groupId: String!) {
      move_item_to_group(item_id: $itemId, group_id: $groupId) { id }
    }
"""

_MUTATION_SET_STATUS = """
    mutation ($boardId: ID!, $itemId: ID!, $colId: String!, $value: JSON!) {
      change_column_value(
        board_id: $boardId, item_id: $itemId, column_id: $colId, value: $value
      ) { id }
    }
"""


# ── GraphQL board adapter ─────────────────────────────────────────────────────


class BoardApiAdapter:
    """ReceivingBoard backed by the project management board GraphQL API.

    All credentials, the base URL, board/group/column IDs are injected at
    construction; this class never reads config or environment variables directly.
    Raises BoardError on any network, non-2xx, or GraphQL error response.
    """

    def __init__(
        self,
        api_url: str,
        token: str,
        board_id: str,
        ready_group_id: str,
        received_group_id: str,
        no_match_group_id: str,
        inventory_id_col: str,
        model_col: str,
        serial_col: str,
        status_col: str,
    ) -> None:
        self._api_url = api_url
        self._token = token
        self._board_id = board_id
        self._ready_group_id = ready_group_id
        self._received_group_id = received_group_id
        self._no_match_group_id = no_match_group_id
        self._inventory_id_col = inventory_id_col
        self._model_col = model_col
        self._serial_col = serial_col
        self._status_col = status_col

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        return {"Authorization": self._token, "Content-Type": "application/json"}

    def _post(self, query: str, variables: dict) -> dict:
        """Execute one GraphQL request; raise BoardError on any failure."""
        try:
            r = requests.post(
                self._api_url,
                json={"query": query, "variables": variables},
                headers=self._headers(),
                timeout=20,
            )
            r.raise_for_status()
        except requests.RequestException as exc:
            raise BoardError(
                "Board API request failed — check base URL, connectivity, "
                f"and token. Detail: {exc!r}"
            ) from exc
        try:
            data = r.json()
        except Exception as exc:
            raise BoardError(
                f"Board API response parse failed — unexpected body. Detail: {exc!r}"
            ) from exc
        if "errors" in data:
            raise BoardError(
                "Board API returned GraphQL errors — check board ID and token "
                f"scopes. Errors: {data['errors']}"
            )
        return data

    def _parse_item(self, item: dict) -> dict:
        """Map a board item's column_values list into the ReceivingBoard dict contract."""
        col_map = {cv["id"]: cv["text"] for cv in item.get("column_values", [])}
        return {
            "item_id": item["id"],
            "po_number": item["name"],
            "inventory_id": col_map.get(self._inventory_id_col, ""),
            "model": col_map.get(self._model_col, ""),
            "serial": col_map.get(self._serial_col, ""),
        }

    # ── Port interface ─────────────────────────────────────────────────────────

    def poll_ready(self) -> list[dict]:
        """Fetch all items in the READY group (paginated, up to 500 per page).

        Returns a list of dicts with keys: item_id, po_number, inventory_id,
        model, serial. Raises BoardError on any API or parse failure.
        """
        data = self._post(
            _QUERY_READY_FIRST,
            {"boardId": self._board_id, "groupId": self._ready_group_id},
        )
        try:
            page = data["data"]["boards"][0]["groups"][0]["items_page"]
            items = list(page["items"])
            cursor = page.get("cursor")
        except (KeyError, IndexError, TypeError) as exc:
            raise BoardError(f"Board poll_ready response parse failed: {exc!r}") from exc

        while cursor:
            data = self._post(_QUERY_READY_NEXT, {"cursor": cursor})
            try:
                page = data["data"]["next_items_page"]
                items.extend(page["items"])
                cursor = page.get("cursor")
            except (KeyError, TypeError) as exc:
                raise BoardError(f"Board poll_ready pagination failed: {exc!r}") from exc

        logger.info(json.dumps({"event": "board_poll_ready", "count": len(items)}))
        return [self._parse_item(item) for item in items]

    def mark_received(self, item_id: str) -> None:
        """Move item to RECEIVED group and set status column to RECEIVED.

        Two sequential mutations: move first, then set status.
        Raises BoardError if either mutation fails.
        """
        self._post(_MUTATION_MOVE, {"itemId": item_id, "groupId": self._received_group_id})
        self._post(
            _MUTATION_SET_STATUS,
            {
                "boardId": self._board_id,
                "itemId": item_id,
                "colId": self._status_col,
                "value": json.dumps({"label": "RECEIVED"}),
            },
        )
        logger.info(json.dumps({"event": "board_mark_received", "item_id": item_id}))

    def mark_no_match(self, item_id: str) -> None:
        """Move item to NO MATCH group. Raises BoardError on failure."""
        self._post(_MUTATION_MOVE, {"itemId": item_id, "groupId": self._no_match_group_id})
        logger.info(json.dumps({"event": "board_mark_no_match", "item_id": item_id}))

    def mark_needs_attention(self, item_id: str) -> None:
        """Set item status column to NEEDS_ATTENTION; no group move.

        The board's automation routes the item based on the status value.
        The robot never moves groups on executor failure — board logic handles routing.
        Raises BoardError on failure.
        """
        self._post(
            _MUTATION_SET_STATUS,
            {
                "boardId": self._board_id,
                "itemId": item_id,
                "colId": self._status_col,
                "value": json.dumps({"label": "NEEDS_ATTENTION"}),
            },
        )
        logger.info(json.dumps({"event": "board_mark_needs_attention", "item_id": item_id}))


# ── In-memory fake board ──────────────────────────────────────────────────────


class FakeBoard:
    """In-memory ReceivingBoard for dev and test use.

    Seeded with ready items at construction. poll_ready returns them unchanged.
    mark_received and mark_no_match record each item_id so callers can assert
    the final group destination of each item. No network calls are made.
    """

    def __init__(self, ready_items: list[dict] | None = None) -> None:
        self._ready: list[dict] = list(ready_items or [])
        self.received: list[str] = []
        self.no_match: list[str] = []
        self.needs_attention: list[str] = []

    def poll_ready(self) -> list[dict]:
        return list(self._ready)

    def mark_received(self, item_id: str) -> None:
        self.received.append(item_id)

    def mark_no_match(self, item_id: str) -> None:
        self.no_match.append(item_id)

    def mark_needs_attention(self, item_id: str) -> None:
        self.needs_attention.append(item_id)


# ── Factory ───────────────────────────────────────────────────────────────────


def make_board(
    board_type: str,
    api_url: str = "",
    token: str = "",
    board_id: str = "",
    ready_group_id: str = "",
    received_group_id: str = "",
    no_match_group_id: str = "",
    inventory_id_col: str = "",
    model_col: str = "",
    serial_col: str = "",
    status_col: str = "",
    ready_items: list[dict] | None = None,
) -> BoardApiAdapter | FakeBoard:
    """Construct a ReceivingBoard from a type string.

    Raises BoardError for unknown board_type values, before constructing anything.
    """
    if board_type == "fake":
        return FakeBoard(ready_items)
    if board_type == "graphql":
        return BoardApiAdapter(
            api_url,
            token,
            board_id,
            ready_group_id,
            received_group_id,
            no_match_group_id,
            inventory_id_col,
            model_col,
            serial_col,
            status_col,
        )
    raise BoardError(
        f"Unknown board_type '{board_type}' — supported values: graphql, fake. "
        "Set BOARD_TYPE in .env and restart."
    )
