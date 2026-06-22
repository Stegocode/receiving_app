"""
Owns: morning catalog-refresh entry point — compose source + repo from config,
      prompt for confirmation, call refresh_all.
Must not: contain business logic; must not read environment variables directly;
          must not import tkinter.
May import: config, core.logging_setup, adapters.db, adapters.source, services.refresh.
"""

from __future__ import annotations

import config
from adapters.db import SQLiteRepository
from adapters.source import make_source
from core.logging_setup import setup_logging
from services.refresh import refresh_all


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

    refresh_all(source, repo, confirmed=confirmed)

    if confirmed:
        print(f"Refresh complete — {repo.count_po_items()} items in catalog.")
    else:
        print("Refresh cancelled.")


if __name__ == "__main__":
    main()
