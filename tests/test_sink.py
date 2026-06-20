"""
Owns: tests for ResultSinkAdapter and FakeResultSink.
Must not: make real API calls or import adapters.db or adapters.source.
May import: pytest, unittest.mock, adapters.sink, tests.fakes.fake_sink,
            core.ports, core.errors, core.schema.

not_measured: real board API calls, real group mutations, rate-limiting behavior,
              token expiry, board permission errors, item creation side-effects.
              See DEBT.md [DEBT-T09-001].
"""

import logging
from unittest.mock import MagicMock

import pytest

from adapters.sink import ResultSinkAdapter
from core.errors import SinkError
from core.ports import ResultSink
from core.schema import ReceivingRecord
from tests.fakes.fake_sink import FakeResultSink

# ── Fixture helpers ───────────────────────────────────────────────────────────


def _make_record(receiving_id: str = "rid-001", match_status: str = "received") -> ReceivingRecord:
    return ReceivingRecord(
        truck="T1",
        stop="S1",
        sales_order="SO-001",
        model_number="MDL-A",
        product_category="Furniture",
        product_size={"w": 10.0, "d": 20.0, "h": 30.0},
        quantity=1,
        receiving_id=receiving_id,
        timestamp="2026-06-19T10:00:00",
        match_status=match_status,
        purchase_order="PO-001",
        inventory_id="INV-001",
    )


def _make_adapter() -> ResultSinkAdapter:
    return ResultSinkAdapter(
        base_url="https://api.example.com/v2",
        api_token="tok",
        board_id="board123",
        received_group_id="grp_recv",
        no_match_group_id="grp_nm",
        attention_group_id="grp_att",
    )


def _mock_response(data: dict) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = data
    return resp


def _ok_response() -> MagicMock:
    return _mock_response({"data": {"create_item": {"id": "item-1"}}})


# ── FakeResultSink tests ──────────────────────────────────────────────────────


def test_fake_satisfies_protocol():
    assert isinstance(FakeResultSink(), ResultSink)


def test_fake_emit_idempotent():
    """PASS: emit twice with same receiving_id → len(emitted) == 1."""
    fake = FakeResultSink()
    r = _make_record("rid-001", "received")
    fake.emit(r)
    fake.emit(r)
    assert len(fake.emitted) == 1


def test_fake_surface_attention_idempotent():
    """PASS: surface_attention twice with same receiving_id → len(attention) == 1."""
    fake = FakeResultSink()
    r = _make_record("rid-002", "needs_attention")
    fake.surface_attention(r)
    fake.surface_attention(r)
    assert len(fake.attention) == 1


def test_fake_seen_is_shared_across_emit_and_attention():
    """emit then surface_attention on same id → attention remains empty."""
    fake = FakeResultSink()
    r = _make_record("rid-003", "received")
    fake.emit(r)
    fake.surface_attention(r)
    assert len(fake.emitted) == 1
    assert len(fake.attention) == 0


def test_fake_different_ids_both_recorded():
    fake = FakeResultSink()
    fake.emit(_make_record("rid-001", "received"))
    fake.emit(_make_record("rid-002", "no_match"))
    assert len(fake.emitted) == 2


# ── ResultSinkAdapter — protocol and idempotency ──────────────────────────────


def test_adapter_satisfies_protocol():
    assert isinstance(_make_adapter(), ResultSink)


def test_adapter_emit_idempotent_second_call_skips_api(monkeypatch):
    """Second emit with same receiving_id must not call requests.post."""
    adapter = _make_adapter()
    call_count = 0

    def fake_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return _ok_response()

    monkeypatch.setattr("adapters.sink.requests.post", fake_post)
    adapter.emit(_make_record("rid-001", "received"))
    adapter.emit(_make_record("rid-001", "received"))
    assert call_count == 1


def test_adapter_surface_attention_idempotent_second_call_skips_api(monkeypatch):
    adapter = _make_adapter()
    call_count = 0

    def fake_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return _ok_response()

    monkeypatch.setattr("adapters.sink.requests.post", fake_post)
    adapter.surface_attention(_make_record("rid-001", "needs_attention"))
    adapter.surface_attention(_make_record("rid-001", "needs_attention"))
    assert call_count == 1


# ── ResultSinkAdapter — group routing ────────────────────────────────────────


def test_adapter_emit_received_routes_to_received_group(monkeypatch):
    adapter = _make_adapter()
    captured: dict = {}

    def fake_post(url, json, headers, timeout):
        captured["groupId"] = json["variables"]["groupId"]
        return _ok_response()

    monkeypatch.setattr("adapters.sink.requests.post", fake_post)
    adapter.emit(_make_record("rid-001", "received"))
    assert captured["groupId"] == "grp_recv"


