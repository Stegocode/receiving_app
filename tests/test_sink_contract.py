"""
Owns: contract tests for ResultSinkAdapter — pins the GraphQL mutation payload
      shape that the adapter sends to the project-management board API.
Must not: make real API calls, import adapters.db, adapters.source, or services.
May import: pytest, unittest.mock, json, adapters.sink, core.schema, core.errors.

not_measured: live board API calls; real item-creation side-effects; rate limiting;
              token expiry; board permission errors; actual board group membership
              after mutation. These require a live board session. See DEBT.md [DEBT-T09-001].
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from adapters.sink import ResultSinkAdapter
from core.errors import SinkError
from core.schema import ReceivingRecord

# ── Fixture helpers ───────────────────────────────────────────────────────────

_BOARD_ID = "board-123"
_READY_GRP = "grp_ready"
_NM_GRP = "grp_nm"
_ATT_GRP = "grp_att"
_COL_INV = "col_inv"
_COL_MODEL = "col_model"
_COL_SERIAL = "col_serial"
_COL_STATUS = "col_status"


def _make_adapter() -> ResultSinkAdapter:
    return ResultSinkAdapter(
        base_url="https://api.example.com/v2",
        api_token="tok-test",
        board_id=_BOARD_ID,
        ready_group_id=_READY_GRP,
        no_match_group_id=_NM_GRP,
        attention_group_id=_ATT_GRP,
        inventory_id_col=_COL_INV,
        model_col=_COL_MODEL,
        serial_col=_COL_SERIAL,
        status_col=_COL_STATUS,
    )


def _make_record(
    receiving_id: str = "rid-001",
    match_status: str = "received",
    serial: str = "SN-001",
    purchase_order: str = "PO-2026-042",
    inventory_id: str = "INV-777",
    model_number: str = "MDL-Q",
) -> ReceivingRecord:
    return ReceivingRecord(
        truck="TRK-1",
        stop="S1",
        sales_order="SO-001",
        model_number=model_number,
        product_category="Furniture",
        product_size={"w": 10.0, "d": 20.0, "h": 30.0},
        quantity=1,
        receiving_id=receiving_id,
        timestamp="2026-06-25T10:00:00",
        match_status=match_status,
        purchase_order=purchase_order,
        inventory_id=inventory_id,
        serial=serial,
    )


def _ok_response() -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"data": {"create_item": {"id": "item-1"}}}
    return resp


def _capture_post(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Wire a capturing fake_post and return the list it appends to."""
    captured: list[dict] = []

    def fake_post(url: str, **kwargs: object) -> MagicMock:
        captured.append(kwargs["json"])  # type: ignore[arg-type]
        return _ok_response()

    monkeypatch.setattr("adapters.sink.requests.post", fake_post)
    return captured


# ── column_values structure ───────────────────────────────────────────────────


def test_emit_column_values_contains_all_4_configured_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The JSON-encoded column_values must include all 4 configured column IDs.

    If any key is missing the board item is created without that column, silently
    dropping data (inventory_id, model, serial, or status) with no error.
    """
    calls = _capture_post(monkeypatch)
    _make_adapter().emit(_make_record())

    col_values = json.loads(calls[0]["variables"]["columnValues"])
    assert _COL_INV in col_values, "inventory_id_col missing from column_values"
    assert _COL_MODEL in col_values, "model_col missing from column_values"
    assert _COL_SERIAL in col_values, "serial_col missing from column_values"
    assert _COL_STATUS in col_values, "status_col missing from column_values"


def test_emit_inventory_id_col_value_equals_record_inventory_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """inventory_id_col value in column_values is str(record.inventory_id)."""
    calls = _capture_post(monkeypatch)
    _make_adapter().emit(_make_record(inventory_id="INV-EXACT-42"))

    col_values = json.loads(calls[0]["variables"]["columnValues"])
    assert col_values[_COL_INV] == "INV-EXACT-42"


def test_emit_model_col_value_equals_record_model_number(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """model_col value in column_values is str(record.model_number)."""
    calls = _capture_post(monkeypatch)
    _make_adapter().emit(_make_record(model_number="MDL-EXACT-99"))

    col_values = json.loads(calls[0]["variables"]["columnValues"])
    assert col_values[_COL_MODEL] == "MDL-EXACT-99"


# ── item_name and boardId wiring ──────────────────────────────────────────────


def test_emit_item_name_is_purchase_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """The mutation's itemName variable equals the record's purchase_order.

    The board displays this as the item name; if it's wrong the item appears
    under an incorrect PO on the board UI.
    """
    calls = _capture_post(monkeypatch)
    _make_adapter().emit(_make_record(purchase_order="PO-BOARD-DISPLAY"))

    assert calls[0]["variables"]["itemName"] == "PO-BOARD-DISPLAY"


def test_emit_board_id_in_mutation_matches_configured_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """boardId in the mutation variables matches the board_id injected at construction."""
    calls = _capture_post(monkeypatch)
    _make_adapter().emit(_make_record())

    assert calls[0]["variables"]["boardId"] == _BOARD_ID


# ── status label strings ──────────────────────────────────────────────────────


def test_emit_no_match_status_label_is_no_match_with_space(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A no_match record sends status label 'NO MATCH' (with space, not underscore).

    The board automation pattern-matches on this exact string. 'NO_MATCH' (underscore)
    would silently produce a board item with an unrecognised status.
    """
    calls = _capture_post(monkeypatch)
    _make_adapter().emit(_make_record(receiving_id="rid-nm", match_status="no_match"))

    col_values = json.loads(calls[0]["variables"]["columnValues"])
    assert col_values[_COL_STATUS] == {"label": "NO MATCH"}


