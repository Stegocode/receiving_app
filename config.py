"""
Owns: all environment variable reads and validated config values.
Must not: contain business logic; must not be imported by core/.
May import: os, pathlib, python-dotenv, core.errors.
"""
# Owns: all environment variable reads and validated config values.
# Must not: contain business logic; must not be imported by core/.
# May import: os, pathlib, python-dotenv, core.errors.

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
SINK_API_TOKEN: str
SINK_BOARD_ID: str
SINK_ATTENTION_GROUP_ID: str


def _require(name: str, problems: list[str]) -> str:
    val = os.environ.get(name, "").strip()
    if not val:
        problems.append(f"  {name} — required but not set. See .env.example for description.")
    return val


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
    global SINK_API_TOKEN, SINK_BOARD_ID, SINK_ATTENTION_GROUP_ID

    if dotenv_path is not None:
        load_dotenv(dotenv_path=dotenv_path, override=False)

    problems: list[str] = []

    db_path_raw = _require("DB_PATH", problems)
    log_dir_raw = _require("LOG_DIR", problems)
    download_dir_raw = _require("DOWNLOAD_DIR", problems)
    source_base_url = _require("SOURCE_BASE_URL", problems)
    source_username = _require("SOURCE_USERNAME", problems)
    source_password = _require("SOURCE_PASSWORD", problems)  # noqa: S105
    sink_api_token = _require("SINK_API_TOKEN", problems)
    sink_board_id = _require("SINK_BOARD_ID", problems)
    sink_attention_group_id = _require("SINK_ATTENTION_GROUP_ID", problems)

    poll_raw = os.environ.get("POLL_INTERVAL_SECS", "10").strip()
    try:
        poll_interval = int(poll_raw)
    except ValueError:
        problems.append(f"  POLL_INTERVAL_SECS — must be an integer, got '{poll_raw}'.")
        poll_interval = 10  # placeholder; not assigned below if we raise

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
    SINK_API_TOKEN = sink_api_token
    SINK_BOARD_ID = sink_board_id
    SINK_ATTENTION_GROUP_ID = sink_attention_group_id
