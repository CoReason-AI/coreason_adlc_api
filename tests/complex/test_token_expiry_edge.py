# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

import asyncio
import datetime
from typing import Any, Dict
from unittest.mock import AsyncMock, patch

import pytest
from coreason_adlc_api.app import app
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_long_running_request_completes_after_expiry(mock_oidc_factory: Any) -> None:
    """
    Test that a request initiated with a valid token completes successfully
    even if the token expires while the request is being processed (mid-flight).
    """

    # Mock the proxy to simulate a long-running operation (2.5 seconds)
    # The token expires in 2.0 seconds.
    async def slow_proxy_response(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        await asyncio.sleep(2.5)
        return {
            "choices": [{"message": {"content": "I survived time travel!"}}],
            "usage": {"total_tokens": 10},
        }

    # We need to mock the budget check to pass, and the proxy to be slow
    with (
        patch("coreason_adlc_api.routers.interceptor.check_budget_guardrail", return_value=True),
        patch("coreason_adlc_api.routers.interceptor.execute_inference_proxy", side_effect=slow_proxy_response),
        # Mock telemetry to avoid DB calls
        patch("coreason_adlc_api.routers.interceptor.async_log_telemetry", new=AsyncMock()),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            # Generate token with short expiry
            exp_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=2.0)
            token = mock_oidc_factory({"exp": exp_time})

            payload = {
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "Hello"}],
                "auc_id": "project-alpha",
            }

            # Start request immediately (token is valid)
            resp = await ac.post(
                "/api/v1/chat/completions", json=payload, headers={"Authorization": f"Bearer {token}"}
            )

            assert resp.status_code == 200
            data = resp.json()
            assert data["choices"][0]["message"]["content"] == "I survived time travel!"


@pytest.mark.asyncio
async def test_request_fails_after_expiry(mock_oidc_factory: Any) -> None:
    """
    Control test: Verify that the same token is rejected if the request
    starts AFTER the token has expired.
    """
    # Expiry 1.0s
    exp_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=1.0)
    token = mock_oidc_factory({"exp": exp_time})

    # Wait for 1.2 seconds (token expires in 1.0s)
    await asyncio.sleep(1.2)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        payload = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Am I late?"}],
            "auc_id": "project-alpha",
        }

        resp = await ac.post(
            "/api/v1/chat/completions", json=payload, headers={"Authorization": f"Bearer {token}"}
        )

        # Should be 401 (or 403 depending on implementation, usually 401 for expiry)
        assert resp.status_code in [401, 403]