def test_surface_attention_status_label_is_needs_attention_with_space(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """surface_attention sends status label 'NEEDS ATTENTION' (with spaces).

    Distinct from mark_needs_attention on the board adapter (which sends 'NEEDS_ATTENTION'
    with underscore). The sink uses a human-readable label for the attention column.
    """
    calls = _capture_post(monkeypatch)
    _make_adapter().surface_attention(
        _make_record(receiving_id="rid-att", match_status="needs_attention")
    )

    col_values = json.loads(calls[0]["variables"]["columnValues"])
    assert col_values[_COL_STATUS] == {"label": "NEEDS ATTENTION"}


def test_no_match_and_attention_labels_are_distinct(monkeypatch: pytest.MonkeyPatch) -> None:
    """'NO MATCH' and 'NEEDS ATTENTION' labels are different strings.

    Guards against a refactor that accidentally unifies these two statuses.
    """
    nm_calls = _capture_post(monkeypatch)
    _make_adapter().emit(_make_record(receiving_id="rid-nm2", match_status="no_match"))
    nm_label = json.loads(nm_calls[0]["variables"]["columnValues"])[_COL_STATUS]["label"]

    att_calls = _capture_post(monkeypatch)
    _make_adapter().surface_attention(
        _make_record(receiving_id="rid-att2", match_status="needs_attention")
    )
    att_label = json.loads(att_calls[0]["variables"]["columnValues"])[_COL_STATUS]["label"]

    assert nm_label != att_label


# ── group routing (status label paired with group ID) ─────────────────────────


def test_emit_received_group_id_and_status_label_are_consistent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A received record goes to the ready group with status 'READY' — both at once."""
    calls = _capture_post(monkeypatch)
    _make_adapter().emit(_make_record(receiving_id="rid-recv", match_status="received"))

    col_values = json.loads(calls[0]["variables"]["columnValues"])
    assert calls[0]["variables"]["groupId"] == _READY_GRP
    assert col_values[_COL_STATUS] == {"label": "READY"}


def test_emit_no_match_group_id_and_status_label_are_consistent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A no_match record goes to the no-match group with status 'NO MATCH'."""
    calls = _capture_post(monkeypatch)
    _make_adapter().emit(_make_record(receiving_id="rid-nm3", match_status="no_match"))

    col_values = json.loads(calls[0]["variables"]["columnValues"])
    assert calls[0]["variables"]["groupId"] == _NM_GRP
    assert col_values[_COL_STATUS] == {"label": "NO MATCH"}


def test_surface_attention_group_id_and_status_label_are_consistent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """surface_attention goes to the attention group with status 'NEEDS ATTENTION'."""
    calls = _capture_post(monkeypatch)
    _make_adapter().surface_attention(
        _make_record(receiving_id="rid-att3", match_status="needs_attention")
    )

    col_values = json.loads(calls[0]["variables"]["columnValues"])
    assert calls[0]["variables"]["groupId"] == _ATT_GRP
    assert col_values[_COL_STATUS] == {"label": "NEEDS ATTENTION"}


# ── Fail-closed: GraphQL errors in response raise SinkError ──────────────────


def test_graphql_errors_field_in_response_raises_sink_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A response body containing an 'errors' key raises SinkError (not silent pass)."""

    def fake_post(url: str, **kwargs: object) -> MagicMock:
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"errors": [{"message": "invalid board id"}]}
        return resp

    monkeypatch.setattr("adapters.sink.requests.post", fake_post)
    with pytest.raises(SinkError):
        _make_adapter().emit(_make_record(receiving_id="rid-err"))
