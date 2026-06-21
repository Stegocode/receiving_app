"""
Owns: all environment variable reads and validated config values.
Must not: contain business logic; must not be imported by core/.
May import: os, pathlib, python-dotenv, core.errors.
"""
# Owns: all environment variable reads and validated config values.
# Must not: contain business logic; must not be imported by core/.
# May import: os, pathlib, python-dotenv, core.errors.
# Blank optional vars (value.strip() == "") are treated as absent and fall back to defaults.

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from core.errors import ConfigError

# Set by validate() — accessing any of these before validate() raises NameError.
DB_PATH: Path
LOG_DIR: Path
DOWNLOAD_DIR: Path
POLL_INTERVAL_SECS: int
SOURCE_BASE_URL: str
SOURCE_USERNAME: str
SOURCE_PASSWORD: str
SINK_BASE_URL: str
SINK_API_TOKEN: str
SINK_BOARD_ID: str
SINK_RECEIVED_GROUP_ID: str
SINK_NO_MATCH_GROUP_ID: str
SINK_ATTENTION_GROUP_ID: str
SCANNER_TYPE: str
PRINTER_TYPE: str
SOURCE_TYPE: str  # "portal" | "fake"
SINK_TYPE: str  # "graphql" | "null"
FAKE_SOURCE_DATA: Path


def _require(name: str, problems: list[str]) -> str:
    val = os.environ.get(name, "").strip()
    if not val:
        problems.append(f"  {name} — required but not set. See .env.example for description.")
    return val


def _read_poll_interval(problems: list[str]) -> int:
    raw = os.environ.get("POLL_INTERVAL_SECS", "").strip()
    if not raw:
        return 10
    try:
        return int(raw)
    except ValueError:
        problems.append(f"  POLL_INTERVAL_SECS — must be an integer, got '{raw}'.")
        return 10  # placeholder; not used if we raise


def _validate_choice(name: str, default: str, allowed: set[str], problems: list[str]) -> str:
    raw = os.environ.get(name, "").strip()
    val = raw if raw else default
    if val not in allowed:
        problems.append(f"  {name} — got '{val}', must be one of {sorted(allowed)}.")
    return val


def _read_optional_str(name: str, default: str) -> str:
    """Return the env var value, or default when absent or blank."""
    raw = os.environ.get(name, "").strip()
    return raw if raw else default


def validate(dotenv_path: Path | str | None = Path(".env")) -> None:
    """Check all required vars in one pass; raise ConfigError listing every problem.

    Call this as the first statement in every entry point. On success, all
    module-level accessors (DB_PATH, SOURCE_USERNAME, etc.) are populated.

    Args:
        dotenv_path: Path to .env file to load. Pass None to skip .env loading
                     (useful in tests that set env vars directly).
    """
    global DB_PATH, LOG_DIR, DOWNLOAD_DIR, POLL_INTERVAL_SECS
    global SOURCE_BASE_URL, SOURCE_USERNAME, SOURCE_PASSWORD
    global SINK_BASE_URL, SINK_API_TOKEN, SINK_BOARD_ID
    global SINK_RECEIVED_GROUP_ID, SINK_NO_MATCH_GROUP_ID, SINK_ATTENTION_GROUP_ID
    global SCANNER_TYPE, PRINTER_TYPE
    global SOURCE_TYPE, SINK_TYPE, FAKE_SOURCE_DATA

    if dotenv_path is not None:
        load_dotenv(dotenv_path=dotenv_path, override=False)

    problems: list[str] = []

    db_path_raw = _require("DB_PATH", problems)
    log_dir_raw = _require("LOG_DIR", problems)
    download_dir_raw = _require("DOWNLOAD_DIR", problems)
    source_base_url = _require("SOURCE_BASE_URL", problems)
    source_username = _require("SOURCE_USERNAME", problems)
    source_password = _require("SOURCE_PASSWORD", problems)  # noqa: S105
    sink_base_url = _require("SINK_BASE_URL", problems)
    sink_api_token = _require("SINK_API_TOKEN", problems)
    sink_board_id = _require("SINK_BOARD_ID", problems)
    sink_received_group_id = _require("SINK_RECEIVED_GROUP_ID", problems)
    sink_no_match_group_id = _require("SINK_NO_MATCH_GROUP_ID", problems)
    sink_attention_group_id = _require("SINK_ATTENTION_GROUP_ID", problems)

    poll_interval = _read_poll_interval(problems)
    scanner_type = _validate_choice("SCANNER_TYPE", "wedge", {"wedge", "manual"}, problems)
    printer_type = _validate_choice("PRINTER_TYPE", "preview", {"preview"}, problems)
    source_type = _validate_choice("SOURCE_TYPE", "portal", {"portal", "fake"}, problems)
    sink_type = _validate_choice("SINK_TYPE", "graphql", {"graphql", "null"}, problems)
    fake_data_raw = _read_optional_str("FAKE_SOURCE_DATA", "test_data/pos.json")

    if problems:
        raise ConfigError(
            "Configuration invalid — fix these in .env before starting:\n" + "\n".join(problems)
        )

    DB_PATH = Path(db_path_raw)
    LOG_DIR = Path(log_dir_raw)
    DOWNLOAD_DIR = Path(download_dir_raw)
    POLL_INTERVAL_SECS = poll_interval
    SOURCE_BASE_URL = source_base_url
    SOURCE_USERNAME = source_username
    SOURCE_PASSWORD = source_password
    SINK_BASE_URL = sink_base_url
    SINK_API_TOKEN = sink_api_token
    SINK_BOARD_ID = sink_board_id
    SINK_RECEIVED_GROUP_ID = sink_received_group_id
    SINK_NO_MATCH_GROUP_ID = sink_no_match_group_id
    SINK_ATTENTION_GROUP_ID = sink_attention_group_id
    SCANNER_TYPE = scanner_type
    PRINTER_TYPE = printer_type
    SOURCE_TYPE = source_type
    SINK_TYPE = sink_type
    FAKE_SOURCE_DATA = Path(fake_data_raw)
