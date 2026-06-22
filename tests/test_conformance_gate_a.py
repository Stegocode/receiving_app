"""
Owns: regression tests for conformance gate_a — banned-term loader, matching, and scan.
Must not: perform I/O against git; must not import adapters;
          must not call conformance.tracked_files() or use real banned terms.
May import: pytest, pathlib.Path, conformance (banned_name_hit, _load_banned_terms,
            gate_a, FAILURES); monkeypatches conformance.read, conformance._load_banned_terms,
            conformance.ROOT.

not_measured: full gate_a integration against a real git tree.
"""

from pathlib import Path

import conformance
import pytest
from conformance import FAILURES, _load_banned_terms, banned_name_hit, gate_a

# ── fixture ───────────────────────────────────────────────────────────────────


@pytest.fixture
def clean_failures():
    """Clear the conformance FAILURES list before and after each test."""
    FAILURES.clear()
    yield FAILURES
    FAILURES.clear()


# ── banned_name_hit unit tests (fake terms only) ──────────────────────────────


def test_banned_name_hit_exact_in_content():
    assert banned_name_hit("zzztestbanned", "content contains zzztestbanned here", "file.py")


def test_banned_name_hit_case_insensitive_in_content():
    assert banned_name_hit("zzztestbanned", "content has ZZZTESTBANNED in it", "file.py")


def test_banned_name_hit_exact_in_path():
    assert banned_name_hit("zzztestbanned", "", "adapters/zzztestbanned.py")


def test_banned_name_hit_case_insensitive_in_path():
    assert banned_name_hit("zzztestbanned", "", "adapters/ZZZTESTBANNED.py")


def test_banned_name_clean_content_not_flagged():
    assert not banned_name_hit("zzztestbanned", "clean content here", "adapters/sink.py")


def test_banned_name_clean_path_not_flagged():
    assert not banned_name_hit("zzztestbanned", "", "adapters/source.py")


# ── _load_banned_terms tests ──────────────────────────────────────────────────


def test_loader_parses_terms_ignoring_comments_and_blanks(tmp_path, monkeypatch):
    """Loader returns non-blank non-comment lines; skips '#' lines and empty lines."""
    banned_file = tmp_path / ".conformance-banned"
    banned_file.write_text("zzztestbanned\n# this is a comment\n\nfake-vendor\n")
    monkeypatch.setattr(conformance, "ROOT", tmp_path)
    result = _load_banned_terms()
    assert result == ["zzztestbanned", "fake-vendor"]


def test_loader_returns_empty_when_file_absent(tmp_path, monkeypatch):
    """Loader returns [] when .conformance-banned does not exist."""
    monkeypatch.setattr(conformance, "ROOT", tmp_path)
    result = _load_banned_terms()
    assert result == []


# ── gate_a scan tests ─────────────────────────────────────────────────────────


def test_gate_a_flags_content_with_banned_term(monkeypatch, clean_failures):
    """gate_a records a failure when a banned term appears in file content."""
    monkeypatch.setattr(conformance, "_load_banned_terms", lambda: ["zzztestbanned"])
    monkeypatch.setattr(conformance, "read", lambda _path: "content with zzztestbanned inside")
    gate_a([Path("x.py")])
    assert clean_failures, "Expected gate_a to record a failure"


def test_gate_a_failure_message_does_not_echo_term(monkeypatch, clean_failures):
    """gate_a failure message must not reproduce the banned term (public-log safety)."""
    monkeypatch.setattr(conformance, "_load_banned_terms", lambda: ["zzztestbanned"])
    monkeypatch.setattr(conformance, "read", lambda _path: "zzztestbanned")
    gate_a([Path("x.py")])
    assert clean_failures
    assert all("zzztestbanned" not in msg for msg in clean_failures)


def test_gate_a_clean_content_no_failure(monkeypatch, clean_failures):
    """gate_a records no failure when file content contains no banned term."""
    monkeypatch.setattr(conformance, "_load_banned_terms", lambda: ["zzztestbanned"])
    monkeypatch.setattr(conformance, "read", lambda _path: "clean content with no hits")
    gate_a([Path("clean.py")])
    assert not clean_failures


def test_gate_a_skips_when_no_terms_file(monkeypatch, clean_failures):
    """gate_a records no failures and does not error when .conformance-banned is absent."""
    monkeypatch.setattr(conformance, "_load_banned_terms", lambda: [])
    monkeypatch.setattr(conformance, "read", lambda _path: "zzztestbanned")
    gate_a([Path("x.py")])
    assert not clean_failures
