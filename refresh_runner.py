"""
Owns: morning catalog-refresh entry point — compose source + repo from config,
      prompt for confirmation, call refresh_all.
Must not: contain business logic; must not read environment variables directly;
          must not import tkinter.
May import: config, core.logging_setup, adapters.db, adapters.source, services.refresh.
"""

from __future__ import annotations

import sys

import config
from adapters.db import SQLiteRepository
from adapters.source import make_source
from core.logging_setup import setup_logging
from services.refresh import RefreshResult, refresh_all

_EXIT_CODES: dict[RefreshResult, int] = {
    RefreshResult.SUCCESS: 0,
    RefreshResult.CANCELLED: 1,
    RefreshResult.EMPTY_ABORT: 2,
}


def _execute(source: object, repo: object, confirmed: bool) -> int:
    """Run the refresh and print a status message; return the exit code."""
    result = refresh_all(source, repo, confirmed=confirmed)  # type: ignore[arg-type]
    if result is RefreshResult.SUCCESS:
        print(f"Refresh complete — {repo.count_po_items()} items in catalog.")  # type: ignore[attr-defined]
    elif result is RefreshResult.CANCELLED:
        print("Refresh cancelled.")
    else:
        print("Refresh aborted — source returned no rows; catalog was not modified.")
    return _EXIT_CODES[result]


def main() -> None:
    config.validate()
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    setup_logging(config.LOG_DIR)

    print("=" * 60)
    print("  Catalog Refresh — wipe and rebuild from open orders")
    print("=" * 60)
    answer = input("Type YES to confirm wipe and rebuild: ").strip()
    confirmed = answer == "YES"

    repo = SQLiteRepository()
    source = make_source(
        config.SOURCE_TYPE,
        base_url=config.SOURCE_BASE_URL,
        username=config.SOURCE_USERNAME,
        password=config.SOURCE_PASSWORD,
        download_dir=config.DOWNLOAD_DIR,
        fake_data_path=config.FAKE_SOURCE_DATA,
    )

    sys.exit(_execute(source, repo, confirmed=confirmed))


if __name__ == "__main__":
    main()
