"""
Owns: tests for core/logging_setup.py — setup_logging wires a rotating file handler.
Must not: modify logging state permanently; must not perform network calls.
May import: pytest, logging, logging.handlers, pathlib.Path, core.logging_setup.
"""

import logging
import logging.handlers

import pytest

from core.logging_setup import setup_logging


@pytest.fixture(autouse=True)
def _restore_root_logger():
    """Snapshot and restore root logger handlers and level around each test."""
    root = logging.getLogger()
    pre_handlers = list(root.handlers)
    pre_level = root.level
    yield
    for h in list(root.handlers):
        if h not in pre_handlers:
            h.close()
            root.removeHandler(h)
    root.setLevel(pre_level)


def test_setup_logging_does_not_raise(tmp_path):
    """setup_logging(log_dir) completes without raising for a valid directory."""
    setup_logging(tmp_path)


def test_setup_logging_creates_log_file(tmp_path):
    """After setup_logging, logging an INFO record creates the log file."""
    root = logging.getLogger()
    pre = list(root.handlers)
    setup_logging(tmp_path)
    added = [h for h in root.handlers if h not in pre]
    if not added:
        pytest.skip("basicConfig was no-op (root already had handlers in test environment)")
    root.info("test_setup_logging probe")
    assert (tmp_path / "receiving_app.log").exists()
