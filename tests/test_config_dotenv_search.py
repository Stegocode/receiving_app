"""
Owns: T3-12 — .env search-order tests for config.validate().
Must not: import concrete adapters or read real credentials from disk.
May import: config (reloaded per test), stdlib.

not_measured: file-not-found behavior on explicit paths (delegated to python-dotenv),
              Path.home() fallback when XDG_CONFIG_HOME is absent (XDG is monkeypatched
              here), partial .env files (file present but incomplete).
"""
# Owns: T3-12 dotenv search-order tests.
# Must not: import concrete adapters or real credentials.
# May import: config (reloaded), stdlib.

from __future__ import annotations

import importlib

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
    "SINK_READY_GROUP_ID",
    "SINK_INVENTORY_ID_COL",
    "SINK_MODEL_COL",
    "SINK_SERIAL_COL",
    "SINK_STATUS_COL",
]

_OPTIONAL_VARS = [
    "POLL_INTERVAL_SECS",
    "SCANNER_TYPE",
    "PRINTER_TYPE",
    "SOURCE_TYPE",
    "SINK_TYPE",
    "FAKE_SOURCE_DATA",
    "RECEIVER_TYPE",
    "RECEIVE_LOCATION",
    "RECEIVE_WHSE_LOCATION",
    "RECEIVE_SCREENSHOT_DIR",
    "XDG_CONFIG_HOME",
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
    "SINK_BOARD_ID": "board-test",
    "SINK_RECEIVED_GROUP_ID": "grp_recv",
    "SINK_NO_MATCH_GROUP_ID": "grp_nm",
    "SINK_ATTENTION_GROUP_ID": "grp_att",
    "SINK_READY_GROUP_ID": "grp_ready",
    "SINK_INVENTORY_ID_COL": "col_inv",
    "SINK_MODEL_COL": "col_model",
    "SINK_SERIAL_COL": "col_serial",
    "SINK_STATUS_COL": "col_status",
    "POLL_INTERVAL_SECS": "10",
    "RECEIVER_TYPE": "fake",
}


def _reload(monkeypatch, env: dict):
    """Clear all known config vars, apply overrides, reload config module."""
    for var in _REQUIRED_VARS + _OPTIONAL_VARS:
        monkeypatch.delenv(var, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import config

    return importlib.reload(config)


def test_explicit_dotenv_path_loads_that_file(monkeypatch, tmp_path):
    """validate(dotenv_path=f) loads vars from that exact file."""
    env_file = tmp_path / "custom.env"
    env_file.write_text("POLL_INTERVAL_SECS=42\n")
    env = {k: v for k, v in _VALID_ENV.items() if k != "POLL_INTERVAL_SECS"}
    cfg = _reload(monkeypatch, env)
    cfg.validate(dotenv_path=env_file)
    assert cfg.POLL_INTERVAL_SECS == 42


def test_cwd_dotenv_loaded_when_present(monkeypatch, tmp_path):
    """./.env in cwd is loaded when no explicit dotenv_path is given."""
    (tmp_path / ".env").write_text("POLL_INTERVAL_SECS=43\n")
    env = {k: v for k, v in _VALID_ENV.items() if k != "POLL_INTERVAL_SECS"}
    cfg = _reload(monkeypatch, env)
    monkeypatch.chdir(tmp_path)
    cfg.validate()
    assert cfg.POLL_INTERVAL_SECS == 43


def test_xdg_config_dotenv_loaded_when_cwd_absent(monkeypatch, tmp_path):
    """XDG config .env loaded when no ./.env exists in cwd."""
    app_dir = tmp_path / "config" / "receiving_app"
    app_dir.mkdir(parents=True)
    (app_dir / ".env").write_text("POLL_INTERVAL_SECS=44\n")
    env = {k: v for k, v in _VALID_ENV.items() if k != "POLL_INTERVAL_SECS"}
    cfg = _reload(monkeypatch, env)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    cwd = tmp_path / "work"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    cfg.validate()
    assert cfg.POLL_INTERVAL_SECS == 44


def test_cwd_dotenv_takes_priority_over_xdg(monkeypatch, tmp_path):
    """cwd ./.env takes priority over XDG config .env when both exist."""
    xdg_app = tmp_path / "config" / "receiving_app"
    xdg_app.mkdir(parents=True)
    (xdg_app / ".env").write_text("POLL_INTERVAL_SECS=99\n")
    cwd = tmp_path / "work"
    cwd.mkdir()
    (cwd / ".env").write_text("POLL_INTERVAL_SECS=55\n")
    env = {k: v for k, v in _VALID_ENV.items() if k != "POLL_INTERVAL_SECS"}
    cfg = _reload(monkeypatch, env)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.chdir(cwd)
    cfg.validate()
    assert cfg.POLL_INTERVAL_SECS == 55


def test_no_dotenv_anywhere_does_not_crash(monkeypatch, tmp_path):
    """No .env file anywhere — validate() succeeds when env vars are set directly."""
    cwd = tmp_path / "work"
    cwd.mkdir()
    cfg = _reload(monkeypatch, {**_VALID_ENV})
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "nonexistent"))
    monkeypatch.chdir(cwd)
    cfg.validate()
    assert cfg.POLL_INTERVAL_SECS == 10
