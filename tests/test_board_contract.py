"""
Owns: contract tests for BoardApiAdapter — pins the GraphQL response shape that
      BoardApiAdapter expects from the project-management board API, and the
      mutation payloads it produces for each state transition.
Must not: make real API calls, import adapters.db, adapters.sink, or services.
May import: pytest, unittest.mock, json, adapters.board, core.errors.

not_measured: live board API calls; real group-move behavior; real column mutations;
              pagination with a live cursor; token expiry; board permission errors;
              rate limiting. These require a live board session. See DEBT.md [DEBT-T12-001].
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from adapters.board import BoardApiAdapter
from core.errors import BoardError

# ── Fixture helpers ───────────────────────────────────────────────────────────

_COL_INV = "col_inv"
_COL_MODEL = "col_model"
_COL_SERIAL = "col_serial"
_COL_STATUS = "col_status"
_BOARD_ID = "board-test"
_READY_GRP = "grp_ready"
_RECV_GRP = "grp_recv"
_NM_GRP = "grp_nm"


def _make_adapter() -> BoardApiAdapter:
    return BoardApiAdapter(
        api_url="https://api.example.com/v2",
        token="tok-test",
        board_id=_BOARD_ID,
        ready_group_id=_READY_GRP,
        received_group_id=_RECV_GRP,
        no_match_group_id=_NM_GRP,
        inventory_id_col=_COL_INV,
        model_col=_COL_MODEL,
        serial_col=_COL_SERIAL,
        status_col=_COL_STATUS,
    )


def _ok_response(data: dict) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = data
    return resp


def _poll_response(
    items: list[dict],
    cursor: str | None = None,
) -> MagicMock:
    """Build a well-formed single-page poll_ready GraphQL response."""
    return _ok_response(
        {
            "data": {
                "boards": [
                    {
                        "groups": [
                            {
                                "items_page": {
                                    "cursor": cursor,
                                    "items": items,
                                }
                            }
                        ]
                    }
                ]
            }
        }
    )


def _mutation_ok() -> MagicMock:
    return _ok_response({"data": {"move_item_to_group": {"id": "item-42"}}})


# ── poll_ready: well-formed response shape ────────────────────────────────────


def test_poll_ready_output_dict_has_exactly_5_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """A well-formed poll_ready response produces dicts with exactly 5 keys."""
    raw = [
        {
            "id": "item-1",
            "name": "PO-2026-001",
            "column_values": [
                {"id": _COL_INV, "text": "INV-001"},
                {"id": _COL_MODEL, "text": "MDL-X"},
                {"id": _COL_SERIAL, "text": "SN-123"},
            ],
        }
    ]
    monkeypatch.setattr("adapters.board.requests.post", lambda *a, **kw: _poll_response(raw))
    items = _make_adapter().poll_ready()

    assert len(items) == 1
    assert set(items[0].keys()) == {"item_id", "po_number", "inventory_id", "model", "serial"}


def test_poll_ready_canonical_field_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each source field maps to the correct output key and value."""
    raw = [
        {
            "id": "item-42",
            "name": "PO-9999",
            "column_values": [
                {"id": _COL_INV, "text": "INV-999"},
                {"id": _COL_MODEL, "text": "Model-X"},
                {"id": _COL_SERIAL, "text": "SN-12345"},
            ],
        }
    ]
    monkeypatch.setattr("adapters.board.requests.post", lambda *a, **kw: _poll_response(raw))
    item = _make_adapter().poll_ready()[0]

    assert item["item_id"] == "item-42"
    assert item["po_number"] == "PO-9999"
    assert item["inventory_id"] == "INV-999"
    assert item["model"] == "Model-X"
    assert item["serial"] == "SN-12345"


def test_poll_ready_missing_column_id_defaults_to_empty_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If a configured column ID is absent from column_values, the field defaults to ''.

    This documents the fail-safe behavior when the board API removes or renames a column:
    the adapter returns '' rather than None or raising. Callers should treat '' as
    'column not found' — a separate validation layer should reject it.
    """
    raw = [
        {
            "id": "item-55",
            "name": "PO-5555",
            "column_values": [
                {"id": _COL_INV, "text": "INV-555"},
                # _COL_MODEL and _COL_SERIAL are absent
            ],
        }
    ]
    monkeypatch.setattr("adapters.board.requests.post", lambda *a, **kw: _poll_response(raw))
    item = _make_adapter().poll_ready()[0]

    assert item["model"] == ""
    assert item["serial"] == ""
    assert item["inventory_id"] == "INV-555"


def test_poll_ready_empty_column_values_list_all_fields_default_to_empty_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty column_values list → all 3 column-derived fields are ''."""
    raw = [{"id": "item-66", "name": "PO-6666", "column_values": []}]
    monkeypatch.setattr("adapters.board.requests.post", lambda *a, **kw: _poll_response(raw))
    item = _make_adapter().poll_ready()[0]

    assert item["inventory_id"] == ""
    assert item["model"] == ""
    assert item["serial"] == ""


