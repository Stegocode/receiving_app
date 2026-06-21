"""
Owns: tests for config.validate() behavior and entry-point startup gate.
Must not: import concrete adapters or read real credentials from disk.
May import: config (reloaded per test), core.errors, stdlib.

not_measured: real .env file on disk, actual filesystem paths, real adapter
              credentials, real database connections, real network services.
"""
# Owns: tests for config.validate() and startup gate.
# Must not: import concrete adapters or real credentials.
# May import: config (reloaded), core.errors, stdlib.

from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path

import pytest

from core.errors import ConfigError

PROJECT_ROOT = Path(__file__).parent.parent

_REQUIRED_VARS = [
    "DB_PATH",
    "LOG_DIR",
    "DOWNLOAD_DIR",
    "SOURCE_BASE_URL",
    "SOURCE_USERNAME",
    "SOURCE_PASSWORD",
    "SINK_BASE_URL",
    "SINK_API_TOKEN",
    "SINK_BOARD_ID",
    "SINK_RECEIVED_GROUP_ID",
    "SINK_NO_MATCH_GROUP_ID",
    "SINK_ATTENTION_GROUP_ID",
]

_VALID_ENV = {
    "DB_PATH": "/tmp/test.db",
    "LOG_DIR": "/tmp/logs",
    "DOWNLOAD_DIR": "/tmp/downloads",
    "SOURCE_BASE_URL": "https://portal.example",
    "SOURCE_USERNAME": "testuser",
    "SOURCE_PASSWORD": "testpass",
    "SINK_BASE_URL": "https://api.example.com/v2",
    "SINK_API_TOKEN": "testtoken",
    "SINK_BOARD_ID": "board123",
    "SINK_RECEIVED_GROUP_ID": "grp_recv",
    "SINK_NO_MATCH_GROUP_ID": "grp_nm",
    "SINK_ATTENTION_GROUP_ID": "group123",
    "POLL_INTERVAL_SECS": "10",
}


