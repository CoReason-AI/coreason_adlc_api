# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

import datetime
import uuid
from unittest.mock import AsyncMock, patch

import jwt
import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from coreason_adlc_api.app import app
from coreason_adlc_api.config import settings


@pytest.fixture
def mock_auth_header() -> str:
    user_uuid = str(uuid.uuid4())
    payload = {
        "sub": user_uuid,
        "oid": user_uuid,
        "name": "Interceptor Edge Tester",
        "email": "interceptor@coreason.ai",
        "groups": [],
        "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1),
    }
    token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return f"Bearer {token}"


@pytest.mark.asyncio
async def test_chat_budget_exceeded(mock_auth_header: str) -> None:
    """
    Test that the API returns 402 when the budget is exceeded.
    We mock check_budget_guardrail to raise HTTPException(402).
    """
    with patch(
        "coreason_adlc_api.routers.interceptor.check_budget_guardrail",
        side_effect=HTTPException(status_code=402, detail="Budget exceeded"),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            payload = {
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "Hello"}],
                "auc_id": "project-alpha",
                "estimated_cost": 0.05,
            }
            resp = await ac.post("/api/v1/chat/completions", json=payload, headers={"Authorization": mock_auth_header})

            assert resp.status_code == 402
            assert "Budget exceeded" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_chat_upstream_failure(mock_auth_header: str) -> None:
    """
    Test that the API returns 500 (or propagates exception) when the proxy fails.
    """
    with (
        patch("coreason_adlc_api.routers.interceptor.check_budget_guardrail", return_value=True),
        patch(
            "coreason_adlc_api.routers.interceptor.execute_inference_proxy",
            side_effect=Exception("Upstream Service Down"),
        ),
    ):
        # raise_app_exceptions=False allows us to capture the 500 response instead of raising the error
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
        ) as ac:
            payload = {"model": "gpt-4", "messages": [{"role": "user", "content": "Hello"}], "auc_id": "project-alpha"}
            resp = await ac.post("/api/v1/chat/completions", json=payload, headers={"Authorization": mock_auth_header})

            assert resp.status_code == 500


@pytest.mark.asyncio
async def test_chat_pii_edge_cases(mock_auth_header: str) -> None:
    """
    Test input with weird PII strings.
    Mock proxy and telemetry to verify everything runs without crashing.
    """
    mock_proxy_resp = {"choices": [{"message": {"content": "Hello there"}}]}

    with (
        patch("coreason_adlc_api.routers.interceptor.check_budget_guardrail", return_value=True),
        patch("coreason_adlc_api.routers.interceptor.execute_inference_proxy", return_value=mock_proxy_resp),
        patch("coreason_adlc_api.routers.interceptor.async_log_telemetry", new=AsyncMock()) as mock_log,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            # 1. PII Only input
            payload = {
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "Call me at 555-555-5555"}],
                "auc_id": "project-alpha",
            }
            resp = await ac.post("/api/v1/chat/completions", json=payload, headers={"Authorization": mock_auth_header})
            assert resp.status_code == 200

            # Verify telemetry was called (we don't check scrubbing logic here, just that it didn't crash)
            mock_log.assert_called()

            # 2. Empty input
            payload["messages"] = [{"role": "user", "content": ""}]
            resp = await ac.post("/api/v1/chat/completions", json=payload, headers={"Authorization": mock_auth_header})
            assert resp.status_code == 200


@pytest.mark.asyncio
async def test_chat_invalid_input(mock_auth_header: str) -> None:
    """
    Test malformed inputs.
    """
    # raise_app_exceptions=False allows us to capture the 500 response instead of raising the error
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test") as ac:
        # Negative cost
        payload = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Hello"}],
            "auc_id": "project-alpha",
            "estimated_cost": -10.0,
        }

        with patch(
            "coreason_adlc_api.routers.interceptor.check_budget_guardrail", side_effect=ValueError("Negative cost")
        ):
            resp = await ac.post("/api/v1/chat/completions", json=payload, headers={"Authorization": mock_auth_header})
            assert resp.status_code == 500
