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
import uuid
from typing import Any, Dict
from unittest.mock import AsyncMock, patch

import jwt
import pytest
from httpx import ASGITransport, AsyncClient

from coreason_adlc_api.app import app
from coreason_adlc_api.config import settings


def generate_token(expiry_seconds: float) -> str:
    """
    Generates a token that expires in `expiry_seconds` from now.
    """
    user_uuid = str(uuid.uuid4())
    # Expiry relative to now
    exp_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=expiry_seconds)

    payload = {
        "sub": user_uuid,
        "oid": user_uuid,
        "name": "Time Traveler",
        "email": "future@coreason.ai",
        "groups": [],
        "exp": exp_time,
    }
    token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return f"Bearer {token}"


@pytest.mark.asyncio
async def test_long_running_request_completes_after_expiry() -> None:
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
            # Generate token INSIDE the context to minimize delay before request
            # Give a robust 2-second window for the request to reach the server handler
            token = generate_token(expiry_seconds=2.0)

            payload = {
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "Hello"}],
                "auc_id": "project-alpha",
            }

            # Start request immediately (token is valid)
            resp = await ac.post("/api/v1/chat/completions", json=payload, headers={"Authorization": token})

            assert resp.status_code == 200
            data = resp.json()
            assert data["choices"][0]["message"]["content"] == "I survived time travel!"


@pytest.mark.asyncio
async def test_request_fails_after_expiry() -> None:
    """
    Control test: Verify that the same token is rejected if the request
    starts AFTER the token has expired.
    """
    token = generate_token(expiry_seconds=1.0)

    # Wait for 1.2 seconds (token expires in 1.0s)
    await asyncio.sleep(1.2)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        payload = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Am I late?"}],
            "auc_id": "project-alpha",
        }

        resp = await ac.post("/api/v1/chat/completions", json=payload, headers={"Authorization": token})

        # Should be 401 (or 403 depending on implementation, usually 401 for expiry)
        assert resp.status_code in [401, 403]
