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
import urllib.parse
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
SINK_READY_GROUP_ID: str
SINK_INVENTORY_ID_COL: str
SINK_MODEL_COL: str
SINK_SERIAL_COL: str
SINK_STATUS_COL: str
SCANNER_TYPE: str
PRINTER_TYPE: str
SOURCE_TYPE: str  # "portal" | "fake"
SINK_TYPE: str  # "graphql" | "null"
FAKE_SOURCE_DATA: Path
RECEIVER_TYPE: str  # "portal" | "fake"
RECEIVE_LOCATION: str
RECEIVE_WHSE_LOCATION: str
RECEIVE_SCREENSHOT_DIR: Path


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


def _read_sink_group_ids(problems: list[str]) -> tuple[str, str, str, str]:
    """Read the four SINK group ID vars; all are required."""
    return (
        _require("SINK_RECEIVED_GROUP_ID", problems),
        _require("SINK_NO_MATCH_GROUP_ID", problems),
        _require("SINK_ATTENTION_GROUP_ID", problems),
        _require("SINK_READY_GROUP_ID", problems),
    )


def _read_board_columns(problems: list[str]) -> tuple[str, str, str, str]:
    """Read the four board column ID vars; all are required."""
    return (
        _require("SINK_INVENTORY_ID_COL", problems),
        _require("SINK_MODEL_COL", problems),
        _require("SINK_SERIAL_COL", problems),
        _require("SINK_STATUS_COL", problems),
    )


def _check_https_scheme(url: str, var_name: str, problems: list[str]) -> None:
    """Reject non-https schemes on credential-bearing URLs.

    http://localhost and http://127.0.0.1 are allowed for local dev/testing.
    """
    if not url:
        return
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme == "https":
        return
    if parsed.hostname in ("localhost", "127.0.0.1"):
        return
    problems.append(
        f"  {var_name} — HTTPS is required for credentialed endpoints;"
        f" got scheme '{parsed.scheme}'."
    )


def _check_credentialed_url_schemes(
    source_base_url: str,
    source_type: str,
    sink_base_url: str,
    sink_type: str,
    problems: list[str],
) -> None:
    """Enforce HTTPS on URLs that carry credentials; skip fake/null adapters."""
    if source_type != "fake":
        _check_https_scheme(source_base_url, "SOURCE_BASE_URL", problems)
    if sink_type != "null":
        _check_https_scheme(sink_base_url, "SINK_BASE_URL", problems)


def _read_receiver_config(problems: list[str]) -> tuple[str, str, str, str]:
    """Read RECEIVER_TYPE (choice) and the RECEIVE_* vars.

    RECEIVE_LOCATION and RECEIVE_WHSE_LOCATION are required when RECEIVER_TYPE=portal;
    optional when RECEIVER_TYPE=fake.
    """
    receiver_type = _validate_choice("RECEIVER_TYPE", "portal", {"portal", "fake"}, problems)
    if receiver_type == "portal":
        receive_location = _require("RECEIVE_LOCATION", problems)
        receive_whse_location = _require("RECEIVE_WHSE_LOCATION", problems)
    else:
        receive_location = _read_optional_str("RECEIVE_LOCATION", "")
        receive_whse_location = _read_optional_str("RECEIVE_WHSE_LOCATION", "")
    return (
        receiver_type,
        receive_location,
        receive_whse_location,
        _read_optional_str("RECEIVE_SCREENSHOT_DIR", ""),
    )


_DOTENV_SEARCH: object = object()  # sentinel: trigger priority-order search


def _find_dotenv() -> Path | None:
    """Return the first existing .env in the priority search order, or None."""
    xdg_raw = os.environ.get("XDG_CONFIG_HOME", "").strip()
    config_home = Path(xdg_raw) if xdg_raw else Path.home() / ".config"
    for candidate in (Path(".env"), config_home / "receiving_app" / ".env"):
        if candidate.exists():
            return candidate
    return None


def _load_dotenv(dotenv_path: object) -> None:
    """Resolve dotenv_path (sentinel, explicit, or None) and load the file."""
    if dotenv_path is _DOTENV_SEARCH:
        resolved: Path | None = _find_dotenv()
    elif dotenv_path is not None:
        resolved = Path(dotenv_path)  # type: ignore[arg-type]
    else:
        resolved = None
    if resolved is not None:
        load_dotenv(dotenv_path=resolved, override=False)


