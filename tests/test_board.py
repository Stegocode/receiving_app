"""
Owns: tests for BoardApiAdapter, FakeBoard, and make_board factory.
Must not: make real API calls or import adapters.db, adapters.sink, or services.
May import: pytest, unittest.mock, adapters.board, core.ports, core.errors.

not_measured: real board API calls, real group moves, real column mutations,
              pagination with a live cursor, token expiry, board permission errors.
              See DEBT.md [DEBT-T12-001].
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from adapters.board import BoardApiAdapter, FakeBoard, make_board
from core.errors import BoardError
from core.ports import ReceivingBoard

# ── Fixture helpers ───────────────────────────────────────────────────────────

_READY_ITEM = {
    "item_id": "item-42",
    "po_number": "PO-2026-001",
    "inventory_id": "INV-999",
    "model": "Model-X",
    "serial": "SN-12345",
}


def _make_adapter() -> BoardApiAdapter:
    return BoardApiAdapter(
        api_url="https://api.example.com/v2",
        token="tok-test",
        board_id="board-test",
        ready_group_id="grp_ready",
        received_group_id="grp_recv",
        no_match_group_id="grp_nm",
        inventory_id_col="col_inv",
        model_col="col_model",
        serial_col="col_serial",
        status_col="col_status",
    )


def _mock_response(data: dict) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = data
    return resp


def _ok_mutation_response() -> MagicMock:
    return _mock_response({"data": {"move_item_to_group": {"id": "item-42"}}})


def _poll_ready_response(items: list[dict] | None = None, cursor: str | None = None) -> MagicMock:
    """Single-page poll_ready GraphQL response."""
    raw_items = [
        {
            "id": it["item_id"],
            "name": it["po_number"],
            "column_values": [
                {"id": "col_inv", "text": it["inventory_id"]},
                {"id": "col_model", "text": it["model"]},
                {"id": "col_serial", "text": it["serial"]},
            ],
        }
        for it in (items or [_READY_ITEM])
    ]
    data = {
        "data": {"boards": [{"groups": [{"items_page": {"cursor": cursor, "items": raw_items}}]}]}
    }
    return _mock_response(data)


# ── make_board factory ────────────────────────────────────────────────────────


def test_make_board_unknown_type_raises_board_error():
    """Unknown board_type raises BoardError before constructing anything."""
    with pytest.raises(BoardError):
        make_board("rest")


def test_make_board_graphql_returns_board_api_adapter():
    adapter = make_board("graphql")
    assert isinstance(adapter, BoardApiAdapter)


def test_make_board_fake_returns_fake_board():
    board = make_board("fake")
    assert isinstance(board, FakeBoard)


# ── Protocol conformance ──────────────────────────────────────────────────────


def test_board_api_adapter_satisfies_protocol():
    assert isinstance(_make_adapter(), ReceivingBoard)


def test_fake_board_satisfies_protocol():
    assert isinstance(FakeBoard(), ReceivingBoard)


# ── FakeBoard ─────────────────────────────────────────────────────────────────


def test_fake_poll_ready_returns_seeded_items():
    """poll_ready returns the items supplied at construction."""
    board = FakeBoard(ready_items=[_READY_ITEM])
    assert board.poll_ready() == [_READY_ITEM]


def test_fake_poll_ready_returns_copy_not_mutation():
    """Mutating the returned list does not alter the board's internal state."""
    board = FakeBoard(ready_items=[_READY_ITEM])
    result = board.poll_ready()
    result.clear()
    assert board.poll_ready() == [_READY_ITEM]


def test_fake_mark_received_records_item_in_received():
    """mark_received appends item_id to the received list."""
    board = FakeBoard(ready_items=[_READY_ITEM])
    board.mark_received("item-42")
    assert "item-42" in board.received
    assert "item-42" not in board.no_match


def test_fake_mark_no_match_records_item_in_no_match():
    """mark_no_match appends item_id to the no_match list."""
    board = FakeBoard(ready_items=[_READY_ITEM])
    board.mark_no_match("item-42")
    assert "item-42" in board.no_match
    assert "item-42" not in board.received


def test_fake_each_item_lands_in_correct_group():
    """Two items routed separately end up in the right lists."""
    board = FakeBoard(ready_items=[_READY_ITEM, {**_READY_ITEM, "item_id": "item-99"}])
    board.mark_received("item-42")
    board.mark_no_match("item-99")
    assert board.received == ["item-42"]
    assert board.no_match == ["item-99"]


# ── BoardApiAdapter.poll_ready ────────────────────────────────────────────────


