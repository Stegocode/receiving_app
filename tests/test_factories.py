"""
Owns: tests for make_source() and make_sink() factories.
Must not: construct a live portal session, make real API calls, or import adapters.db.
May import: pytest, adapters.source, adapters.sink, core.errors, pathlib.

not_measured: actual portal scrape; actual API board mutation; FakeSource JSON
              parsing (covered in test_source.py); NullSink log output
              (covered in test_sink.py).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.errors import SinkError, SourceError

# ── make_source ───────────────────────────────────────────────────────────────


def test_make_source_unknown_type_raises():
    """Unknown source_type raises SourceError before constructing anything."""
    from adapters.source import make_source

    with pytest.raises(SourceError, match="SOURCE_TYPE"):
        make_source("bogus", "http://x", "u", "p", Path("/tmp"))


def test_make_source_portal_returns_portal_source(tmp_path):
    """source_type='portal' returns a PortalSource."""
    from adapters.source import PortalSource, make_source

    src = make_source("portal", "http://x", "user", "pass", tmp_path)
    assert isinstance(src, PortalSource)


def test_make_source_fake_returns_fake_source(tmp_path):
    """source_type='fake' returns a FakeSource."""
    from adapters.source import FakeSource, make_source

    src = make_source(
        "fake", "http://x", "user", "pass", tmp_path, fake_data_path=tmp_path / "f.json"
    )
    assert isinstance(src, FakeSource)


# ── make_sink ─────────────────────────────────────────────────────────────────


def test_make_sink_unknown_type_raises():
    """Unknown sink_type raises SinkError before constructing anything."""
    from adapters.sink import make_sink

    with pytest.raises(SinkError, match="SINK_TYPE"):
        make_sink("bogus")


def test_make_sink_null_returns_null_sink():
    """sink_type='null' returns a NullSink."""
    from adapters.sink import NullSink, make_sink

    sink = make_sink("null")
    assert isinstance(sink, NullSink)


def test_make_sink_graphql_returns_result_sink_adapter():
    """sink_type='graphql' returns a ResultSinkAdapter."""
    from adapters.sink import ResultSinkAdapter, make_sink

    sink = make_sink(
        "graphql",
        base_url="http://x",
        api_token="t",
        board_id="b",
        ready_group_id="r",
        no_match_group_id="n",
        attention_group_id="a",
    )
    assert isinstance(sink, ResultSinkAdapter)
