"""
Owns: robot entry point — poll loop for the receiving robot.
Must not: contain domain logic; must not be imported by services or adapters.
May import: config, core.logging_setup, adapters.board, adapters.receiver,
            services.receive_sync, core.errors.
"""
# Owns: robot entry point — poll loop.
# Must not: contain domain logic; must not be imported by services or adapters.
# May import: config, core.logging_setup, adapters.board, adapters.receiver,
#             services.receive_sync, core.errors.

from __future__ import annotations

import logging
import time

import config
from adapters.board import make_board
from adapters.receiver import make_receiver
from core.errors import SyncKillError
from core.logging_setup import setup_logging
from services import receive_sync

_log = logging.getLogger(__name__)


def main() -> None:
    config.validate()
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    setup_logging(config.LOG_DIR)

    board = make_board(
        config.SINK_TYPE,
        api_url=config.SINK_BASE_URL,
        token=config.SINK_API_TOKEN,
        board_id=config.SINK_BOARD_ID,
        ready_group_id=config.SINK_READY_GROUP_ID,
        received_group_id=config.SINK_RECEIVED_GROUP_ID,
        no_match_group_id=config.SINK_NO_MATCH_GROUP_ID,
        inventory_id_col=config.SINK_INVENTORY_ID_COL,
        model_col=config.SINK_MODEL_COL,
        serial_col=config.SINK_SERIAL_COL,
        status_col=config.SINK_STATUS_COL,
    )

    _log.info("robot_start poll_interval_secs=%d", config.POLL_INTERVAL_SECS)

    while True:
        executor = make_receiver(
            config.RECEIVER_TYPE,
            base_url=config.SOURCE_BASE_URL,
            username=config.SOURCE_USERNAME,
            password=config.SOURCE_PASSWORD,
            location_label=config.RECEIVE_LOCATION,
            whse_label=config.RECEIVE_WHSE_LOCATION,
            screenshot_dir=config.RECEIVE_SCREENSHOT_DIR,
        )
        try:
            result = receive_sync.receive_pending(board, executor)
            _log.info(
                "pass_complete rcvd=%d no_match=%d failed=%d skipped=%d",
                result.received,
                result.no_match,
                result.failed,
                result.skipped,
            )
        except SyncKillError as exc:
            _log.error("robot_kill msg=%s", exc)
            break
        except KeyboardInterrupt:
            _log.info("robot_shutdown")
            break
        except Exception:
            _log.exception("robot_pass_error")
        finally:
            executor.close()
        try:
            time.sleep(config.POLL_INTERVAL_SECS)
        except KeyboardInterrupt:
            _log.info("robot_shutdown")
            break


if __name__ == "__main__":
    main()
