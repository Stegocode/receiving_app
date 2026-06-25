"""
Owns: entry-layer tests for robot_runner — kill-path and shutdown break the loop.
Must not: import concrete portal or board adapters; perform real network I/O; sleep.
May import: pytest, unittest.mock, robot_runner, core.errors, services.receive_sync.

not_measured: the infinite poll loop itself (untestable without injection); real
              board/executor construction; executor per-pass lifecycle against a
              live portal. See DEBT.md [DEBT-T14-001].

PASS criteria:  SyncKillError → loop exits, executor.close() called exactly once (by runner).
PASS criteria:  KeyboardInterrupt during receive_pending → loop exits, executor.close() called once.
PASS criteria:  KeyboardInterrupt during sleep → loop exits cleanly, executor.close() called once.
PASS criteria:  receive_sync never closes the executor; runner is the single owner.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import robot_runner
from core.errors import SyncKillError
from services.receive_sync import ReceiveResult


def _env(tmp_path: object) -> dict[str, str]:
    """Minimal env that passes config.validate() with SINK_TYPE=graphql and RECEIVER_TYPE=fake."""
    return {
        "DB_PATH": str(tmp_path / "db.sqlite"),  # type: ignore[operator]
        "LOG_DIR": str(tmp_path / "logs"),  # type: ignore[operator]
        "DOWNLOAD_DIR": str(tmp_path / "dl"),  # type: ignore[operator]
        "SOURCE_BASE_URL": "https://source.example",
        "SOURCE_USERNAME": "user",
        "SOURCE_PASSWORD": "pass",
        "SINK_BASE_URL": "https://sink.example",
        "SINK_API_TOKEN": "tok",
        "SINK_BOARD_ID": "b1",
        "SINK_RECEIVED_GROUP_ID": "g1",
        "SINK_NO_MATCH_GROUP_ID": "g2",
        "SINK_ATTENTION_GROUP_ID": "g3",
        "SINK_READY_GROUP_ID": "g4",
        "SINK_INVENTORY_ID_COL": "c1",
        "SINK_MODEL_COL": "c2",
        "SINK_SERIAL_COL": "c3",
        "SINK_STATUS_COL": "c4",
        "SINK_TYPE": "graphql",
        "RECEIVER_TYPE": "fake",
        "RECEIVE_LOCATION": "LOC-01",
        "RECEIVE_WHSE_LOCATION": "WHSE-01",
    }


def test_sync_kill_error_breaks_loop(tmp_path, monkeypatch):
    """SyncKillError raised by receive_pending → loop exits; runner closes executor exactly once."""
    for k, v in _env(tmp_path).items():
        monkeypatch.setenv(k, v)

    fake_board = MagicMock()
    fake_executor = MagicMock()

    with (
        patch("robot_runner.make_board", return_value=fake_board),
        patch("robot_runner.make_receiver", return_value=fake_executor),
        patch(
            "robot_runner.receive_sync.receive_pending",
            side_effect=SyncKillError("test kill"),
        ),
        patch("robot_runner.setup_logging"),
        patch("time.sleep"),
    ):
        robot_runner.main()

    fake_executor.close.assert_called_once()


def test_keyboard_interrupt_breaks_loop(tmp_path, monkeypatch):
    """KeyboardInterrupt from receive_pending → loop exits cleanly; runner closes executor once."""
    for k, v in _env(tmp_path).items():
        monkeypatch.setenv(k, v)

    fake_board = MagicMock()
    fake_executor = MagicMock()

    with (
        patch("robot_runner.make_board", return_value=fake_board),
        patch("robot_runner.make_receiver", return_value=fake_executor),
        patch(
            "robot_runner.receive_sync.receive_pending",
            side_effect=KeyboardInterrupt,
        ),
        patch("robot_runner.setup_logging"),
        patch("time.sleep"),
    ):
        robot_runner.main()

    fake_executor.close.assert_called_once()


def test_keyboard_interrupt_during_sleep_shuts_down_cleanly(tmp_path, monkeypatch):
    """KeyboardInterrupt during time.sleep → runner exits cleanly; executor closed once.

    Covers the idle-sleep path: receive_pending completes, the runner's finally already closed
    the executor, then sleep fires KeyboardInterrupt. The runner must catch it and exit cleanly
    (no propagation, no double-close).
    """
    for k, v in _env(tmp_path).items():
        monkeypatch.setenv(k, v)

    fake_board = MagicMock()
    fake_executor = MagicMock()

    with (
        patch("robot_runner.make_board", return_value=fake_board),
        patch("robot_runner.make_receiver", return_value=fake_executor),
        patch(
            "robot_runner.receive_sync.receive_pending",
            return_value=ReceiveResult(received=1, no_match=0, failed=0, skipped=0),
        ),
        patch("robot_runner.setup_logging"),
        patch("time.sleep", side_effect=KeyboardInterrupt),
    ):
        robot_runner.main()  # must not raise

    fake_executor.close.assert_called_once()
