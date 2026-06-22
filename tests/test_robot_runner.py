"""
Owns: entry-layer tests for robot_runner — kill-path and shutdown break the loop.
Must not: import concrete portal or board adapters; perform real network I/O; sleep.
May import: pytest, unittest.mock, robot_runner, core.errors.

not_measured: the infinite poll loop itself (untestable without injection); real
              board/executor construction; executor per-pass lifecycle against a
              live portal. See DEBT.md [DEBT-T14-001].

PASS criteria:  SyncKillError → loop exits, executor.close() called.
PASS criteria:  KeyboardInterrupt → loop exits, executor.close() called.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import robot_runner
from core.errors import SyncKillError


def _env(tmp_path: object) -> dict[str, str]:
    """Minimal env that passes config.validate() with SINK_TYPE=graphql and RECEIVER_TYPE=fake."""
    return {
        "DB_PATH": str(tmp_path / "db.sqlite"),  # type: ignore[operator]
        "LOG_DIR": str(tmp_path / "logs"),  # type: ignore[operator]
        "DOWNLOAD_DIR": str(tmp_path / "dl"),  # type: ignore[operator]
        "SOURCE_BASE_URL": "http://source.example",
        "SOURCE_USERNAME": "user",
        "SOURCE_PASSWORD": "pass",
        "SINK_BASE_URL": "http://sink.example",
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
    """SyncKillError raised by receive_pending → loop exits; executor.close() is called."""
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

    fake_executor.close.assert_called()


def test_keyboard_interrupt_breaks_loop(tmp_path, monkeypatch):
    """KeyboardInterrupt from receive_pending → loop exits cleanly; executor.close() is called."""
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

    fake_executor.close.assert_called()