def _reload(monkeypatch, env: dict):
    """Clear all config vars from the environment, apply overrides, reload config."""
    _OPTIONAL_VARS = [
        "POLL_INTERVAL_SECS",
        "SCANNER_TYPE",
        "PRINTER_TYPE",
        "SOURCE_TYPE",
        "SINK_TYPE",
        "FAKE_SOURCE_DATA",
    ]
    for var in _REQUIRED_VARS + _OPTIONAL_VARS:
        monkeypatch.delenv(var, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import config

    return importlib.reload(config)


def test_missing_all_required_vars_reported_together(monkeypatch):
    """All required vars absent — ConfigError names every one in a single message."""
    cfg = _reload(monkeypatch, {})
    with pytest.raises(ConfigError) as exc:
        cfg.validate(dotenv_path=None)
    msg = str(exc.value)
    for var in _REQUIRED_VARS:
        assert var in msg, f"Expected '{var}' in error message, got:\n{msg}"


def test_missing_one_var_named(monkeypatch):
    """One var absent — ConfigError names it specifically."""
    env = {**_VALID_ENV}
    del env["SINK_API_TOKEN"]
    cfg = _reload(monkeypatch, env)
    with pytest.raises(ConfigError) as exc:
        cfg.validate(dotenv_path=None)
    assert "SINK_API_TOKEN" in str(exc.value)


def test_all_vars_present_no_exception(monkeypatch):
    """All vars set — validate() returns without raising; accessors are populated."""
    cfg = _reload(monkeypatch, _VALID_ENV)
    cfg.validate(dotenv_path=None)
    assert cfg.POLL_INTERVAL_SECS == 10
    assert isinstance(cfg.DB_PATH, Path)
    assert isinstance(cfg.LOG_DIR, Path)
    assert isinstance(cfg.DOWNLOAD_DIR, Path)


def test_poll_interval_defaults_to_10(monkeypatch):
    """POLL_INTERVAL_SECS absent — defaults to 10 without error."""
    env = {k: v for k, v in _VALID_ENV.items() if k != "POLL_INTERVAL_SECS"}
    cfg = _reload(monkeypatch, env)
    cfg.validate(dotenv_path=None)
    assert cfg.POLL_INTERVAL_SECS == 10


def test_poll_interval_invalid_raises(monkeypatch):
    """Non-integer POLL_INTERVAL_SECS — ConfigError names the var."""
    env = {**_VALID_ENV, "POLL_INTERVAL_SECS": "not_a_number"}
    cfg = _reload(monkeypatch, env)
    with pytest.raises(ConfigError) as exc:
        cfg.validate(dotenv_path=None)
    assert "POLL_INTERVAL_SECS" in str(exc.value)


def test_raises_config_error_not_bare_exception(monkeypatch):
    """validate() raises ConfigError specifically, not a bare Exception."""
    cfg = _reload(monkeypatch, {})
    with pytest.raises(ConfigError):
        cfg.validate(dotenv_path=None)


def test_scanner_type_defaults_to_wedge(monkeypatch):
    """SCANNER_TYPE absent — defaults to 'wedge' without error."""
    env = {k: v for k, v in _VALID_ENV.items() if k != "SCANNER_TYPE"}
    cfg = _reload(monkeypatch, env)
    cfg.validate(dotenv_path=None)
    assert cfg.SCANNER_TYPE == "wedge"


def test_scanner_type_manual_accepted(monkeypatch):
    """SCANNER_TYPE='manual' is a valid value."""
    cfg = _reload(monkeypatch, {**_VALID_ENV, "SCANNER_TYPE": "manual"})
    cfg.validate(dotenv_path=None)
    assert cfg.SCANNER_TYPE == "manual"


def test_scanner_type_invalid_raises(monkeypatch):
    """Invalid SCANNER_TYPE — ConfigError names the var."""
    cfg = _reload(monkeypatch, {**_VALID_ENV, "SCANNER_TYPE": "usb_hid"})
    with pytest.raises(ConfigError) as exc:
        cfg.validate(dotenv_path=None)
    assert "SCANNER_TYPE" in str(exc.value)


def test_printer_type_defaults_to_preview(monkeypatch):
    """PRINTER_TYPE absent — defaults to 'preview' without error."""
    env = {k: v for k, v in _VALID_ENV.items() if k != "PRINTER_TYPE"}
    cfg = _reload(monkeypatch, env)
    cfg.validate(dotenv_path=None)
    assert cfg.PRINTER_TYPE == "preview"


def test_printer_type_invalid_raises(monkeypatch):
    """Invalid PRINTER_TYPE — ConfigError names the var."""
    cfg = _reload(monkeypatch, {**_VALID_ENV, "PRINTER_TYPE": "zebra"})
    with pytest.raises(ConfigError) as exc:
        cfg.validate(dotenv_path=None)
    assert "PRINTER_TYPE" in str(exc.value)


def test_source_type_defaults_to_portal(monkeypatch):
    """SOURCE_TYPE absent — defaults to 'portal' without error."""
    cfg = _reload(monkeypatch, _VALID_ENV)
    cfg.validate(dotenv_path=None)
    assert cfg.SOURCE_TYPE == "portal"


def test_source_type_blank_falls_back_to_portal(monkeypatch):
    """SOURCE_TYPE='' (blank) — treated as absent, defaults to 'portal'."""
    cfg = _reload(monkeypatch, {**_VALID_ENV, "SOURCE_TYPE": ""})
    cfg.validate(dotenv_path=None)
    assert cfg.SOURCE_TYPE == "portal"


def test_source_type_invalid_raises(monkeypatch):
    """Invalid SOURCE_TYPE — ConfigError names the var."""
    cfg = _reload(monkeypatch, {**_VALID_ENV, "SOURCE_TYPE": "scraper"})
    with pytest.raises(ConfigError) as exc:
        cfg.validate(dotenv_path=None)
    assert "SOURCE_TYPE" in str(exc.value)


def test_sink_type_defaults_to_graphql(monkeypatch):
    """SINK_TYPE absent — defaults to 'graphql' without error."""
    cfg = _reload(monkeypatch, _VALID_ENV)
    cfg.validate(dotenv_path=None)
    assert cfg.SINK_TYPE == "graphql"


def test_sink_type_blank_falls_back_to_graphql(monkeypatch):
    """SINK_TYPE='' (blank) — treated as absent, defaults to 'graphql'."""
    cfg = _reload(monkeypatch, {**_VALID_ENV, "SINK_TYPE": ""})
    cfg.validate(dotenv_path=None)
    assert cfg.SINK_TYPE == "graphql"


def test_sink_type_invalid_raises(monkeypatch):
    """Invalid SINK_TYPE — ConfigError names the var."""
    cfg = _reload(monkeypatch, {**_VALID_ENV, "SINK_TYPE": "rest"})
    with pytest.raises(ConfigError) as exc:
        cfg.validate(dotenv_path=None)
    assert "SINK_TYPE" in str(exc.value)


def test_poll_interval_blank_falls_back_to_default(monkeypatch):
    """POLL_INTERVAL_SECS='' (blank) — treated as absent, defaults to 10."""
    cfg = _reload(monkeypatch, {**_VALID_ENV, "POLL_INTERVAL_SECS": ""})
    cfg.validate(dotenv_path=None)
    assert cfg.POLL_INTERVAL_SECS == 10


def test_scanner_type_blank_falls_back_to_default(monkeypatch):
    """SCANNER_TYPE='' (blank) — treated as absent, defaults to 'wedge'."""
    cfg = _reload(monkeypatch, {**_VALID_ENV, "SCANNER_TYPE": ""})
    cfg.validate(dotenv_path=None)
    assert cfg.SCANNER_TYPE == "wedge"


def test_build_app_creates_missing_dirs(monkeypatch, tmp_path):
    """build_app() creates DB_PATH.parent, LOG_DIR, and DOWNLOAD_DIR on first run.

    PASS: all three directories exist after build_app() completes.
    KILL: build_app() raises, or any directory is absent.
    SKIP: tkinter/_tkinter not installed (run `brew install python-tk@3.12` to enable).
    not_measured: Tk widget construction (run() is not called).
    """
    pytest.importorskip("tkinter", reason="tkinter not available — brew install python-tk@3.12")
    env = {
        **_VALID_ENV,
        "DB_PATH": str(tmp_path / "db" / "app.db"),
        "LOG_DIR": str(tmp_path / "logs"),
        "DOWNLOAD_DIR": str(tmp_path / "downloads"),
    }
    cfg = _reload(monkeypatch, env)
    real_validate = cfg.validate
    monkeypatch.setattr(cfg, "validate", lambda: real_validate(dotenv_path=None))
    spec = importlib.util.spec_from_file_location("app_main", PROJECT_ROOT / "__main__.py")
    app_main = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(app_main)
    app_main.build_app()
    assert (tmp_path / "db").exists()
    assert (tmp_path / "logs").exists()
    assert (tmp_path / "downloads").exists()


def test_startup_gate(monkeypatch, tmp_path):
    """Smoke gate: build_app() returns a ReceivingUI when all required vars are set.

    PASS: build_app() returns ReceivingUI without raising, no Tk window opened.
    KILL: build_app() raises any exception.
    SKIP: tkinter/_tkinter not installed (run `brew install python-tk@3.12` to enable).
    not_measured: real DB, real adapters, real network, actual .env file on disk,
                  Tk widget construction (run() is not called).
    """
    pytest.importorskip("tkinter", reason="tkinter not available — brew install python-tk@3.12")
    env = {
        **_VALID_ENV,
        "DB_PATH": str(tmp_path / "test.db"),
        "LOG_DIR": str(tmp_path / "logs"),
        "DOWNLOAD_DIR": str(tmp_path / "downloads"),
    }
    cfg = _reload(monkeypatch, env)
    real_validate = cfg.validate
    # Bypass .env file loading — env vars already set via monkeypatch.
    monkeypatch.setattr(cfg, "validate", lambda: real_validate(dotenv_path=None))
    # Load __main__.py by file path to avoid collision with pytest's own __main__.
    spec = importlib.util.spec_from_file_location("app_main", PROJECT_ROOT / "__main__.py")
    app_main = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(app_main)
    from adapters.ui.scanner_ui import ReceivingUI

    app = app_main.build_app()
    assert isinstance(app, ReceivingUI)
