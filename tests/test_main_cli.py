# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

import sys
from unittest.mock import patch

from coreason_adlc_api.main import main, start


def test_start_command() -> None:
    """Verify that start() calls uvicorn.run with correct parameters."""
    with patch("coreason_adlc_api.main.uvicorn.run") as mock_run:
        start()
        mock_run.assert_called_once()
        args, kwargs = mock_run.call_args
        assert args[0] == "coreason_adlc_api.app:app"
        assert "host" in kwargs
        assert "port" in kwargs


def test_main_start_arg() -> None:
    """Verify that main() calls start() when 'start' arg is provided."""
    with patch("sys.argv", ["coreason-api", "start"]), patch("coreason_adlc_api.main.start") as mock_start:
        main()
        mock_start.assert_called_once()


def test_main_invalid_arg() -> None:
    """Verify that main() exits with 1 when invalid arg is provided."""
    with patch("sys.argv", ["coreason-api", "invalid"]), patch("sys.exit") as mock_exit:
        # Capture print output if needed, or just verify exit
        with patch("builtins.print") as mock_print:
            main()

        mock_exit.assert_called_once_with(1)
        mock_print.assert_called_with("Usage: coreason-api start")


def test_main_no_arg() -> None:
    """Verify that main() exits with 1 when no arg is provided."""
    with patch("sys.argv", ["coreason-api"]), patch("sys.exit") as mock_exit:
        with patch("builtins.print"):
            main()

        mock_exit.assert_called_once_with(1)
