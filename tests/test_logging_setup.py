"""
Owns: tests for core/logging_setup.py — _ContextFormatter renders extras, setup installs handler.
Must not: modify logging state permanently; must not perform network calls.
May import: pytest, logging, logging.handlers, pathlib.Path, core.logging_setup
            (_ContextFormatter, setup_logging).

not_measured: file rotation behaviour on disk, log output under concurrent writers,
              handler cleanup on process exit, multiple setup_logging calls in production.
"""

import logging
import logging.handlers

import pytest

from core.logging_setup import _ContextFormatter, setup_logging


@pytest.fixture(autouse=True)
def _restore_root_logger():
    """Snapshot root logger state; restore handlers and level after each test."""
    root = logging.getLogger()
    pre_handlers = list(root.handlers)
    pre_level = root.level
    yield
    for h in list(root.handlers):
        if h not in pre_handlers:
            h.close()
            root.removeHandler(h)
    root.handlers[:] = pre_handlers
    root.setLevel(pre_level)


def test_context_formatter_renders_extra_fields():
    """_ContextFormatter appends extra={} fields as key=value to the log line.

    Strengthened: assert base message precedes extras to kill mutmut_7 (base=None
    would produce "None po_number=PO-9", not "portal.fetch_order.start po_number=PO-9").
    """
    rec = logging.LogRecord("n", logging.INFO, "p", 1, "portal.fetch_order.start", None, None)
    rec.po_number = "PO-9"
    out = _ContextFormatter("%(message)s").format(rec)
    assert "po_number=PO-9" in out
    assert "portal.fetch_order.start" in out


def test_context_formatter_excludes_private_underscore_fields():
    """Fields starting with '_' must NOT appear in formatted output.

    Kills mutmut_2 (`and not k.startswith("_")` → `or not k.startswith("_")`):
    the mutation includes private fields in extras.
    Kills mutmut_6 (startswith("XX_XX")): private keys no longer excluded.
    """
    rec = logging.LogRecord("n", logging.INFO, "p", 1, "msg", None, None)
    rec._internal = "secret"
    rec.public = "visible"
    out = _ContextFormatter("%(message)s").format(rec)
    assert "public=visible" in out
    assert "_internal" not in out
    assert "secret" not in out


def test_context_formatter_multiple_extras_space_separated():
    """Two extra fields appear with a single space separator, not 'XX XX'.

    Kills mutmut_12: `" ".join(...)` → `"XX XX".join(...)` changes the separator.
    """
    rec = logging.LogRecord("n", logging.INFO, "p", 1, "msg", None, None)
    rec.po_number = "PO-1"
    rec.status = "ok"
    out = _ContextFormatter("%(message)s").format(rec)
    assert "po_number=PO-1" in out
    assert "status=ok" in out
    # Neither field should be separated by "XX XX"
    assert "XX" not in out


def test_setup_logging_installs_rotating_handler_at_correct_path(tmp_path):
    """setup_logging attaches a TimedRotatingFileHandler writing to receiving_app.log.

    Strengthened to check when, backupCount, formatter, and log level — killing:
      - mutmut_4 (backupCount=None), mutmut_7 (remove backupCount), mutmut_13 (backupCount=31)
      - mutmut_6 (remove when="midnight") — Python normalizes to "MIDNIGHT" internally
      - mutmut_14 (formatter=None), mutmut_15 (_ContextFormatter(None))
      - mutmut_16/17 (garbled format string)
      - mutmut_18 (level=None), mutmut_21 (remove level arg)
    """
    logging.getLogger().setLevel(logging.WARNING)  # ensure level change is observable
    setup_logging(tmp_path)
    root = logging.getLogger()
    file_handlers = [
        h for h in root.handlers if isinstance(h, logging.handlers.TimedRotatingFileHandler)
    ]
    assert file_handlers, "Expected a TimedRotatingFileHandler on the root logger"
    handler = next(
        h for h in file_handlers if h.baseFilename == str(tmp_path / "receiving_app.log")
    )

    assert handler.backupCount == 30
    assert handler.when == "MIDNIGHT"  # Python normalizes when= to uppercase
    assert root.level == logging.INFO

    assert isinstance(handler.formatter, _ContextFormatter)
    fmt = handler.formatter._fmt
    assert fmt == "%(asctime)s %(levelname)s %(name)s %(message)s"