# ── poll_ready: malformed responses raise BoardError ─────────────────────────


def test_poll_ready_missing_data_key_raises_board_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A response with no 'data' key raises BoardError (not KeyError)."""
    monkeypatch.setattr(
        "adapters.board.requests.post",
        lambda *a, **kw: _ok_response({"totally_wrong": True}),
    )
    with pytest.raises(BoardError):
        _make_adapter().poll_ready()


def test_poll_ready_empty_boards_list_raises_board_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty boards list causes an IndexError that is wrapped as BoardError."""
    monkeypatch.setattr(
        "adapters.board.requests.post",
        lambda *a, **kw: _ok_response({"data": {"boards": []}}),
    )
    with pytest.raises(BoardError):
        _make_adapter().poll_ready()


def test_poll_ready_null_items_page_raises_board_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A null items_page value raises BoardError (not TypeError)."""
    monkeypatch.setattr(
        "adapters.board.requests.post",
        lambda *a, **kw: _ok_response({"data": {"boards": [{"groups": [{"items_page": None}]}]}}),
    )
    with pytest.raises(BoardError):
        _make_adapter().poll_ready()


# ── mark_received: mutation payload shape ─────────────────────────────────────


def test_mark_received_status_value_is_json_encoded_label_dict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The status column value is a JSON-encoded {'label': 'RECEIVED'} dict.

    The board API requires a JSON string for column_value changes. A plain string
    would silently fail or be rejected. This pins the exact encoding.
    """
    calls: list[dict] = []

    def fake_post(url: str, json: dict, headers: dict, timeout: int) -> MagicMock:
        calls.append(json)
        return _mutation_ok()

    monkeypatch.setattr("adapters.board.requests.post", fake_post)
    _make_adapter().mark_received("item-42")

    status_call = calls[1]  # second call sets status
    value_str = status_call["variables"]["value"]
    value = __import__("json").loads(value_str)
    assert value == {"label": "RECEIVED"}


# ── mark_needs_attention: mutation payload shape (no prior coverage) ──────────


def test_mark_needs_attention_sends_exactly_one_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """mark_needs_attention issues exactly 1 GraphQL POST (set-status only; no group move).

    mark_received issues 2 POSTs (move + set-status). mark_needs_attention skips the
    group move and relies on board automation for routing — only 1 mutation allowed.
    """
    calls: list[dict] = []

    def fake_post(url: str, json: dict, headers: dict, timeout: int) -> MagicMock:
        calls.append(json)
        return _mutation_ok()

    monkeypatch.setattr("adapters.board.requests.post", fake_post)
    _make_adapter().mark_needs_attention("item-77")

    assert len(calls) == 1, (
        f"expected 1 POST (status-only), got {len(calls)} — "
        "mark_needs_attention must not issue a group-move mutation"
    )


def test_mark_needs_attention_targets_correct_item_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The mutation targets the item_id passed to mark_needs_attention."""
    captured: list[dict] = []

    def fake_post(url: str, json: dict, headers: dict, timeout: int) -> MagicMock:
        captured.append(json)
        return _mutation_ok()

    monkeypatch.setattr("adapters.board.requests.post", fake_post)
    _make_adapter().mark_needs_attention("item-88")

    assert captured[0]["variables"]["itemId"] == "item-88"


def test_mark_needs_attention_status_value_is_needs_attention_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The status column value encodes {'label': 'NEEDS_ATTENTION'}.

    The board automation routes items based on this exact label string. An incorrect
    label (e.g., 'NEEDS ATTENTION' with a space) would silently leave items unrouted.
    """
    captured: list[dict] = []

    def fake_post(url: str, json: dict, headers: dict, timeout: int) -> MagicMock:
        captured.append(json)
        return _mutation_ok()

    monkeypatch.setattr("adapters.board.requests.post", fake_post)
    _make_adapter().mark_needs_attention("item-99")

    value_str = captured[0]["variables"]["value"]
    value = json.loads(value_str)
    assert value == {"label": "NEEDS_ATTENTION"}


def test_mark_needs_attention_uses_status_col_not_group_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The mutation targets the configured status column, not any group ID."""
    captured: list[dict] = []

    def fake_post(url: str, json: dict, headers: dict, timeout: int) -> MagicMock:
        captured.append(json)
        return _mutation_ok()

    monkeypatch.setattr("adapters.board.requests.post", fake_post)
    _make_adapter().mark_needs_attention("item-100")

    assert captured[0]["variables"]["colId"] == _COL_STATUS
    assert "groupId" not in captured[0]["variables"]