def validate(dotenv_path: Path | str | None = _DOTENV_SEARCH) -> None:  # type: ignore[assignment]
    """Check all required vars in one pass; raise ConfigError listing every problem.

    Call this as the first statement in every entry point. On success, all
    module-level accessors (DB_PATH, SOURCE_USERNAME, etc.) are populated.

    Args:
        dotenv_path: Path to a specific .env file to load; None to skip .env
                     loading entirely (useful in tests that set env vars directly).
                     When omitted, searches in order: ./.env, then
                     $XDG_CONFIG_HOME/receiving_app/.env (falling back to
                     ~/.config/receiving_app/.env). The first file found is loaded.
    """
    global DB_PATH, LOG_DIR, DOWNLOAD_DIR, POLL_INTERVAL_SECS
    global SOURCE_BASE_URL, SOURCE_USERNAME, SOURCE_PASSWORD
    global SINK_BASE_URL, SINK_API_TOKEN, SINK_BOARD_ID
    global SINK_RECEIVED_GROUP_ID, SINK_NO_MATCH_GROUP_ID
    global SINK_ATTENTION_GROUP_ID, SINK_READY_GROUP_ID
    global SINK_INVENTORY_ID_COL, SINK_MODEL_COL, SINK_SERIAL_COL, SINK_STATUS_COL
    global SCANNER_TYPE, PRINTER_TYPE
    global SOURCE_TYPE, SINK_TYPE, FAKE_SOURCE_DATA
    global RECEIVER_TYPE, RECEIVE_LOCATION, RECEIVE_WHSE_LOCATION, RECEIVE_SCREENSHOT_DIR

    _load_dotenv(dotenv_path)

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
    (
        sink_received_group_id,
        sink_no_match_group_id,
        sink_attention_group_id,
        sink_ready_group_id,
    ) = _read_sink_group_ids(problems)
    (
        sink_inventory_id_col,
        sink_model_col,
        sink_serial_col,
        sink_status_col,
    ) = _read_board_columns(problems)

    poll_interval = _read_poll_interval(problems)
    scanner_type = _validate_choice("SCANNER_TYPE", "wedge", {"wedge", "manual"}, problems)
    printer_type = _validate_choice("PRINTER_TYPE", "preview", {"preview", "zebra"}, problems)
    source_type = _validate_choice("SOURCE_TYPE", "portal", {"portal", "fake"}, problems)
    sink_type = _validate_choice("SINK_TYPE", "graphql", {"graphql", "null"}, problems)
    _check_credentialed_url_schemes(
        source_base_url, source_type, sink_base_url, sink_type, problems
    )
    fake_data_raw = _read_optional_str("FAKE_SOURCE_DATA", "test_data/pos.json")
    (
        receiver_type,
        receive_location,
        receive_whse_location,
        receive_screenshot_raw,
    ) = _read_receiver_config(problems)

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
    (
        SINK_RECEIVED_GROUP_ID,
        SINK_NO_MATCH_GROUP_ID,
        SINK_ATTENTION_GROUP_ID,
        SINK_READY_GROUP_ID,
    ) = sink_received_group_id, sink_no_match_group_id, sink_attention_group_id, sink_ready_group_id
    SINK_INVENTORY_ID_COL, SINK_MODEL_COL, SINK_SERIAL_COL, SINK_STATUS_COL = (
        sink_inventory_id_col,
        sink_model_col,
        sink_serial_col,
        sink_status_col,
    )
    (SCANNER_TYPE, PRINTER_TYPE, SOURCE_TYPE, SINK_TYPE) = (
        scanner_type,
        printer_type,
        source_type,
        sink_type,
    )
    FAKE_SOURCE_DATA = Path(fake_data_raw)
    (RECEIVER_TYPE, RECEIVE_LOCATION, RECEIVE_WHSE_LOCATION) = (
        receiver_type,
        receive_location,
        receive_whse_location,
    )
    RECEIVE_SCREENSHOT_DIR = (
        Path(receive_screenshot_raw) if receive_screenshot_raw else LOG_DIR / "screenshots"
    )
