# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

import hashlib
import os
from unittest.mock import patch

import pytest
from coreason_adlc_api.app import app
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_get_compliance_success() -> None:
    """Verify that the compliance endpoint returns the correct hash and allowlists."""

    # Calculate expected hash
    # __file__ is /app/tests/test_router_system.py
    # Root is /app
    # Compliance is /app/src/coreason_adlc_api/compliance.yaml
    base_path = os.path.dirname(os.path.dirname(__file__))  # /app
    compliance_path = os.path.join(base_path, "src", "coreason_adlc_api", "compliance.yaml")

    with open(compliance_path, "rb") as f:
        expected_hash = hashlib.sha256(f.read()).hexdigest()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/api/v1/system/compliance")

        assert response.status_code == 200
        data = response.json()
        assert data["checksum_sha256"] == expected_hash
        assert "libraries" in data["allowlists"]
        assert "pandas" in data["allowlists"]["libraries"]


@pytest.mark.asyncio
async def test_compliance_missing_file() -> None:
    """Verify 500 error if compliance file is missing."""
    with patch("coreason_adlc_api.routers.system.os.path.exists", return_value=False):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get("/api/v1/system/compliance")
            assert response.status_code == 500
            assert "Compliance definition file missing" in response.json()["detail"]


@pytest.mark.asyncio
async def test_compliance_read_error() -> None:
    """Verify 500 error if reading/parsing fails."""
    # Mock open to raise exception
    with patch("builtins.open", side_effect=IOError("Disk read failed")):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get("/api/v1/system/compliance")
            assert response.status_code == 500
            assert "Failed to process compliance file" in response.json()["detail"]
