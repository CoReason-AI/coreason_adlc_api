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
from coreason_adlc_api.app import create_app, lifespan


@pytest.mark.asyncio
async def test_lifespan_community_mode() -> None:
    """Verify Community Mode logging when license key is missing."""
    app = create_app()

    with (
        patch("coreason_adlc_api.app.init_db", new=AsyncMock()),
        patch("coreason_adlc_api.app.close_db", new=AsyncMock()),
        patch("coreason_adlc_api.app.telemetry_worker", new=AsyncMock()),
        patch("coreason_adlc_api.app.logger") as mock_logger,
        patch("coreason_adlc_api.app.settings.ENTERPRISE_LICENSE_KEY", None),
    ):
        async with lifespan(app):
            # Check for Community Mode log
            mock_logger.info.assert_any_call("Community Mode Enabled. Features restricted to local storage.")


@pytest.mark.asyncio
async def test_lifespan_enterprise_mode() -> None:
    """Verify Enterprise Mode logging when license key is present."""
    app = create_app()

    with (
        patch("coreason_adlc_api.app.init_db", new=AsyncMock()),
        patch("coreason_adlc_api.app.close_db", new=AsyncMock()),
        patch("coreason_adlc_api.app.telemetry_worker", new=AsyncMock()),
        patch("coreason_adlc_api.app.logger") as mock_logger,
        patch("coreason_adlc_api.app.settings.ENTERPRISE_LICENSE_KEY", "valid-key"),
    ):
        async with lifespan(app):
            # Check for Enterprise Mode log
            mock_logger.info.assert_any_call("Enterprise Mode Enabled. SSO and Remote Features Active.")
