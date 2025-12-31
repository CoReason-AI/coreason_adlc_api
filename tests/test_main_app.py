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
from unittest.mock import AsyncMock, patch

import pytest

from coreason_adlc_api.app import create_app, lifespan
from coreason_adlc_api.main import main


def test_main() -> None:
    """Verify main entry point runs uvicorn."""
    with patch("uvicorn.run") as mock_run, patch.object(sys, "argv", ["coreason-api", "start"]):
        main()
        mock_run.assert_called_once()


@pytest.mark.asyncio
async def test_lifespan() -> None:
    """Verify lifespan startup and shutdown."""
    app = create_app()

    with patch("coreason_adlc_api.app.telemetry_worker", new=AsyncMock()) as mock_worker:
        async with lifespan(app):
            # Worker should be started
            mock_worker.assert_called_once()
