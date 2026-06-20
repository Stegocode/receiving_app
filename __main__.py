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
from adapters.sink import ResultSinkAdapter
from adapters.source import PortalSource
from adapters.ui.scanner_ui import ReceivingUI
from services.populate import populate_po
from services.receive import process_scan


def build_app() -> ReceivingUI:
    """Wire all adapters and return a ready-to-run ReceivingUI.

    Tk-free: no widget or mainloop call here. Call .run() to start the UI.
    """
    config.validate()
    repo = SQLiteRepository()
    sink = ResultSinkAdapter(
        config.SINK_BASE_URL,
        config.SINK_API_TOKEN,
        config.SINK_BOARD_ID,
        config.SINK_RECEIVED_GROUP_ID,
        config.SINK_NO_MATCH_GROUP_ID,
        config.SINK_ATTENTION_GROUP_ID,
    )
    source = PortalSource(
        config.SOURCE_BASE_URL,
        config.SOURCE_USERNAME,
        config.SOURCE_PASSWORD,
        config.DOWNLOAD_DIR,
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