def test_adapter_poll_ready_parses_column_values_by_id(monkeypatch):
    """poll_ready maps column_values entries by id into the expected dict shape."""
    adapter = _make_adapter()
    monkeypatch.setattr("adapters.board.requests.post", lambda *a, **kw: _poll_ready_response())
    items = adapter.poll_ready()
    assert items == [_READY_ITEM]


def test_adapter_poll_ready_paginates_when_cursor_present(monkeypatch):
    """poll_ready follows the cursor and returns items from all pages."""
    adapter = _make_adapter()
    item_a = _READY_ITEM
    item_b = {**_READY_ITEM, "item_id": "item-99", "serial": "SN-99999"}

    page1 = _poll_ready_response(items=[item_a], cursor="cur-abc")
    page2_raw = {
        "data": {
            "next_items_page": {
                "cursor": None,
                "items": [
                    {
                        "id": "item-99",
                        "name": "PO-2026-001",
                        "column_values": [
                            {"id": "col_inv", "text": "INV-999"},
                            {"id": "col_model", "text": "Model-X"},
                            {"id": "col_serial", "text": "SN-99999"},
                        ],
                    }
                ],
            }
        }
    }
    page2 = _mock_response(page2_raw)

    call_count = 0

    def fake_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return page1 if call_count == 1 else page2

    monkeypatch.setattr("adapters.board.requests.post", fake_post)
    items = adapter.poll_ready()
    assert len(items) == 2
    assert items[0] == item_a
    assert items[1] == item_b


# ── BoardApiAdapter.mark_received ─────────────────────────────────────────────


def test_adapter_mark_received_moves_to_received_group_then_sets_status(monkeypatch):
    """mark_received: first call moves to received group; second sets status to RECEIVED."""
    adapter = _make_adapter()
    calls: list[dict] = []

    def fake_post(url, json, headers, timeout):
        calls.append(json)
        return _ok_mutation_response()

    monkeypatch.setattr("adapters.board.requests.post", fake_post)
    adapter.mark_received("item-42")

    assert len(calls) == 2
    assert calls[0]["variables"]["itemId"] == "item-42"
    assert calls[0]["variables"]["groupId"] == "grp_recv"
    assert calls[1]["variables"]["itemId"] == "item-42"
    assert calls[1]["variables"]["colId"] == "col_status"
    assert "RECEIVED" in calls[1]["variables"]["value"]


# ── BoardApiAdapter.mark_no_match ─────────────────────────────────────────────


def test_adapter_mark_no_match_moves_to_no_match_group(monkeypatch):
    """mark_no_match sends a single move mutation to the no_match group."""
    adapter = _make_adapter()
    captured: list[dict] = []

    def fake_post(url, json, headers, timeout):
        captured.append(json)
        return _ok_mutation_response()

    monkeypatch.setattr("adapters.board.requests.post", fake_post)
    adapter.mark_no_match("item-42")

    assert len(captured) == 1
    assert captured[0]["variables"]["itemId"] == "item-42"
    assert captured[0]["variables"]["groupId"] == "grp_nm"


# ── Error paths ───────────────────────────────────────────────────────────────


def test_adapter_non2xx_response_raises_board_error_with_cause(monkeypatch):
    """Non-2xx response raises BoardError with the HTTPError chained as cause."""
    import requests as req_lib

    adapter = _make_adapter()
    http_error = req_lib.HTTPError("500 Server Error")
    resp = MagicMock()
    resp.raise_for_status.side_effect = http_error

    monkeypatch.setattr("adapters.board.requests.post", lambda *a, **kw: resp)
    with pytest.raises(BoardError) as exc_info:
        adapter.poll_ready()
    assert exc_info.value.__cause__ is http_error


def test_adapter_graphql_errors_payload_raises_board_error(monkeypatch):
    """A response body containing an 'errors' key raises BoardError.

    The payload includes a valid 'data' structure so the raise is caused by the
    errors-check, not a KeyError from a missing 'data' key.
    """
    adapter = _make_adapter()
    payload = {
        "data": {"boards": [{"groups": [{"items_page": {"cursor": None, "items": []}}]}]},
        "errors": [{"message": "invalid token"}],
    }
    monkeypatch.setattr(
        "adapters.board.requests.post",
        lambda *a, **kw: _mock_response(payload),
    )
    with pytest.raises(BoardError):
        adapter.poll_ready()


def test_adapter_request_exception_raises_board_error_with_cause(monkeypatch):
    """Network-level RequestException is wrapped and chained into BoardError."""
    import requests as req_lib

    adapter = _make_adapter()
    monkeypatch.setattr(
        "adapters.board.requests.post",
        lambda *a, **kw: (_ for _ in ()).throw(req_lib.RequestException("timeout")),
    )
    with pytest.raises(BoardError) as exc_info:
        adapter.poll_ready()
    assert isinstance(exc_info.value.__cause__, req_lib.RequestException)