def test_adapter_emit_no_match_routes_to_no_match_group(monkeypatch):
    adapter = _make_adapter()
    captured: dict = {}

    def fake_post(url, json, headers, timeout):
        captured["groupId"] = json["variables"]["groupId"]
        return _ok_response()

    monkeypatch.setattr("adapters.sink.requests.post", fake_post)
    adapter.emit(_make_record("rid-001", "no_match"))
    assert captured["groupId"] == "grp_nm"


def test_adapter_surface_attention_routes_to_attention_group(monkeypatch):
    adapter = _make_adapter()
    captured: dict = {}

    def fake_post(url, json, headers, timeout):
        captured["groupId"] = json["variables"]["groupId"]
        return _ok_response()

    monkeypatch.setattr("adapters.sink.requests.post", fake_post)
    adapter.surface_attention(_make_record("rid-001", "needs_attention"))
    assert captured["groupId"] == "grp_att"


# ── ResultSinkAdapter — error wrapping ───────────────────────────────────────


def test_adapter_request_exception_raises_sink_error(monkeypatch):
    import requests as req_lib

    adapter = _make_adapter()

    monkeypatch.setattr(
        "adapters.sink.requests.post",
        lambda *a, **kw: (_ for _ in ()).throw(req_lib.RequestException("timeout")),
    )
    with pytest.raises(SinkError) as exc_info:
        adapter.emit(_make_record("rid-001", "received"))
    assert isinstance(exc_info.value.__cause__, req_lib.RequestException)


def test_adapter_graphql_errors_raises_sink_error(monkeypatch):
    adapter = _make_adapter()

    monkeypatch.setattr(
        "adapters.sink.requests.post",
        lambda *a, **kw: _mock_response({"errors": [{"message": "bad token"}]}),
    )
    with pytest.raises(SinkError):
        adapter.emit(_make_record("rid-001", "received"))


def test_adapter_non2xx_response_raises_sink_error_with_cause(monkeypatch):
    """raise_for_status on a non-2xx status must surface as SinkError with HTTPError chained."""
    import requests as req_lib

    adapter = _make_adapter()
    http_error = req_lib.HTTPError("500 Server Error")
    resp = MagicMock()
    resp.raise_for_status.side_effect = http_error

    monkeypatch.setattr("adapters.sink.requests.post", lambda *a, **kw: resp)
    with pytest.raises(SinkError) as exc_info:
        adapter.emit(_make_record("rid-001", "received"))
    assert exc_info.value.__cause__ is http_error


# ── ResultSinkAdapter — audit logging ────────────────────────────────────────


def test_adapter_emit_writes_before_and_after_audit_entries(
    monkeypatch, caplog: pytest.LogCaptureFixture
):
    """Actual transition must produce exactly two log entries: before and after."""
    adapter = _make_adapter()
    monkeypatch.setattr("adapters.sink.requests.post", lambda *a, **kw: _ok_response())

    with caplog.at_level(logging.INFO, logger="adapters.sink"):
        adapter.emit(_make_record("rid-001", "received"))

    messages = [r.getMessage() for r in caplog.records]
    assert any('"stage": "before"' in m for m in messages)
    assert any('"stage": "after"' in m for m in messages)


def test_adapter_noop_produces_no_audit_entries(monkeypatch, caplog: pytest.LogCaptureFixture):
    """Second emit with same receiving_id must produce zero log entries."""
    adapter = _make_adapter()
    monkeypatch.setattr("adapters.sink.requests.post", lambda *a, **kw: _ok_response())

    with caplog.at_level(logging.INFO, logger="adapters.sink"):
        adapter.emit(_make_record("rid-001", "received"))
        count_after_first = len(caplog.records)
        adapter.emit(_make_record("rid-001", "received"))
        count_after_second = len(caplog.records)

    assert count_after_first == 2  # before + after
    assert count_after_second == 2  # no new entries on no-op


def test_adapter_audit_entry_contains_receiving_id(monkeypatch, caplog: pytest.LogCaptureFixture):
    adapter = _make_adapter()
    monkeypatch.setattr("adapters.sink.requests.post", lambda *a, **kw: _ok_response())

    with caplog.at_level(logging.INFO, logger="adapters.sink"):
        adapter.emit(_make_record("rid-unique-99", "received"))

    combined = " ".join(r.getMessage() for r in caplog.records)
    assert "rid-unique-99" in combined
