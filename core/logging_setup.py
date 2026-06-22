# Owns: process-wide logging configuration (file handler, format, rotation).
# Must not: read config or environment; contain domain logic; be imported by library modules.
# May import: logging, logging.handlers, pathlib.

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path


def setup_logging(log_dir: Path) -> None:
    """Wire a rotating file handler to the root logger. Call once at application startup."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[
            logging.handlers.TimedRotatingFileHandler(
                log_dir / "receiving_app.log",
                when="midnight",
                backupCount=30,
            )
        ],
    )
