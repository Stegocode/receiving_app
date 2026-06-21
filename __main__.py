"""
Owns: application entry point and composition root — wires all adapters together.
Must not: contain business logic; must not read environment variables directly;
          must not import tkinter.
May import: config, adapters.db, adapters.printer, adapters.sink, adapters.source,
            adapters.ui.scanner_ui, services.receive, services.populate.
"""

from __future__ import annotations

import config
from adapters.db import SQLiteRepository
from adapters.printer import make_printer
from adapters.sink import make_sink
from adapters.source import make_source
from adapters.ui.scanner_ui import ReceivingUI
from services.populate import populate_po
from services.receive import process_scan


def build_app() -> ReceivingUI:
    """Wire all adapters and return a ready-to-run ReceivingUI.

    Tk-free: no widget or mainloop call here. Call .run() to start the UI.
    Creates DB_PATH.parent, LOG_DIR, and DOWNLOAD_DIR on first run.
    """
    config.validate()
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    config.DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    repo = SQLiteRepository()
    sink = make_sink(
        config.SINK_TYPE,
        base_url=config.SINK_BASE_URL,
        api_token=config.SINK_API_TOKEN,
        board_id=config.SINK_BOARD_ID,
        received_group_id=config.SINK_RECEIVED_GROUP_ID,
        no_match_group_id=config.SINK_NO_MATCH_GROUP_ID,
        attention_group_id=config.SINK_ATTENTION_GROUP_ID,
    )
    source = make_source(
        config.SOURCE_TYPE,
        base_url=config.SOURCE_BASE_URL,
        username=config.SOURCE_USERNAME,
        password=config.SOURCE_PASSWORD,
        download_dir=config.DOWNLOAD_DIR,
        fake_data_path=config.FAKE_SOURCE_DATA,
    )
    printer = make_printer(config.PRINTER_TYPE)
    return ReceivingUI(
        process=lambda barcode, po: process_scan(barcode, po, repo, sink),
        printer=printer,
        scanner_type=config.SCANNER_TYPE,
        populate=lambda po: populate_po(po, repo, source),
    )


def main() -> None:
    build_app().run()


if __name__ == "__main__":
    main()
