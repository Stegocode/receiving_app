"""
Owns: tests for PortalReceiver, FakeReceiver, make_receiver factory, and _model_matches.
Must not: launch a real browser, open a network connection, or import services.
May import: pytest, adapters.receiver, core.ports, core.errors.

not_measured:
    - Live portal login and re-login after session expiry.
    - All 8 wizard steps against the live portal.
    - Location and WHSE dropdown resolution against real option values.
    - Grid row matching with TBR > 0 across real portal pages.
    - Grid pagination against a multi-page receiving grid.
    - Serial entry on the real serial-input page.
    - Finalize-error detection from a live alert-danger element.
    - Browser session reuse across multiple receive_item calls.
    - close() against a real browser (teardown, idempotency with a live browser).
    See DEBT.md [DEBT-T13-001].
"""

from __future__ import annotations

from pathlib import Path

import pytest

from adapters.receiver import FakeReceiver, PortalReceiver, _model_matches, make_receiver
from core.errors import ExecutorError
from core.ports import ReceivingExecutor

# ── Fixture helpers ───────────────────────────────────────────────────────────


def _make_portal_receiver(tmp_path: Path) -> PortalReceiver:
    """Construct a PortalReceiver with dummy args. No browser is launched."""
    return PortalReceiver(
        base_url="http://mock-portal",
        username="test_user",
        password="test_pass",
        location_label="TEST WAREHOUSE",
        whse_label="TEST-WHSE-01",
        screenshot_dir=tmp_path / "screenshots",
        headless=True,
    )


# ── Protocol conformance ──────────────────────────────────────────────────────


def test_portal_receiver_satisfies_protocol(tmp_path: Path):
    """PortalReceiver with dummy args (no browser launched) satisfies ReceivingExecutor."""
    assert isinstance(_make_portal_receiver(tmp_path), ReceivingExecutor)


def test_fake_receiver_satisfies_protocol():
    """FakeReceiver satisfies ReceivingExecutor."""
    assert isinstance(FakeReceiver(), ReceivingExecutor)


# ── make_receiver factory ─────────────────────────────────────────────────────


def test_make_receiver_unknown_type_raises_executor_error_before_constructing():
    """Unknown receiver_type raises ExecutorError before any object is created."""
    with pytest.raises(ExecutorError, match="supported values"):
        make_receiver("rest")


def test_make_receiver_fake_returns_fake_receiver():
    result = make_receiver("fake")
    assert isinstance(result, FakeReceiver)


def test_make_receiver_portal_returns_portal_receiver(tmp_path: Path):
    result = make_receiver("portal", screenshot_dir=tmp_path / "ss")
    assert isinstance(result, PortalReceiver)


# ── FakeReceiver behaviour ────────────────────────────────────────────────────


def test_fake_receiver_returns_configured_outcome_for_inventory_id():
    """receive_item returns the per-inventory_id configured outcome."""
    fake = FakeReceiver(outcomes={"INV-1": "not_found", "INV-2": "finalize_error"})
    assert fake.receive_item("PO-1", "INV-1", "MDL-A", "SN-1") == "not_found"
    assert fake.receive_item("PO-1", "INV-2", "MDL-B", "SN-2") == "finalize_error"


def test_fake_receiver_returns_default_outcome_when_id_not_configured():
    """receive_item falls back to default_outcome for unconfigured inventory IDs."""
    fake = FakeReceiver(default_outcome="received")
    assert fake.receive_item("PO-1", "INV-99", "MDL-X", "SN-X") == "received"


def test_fake_receiver_raise_outcome_raises_executor_error():
    """'raise' outcome causes receive_item to raise ExecutorError."""
    fake = FakeReceiver(outcomes={"INV-ERR": "raise"})
    with pytest.raises(ExecutorError):
        fake.receive_item("PO-1", "INV-ERR", "MDL-X", "SN-X")


def test_fake_receiver_records_all_call_args():
    """Every receive_item call is appended to self.calls as a 4-tuple."""
    fake = FakeReceiver()
    fake.receive_item("PO-1", "INV-A", "MDL-A", "SN-A")
    fake.receive_item("PO-2", "INV-B", "MDL-B", "SN-B")
    assert fake.calls == [
        ("PO-1", "INV-A", "MDL-A", "SN-A"),
        ("PO-2", "INV-B", "MDL-B", "SN-B"),
    ]


def test_fake_receiver_close_sets_closed_flag():
    """close() sets self.closed = True; no browser interaction occurs."""
    fake = FakeReceiver()
    assert not fake.closed
    fake.close()
    assert fake.closed


# ── _model_matches unit tests ─────────────────────────────────────────────────


def test_model_matches_exact_match():
    assert _model_matches("MDL-100", "MDL-100") is True


def test_model_matches_case_and_space_insensitive():
    """Normalization folds case and collapses internal whitespace."""
    assert _model_matches("mdl 100", "MDL  100") is True
    assert _model_matches("MDL-100", "mdl-100") is True


def test_model_matches_near_match_above_threshold():
    """A high-similarity pair (space-collapsed ratio >= 0.85) returns True."""
    # "ABCDEFGHIJ" vs "ABCDEFGHIX" — 9 of 10 chars match; ratio = 0.9
    assert _model_matches("ABCDEFGHIJ", "ABCDEFGHIX") is True


def test_model_matches_clearly_different_returns_false():
    """Unrelated model strings return False."""
    assert _model_matches("TABLE-100", "CHAIR-999") is False


def test_model_matches_empty_strings_return_false():
    """Empty target or cell_text is never a match."""
    assert _model_matches("", "MDL-100") is False
    assert _model_matches("MDL-100", "") is False
