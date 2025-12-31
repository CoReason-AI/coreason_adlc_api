# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from coreason_adlc_api.app import app
from coreason_adlc_api.config import settings
from coreason_adlc_api.main import main, start

client = TestClient(app)


def test_health_check() -> None:
    """Verify the health check endpoint returns 200 OK."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "env": settings.APP_ENV}


def test_settings_load() -> None:
    """Verify settings are loaded from env vars (or defaults)."""
    assert settings.APP_ENV == "development"
    assert settings.PORT == 8000


@patch("uvicorn.run")
def test_cli_start_command(mock_run: MagicMock) -> None:
    """Verify the start command calls uvicorn.run with correct params."""
    start()
    mock_run.assert_called_once_with(
        "coreason_adlc_api.app:app",
        host=settings.HOST,
        port=settings.PORT,
        log_level=settings.LOG_LEVEL.lower(),
        reload=settings.DEBUG,
    )


@patch("coreason_adlc_api.main.start")
def test_main_start_arg(mock_start: MagicMock) -> None:
    """Verify main calls start() when argument is 'start'."""
    with patch("sys.argv", ["coreason-api", "start"]):
        main()
        mock_start.assert_called_once()


def test_main_no_args(capsys: pytest.CaptureFixture[str]) -> None:
    """Verify main prints usage and exits when no args provided."""
    with patch("sys.argv", ["coreason-api"]):
        with pytest.raises(SystemExit) as excinfo:
            main()
        assert excinfo.value.code == 1
        captured = capsys.readouterr()
        assert "Usage: coreason-api start" in captured.out


def test_lifespan() -> None:
    """Verify lifespan logs startup and shutdown and handles DB init."""
    # DB init/close calls removed from app.py, so we just check worker
    with patch("coreason_adlc_api.app.telemetry_worker", new=AsyncMock()) as mock_worker:
        with TestClient(app) as _:
            # Trigger startup
            pass

        mock_worker.assert_called_once()
