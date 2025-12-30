# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

import uuid
from typing import Any, Dict
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from coreason_adlc_api.app import app

try:
    from presidio_analyzer import AnalyzerEngine  # noqa: F401

    HAS_PRESIDIO = True
except ImportError:
    HAS_PRESIDIO = False


@pytest.fixture
def mock_auth_header(mock_oidc_factory: Any) -> str:
    user_uuid = str(uuid.uuid4())
    token = mock_oidc_factory(
        {
            "sub": user_uuid,
            "oid": user_uuid,
            "name": "Robustness Tester",
            "email": "robust@coreason.ai",
        }
    )
    return f"Bearer {token}"


@pytest.mark.asyncio
async def test_chat_huge_payload(mock_auth_header: str) -> None:
    """
    Test sending a very large payload (1MB+ text) to the chat endpoint.
    Goal: Verify PII scrubber and Middleware process it without crashing or timing out significantly.
    """
    # Create a 2MB string
    huge_text = "a" * (2 * 1024 * 1024)

    payload = {
        "model": "gpt-4",
        "messages": [{"role": "user", "content": huge_text}],
        "auc_id": "project-robustness",
        "estimated_cost": 0.1,
    }

    # Mock dependencies to isolate middleware processing
    mock_response = {
        "id": "chatcmpl-robust",
        "object": "chat.completion",
        "created": 1234567890,
        "model": "gpt-4",
        "choices": [{"message": {"content": "Processed"}}],
        "usage": {"total_tokens": 10},
    }

    # Removing the mock for scrub_pii_payload to test real behavior
    # Assuming Presidio can handle 2MB within the timeout, or we accept the slowness.
    # If it's too slow for CI, we might need to reduce size or optimize, but the requirement
    # is to verify it doesn't crash.

    with (
        patch("coreason_adlc_api.middleware.budget.BudgetService.check_budget_guardrail", return_value=True),
        patch("coreason_adlc_api.middleware.proxy.InferenceProxyService.execute_inference", return_value=mock_response),
        patch("coreason_adlc_api.middleware.telemetry.TelemetryService.async_log_telemetry", new=AsyncMock()) as mock_log,
        patch("coreason_adlc_api.middleware.proxy.litellm.token_counter", return_value=100),
        patch(
            "coreason_adlc_api.middleware.proxy.litellm.model_cost",
            {"gpt-4": {"input_cost_per_token": 0, "output_cost_per_token": 0}},
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post(
                "/api/v1/chat/completions",
                json=payload,
                headers={"Authorization": mock_auth_header},
                timeout=30.0,  # Increase timeout for real PII scrubbing
            )

            assert resp.status_code == 200

            # Verify telemetry received the huge payload (scrubbed)
            mock_log.assert_called_once()
            call_kwargs = mock_log.call_args[1]

            # Assertion depends on environment
            if HAS_PRESIDIO:
                # Since the payload is > 1MB, the scrubber should replace it with the placeholder
                assert call_kwargs["input_text"] == "<REDACTED: PAYLOAD TOO LARGE FOR PII ANALYSIS>"
            else:
                # Fallback message
                assert call_kwargs["input_text"] == "<REDACTED: PII ANALYZER MISSING>"


@pytest.mark.asyncio
async def test_chat_deeply_nested_json(mock_auth_header: str) -> None:
    """
    Test sending deeply nested JSON to check for recursion limits or parsing crashes.
    """
    # Create deeply nested messages structure
    depth = 1000
    nested_context: Dict[str, Any] = {}
    current = nested_context
    for _ in range(depth):
        current["next"] = {}
        current = current["next"]

    payload = {
        "model": "gpt-4",
        "messages": [{"role": "user", "content": "hello"}],
        "auc_id": "project-robustness",
        "user_context": nested_context,
    }

    with (
        patch("coreason_adlc_api.middleware.budget.BudgetService.check_budget_guardrail", return_value=True),
        patch("coreason_adlc_api.middleware.proxy.InferenceProxyService.execute_inference", return_value={
            "id": "chatcmpl-nested",
            "object": "chat.completion",
            "created": 1234567890,
            "model": "gpt-4",
            "choices": [],
            "usage": {"total_tokens": 10},
        }),
        patch("coreason_adlc_api.middleware.telemetry.TelemetryService.async_log_telemetry", new=AsyncMock()),
        patch("coreason_adlc_api.middleware.proxy.litellm.token_counter", return_value=100),
        patch(
            "coreason_adlc_api.middleware.proxy.litellm.model_cost",
            {"gpt-4": {"input_cost_per_token": 0, "output_cost_per_token": 0}},
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            try:
                resp = await ac.post(
                    "/api/v1/chat/completions", json=payload, headers={"Authorization": mock_auth_header}
                )
                assert resp.status_code != 500
            except RecursionError:
                pytest.fail("Application crashed with RecursionError")


@pytest.mark.asyncio
async def test_chat_zalgo_text(mock_auth_header: str) -> None:
    """
    Test sending malformed/Zalgo Unicode text to verify string handling stability.
    """
    # Zalgo text generator style characters
    zalgo_text = "H̡e̢l̡l̢o̡ ̢W̡o̢r̡l̢d̡" * 100

    payload = {
        "model": "gpt-4",
        "messages": [{"role": "user", "content": zalgo_text}],
        "auc_id": "project-robustness",
    }

    mock_response = {
        "id": "chatcmpl-zalgo",
        "object": "chat.completion",
        "created": 1234567890,
        "model": "gpt-4",
        "choices": [{"message": {"content": "Zalgo Processed"}}],
        "usage": {"total_tokens": 10},
    }

    # Do not mock scrub_pii_payload, we want to test real processing
    with (
        patch("coreason_adlc_api.middleware.budget.BudgetService.check_budget_guardrail", return_value=True),
        patch("coreason_adlc_api.middleware.proxy.InferenceProxyService.execute_inference", return_value=mock_response),
        patch("coreason_adlc_api.middleware.telemetry.TelemetryService.async_log_telemetry", new=AsyncMock()) as mock_log,
        patch("coreason_adlc_api.middleware.proxy.litellm.token_counter", return_value=100),
        patch(
            "coreason_adlc_api.middleware.proxy.litellm.model_cost",
            {"gpt-4": {"input_cost_per_token": 0, "output_cost_per_token": 0}},
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post("/api/v1/chat/completions", json=payload, headers={"Authorization": mock_auth_header})

            assert resp.status_code == 200

            # Verify telemetry was called (implies scrubbing finished)
            mock_log.assert_called_once()
