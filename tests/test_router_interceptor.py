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
from typing import Any
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from coreason_adlc_api.app import app
from coreason_adlc_api.auth.identity import UserIdentity, parse_and_validate_token

# Router is already registered in app.py now.
client = TestClient(app)


@pytest.fixture
def mock_user_identity() -> Any:
    user = UserIdentity(oid=uuid.uuid4(), email="test@example.com", groups=[uuid.uuid4()], full_name="Test User")
    # Override the dependency
    app.dependency_overrides[parse_and_validate_token] = lambda: user
    yield user
    del app.dependency_overrides[parse_and_validate_token]


@pytest.fixture
def mock_middleware() -> Any:
    with (
        mock.patch("coreason_adlc_api.routers.interceptor.check_budget_guardrail") as mock_budget,
        mock.patch("coreason_adlc_api.routers.interceptor.execute_inference_proxy") as mock_proxy,
        mock.patch("coreason_adlc_api.routers.interceptor.scrub_pii_payload") as mock_scrub,
        mock.patch("coreason_adlc_api.routers.interceptor.async_log_telemetry") as mock_log,
        mock.patch("coreason_adlc_api.routers.interceptor.litellm.token_counter") as mock_token_counter,
        mock.patch("coreason_adlc_api.routers.interceptor.litellm.model_cost", {"gpt-4": {"input_cost_per_token": 0.03, "output_cost_per_token": 0.06}})
    ):
        mock_budget.return_value = True
        mock_proxy.return_value = {"choices": [{"message": {"content": "response content"}}]}
        mock_scrub.side_effect = lambda x: f"SCRUBBED[{x}]"
        mock_log.return_value = None
        mock_token_counter.return_value = 10  # 10 tokens

        yield mock_budget, mock_proxy, mock_scrub, mock_log, mock_token_counter


def test_interceptor_flow_success(mock_user_identity: Any, mock_middleware: Any) -> None:
    mock_budget, mock_proxy, mock_scrub, mock_log, mock_token_counter = mock_middleware

    payload = {
        "model": "gpt-4",
        "messages": [{"role": "user", "content": "hello world"}],
        "auc_id": "proj-1",
        "estimated_cost": 0.0001,  # Client tries to cheat with low estimate
    }

    response = client.post("/api/v1/chat/completions", json=payload)

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "response content"

    # Verify Middleware calls
    # Calculated Cost:
    # Input: 10 tokens * 0.03 = 0.3
    # Output: 500 tokens (buffer) * 0.06 = 30.0
    # Total: 30.3
    expected_cost = (10 * 0.03) + (500 * 0.06)

    # We assert that the budget check uses the server-calculated cost, not the client's 0.0001
    mock_budget.assert_called_once_with(mock_user_identity.oid, expected_cost)

    mock_proxy.assert_called_once()
    assert mock_proxy.call_args[1]["model"] == "gpt-4"
    assert mock_proxy.call_args[1]["auc_id"] == "proj-1"

    # Scrub called twice (input and output)
    assert mock_scrub.call_count == 2

    mock_log.assert_called_once()
    log_kwargs = mock_log.call_args[1]
    assert log_kwargs["user_id"] == mock_user_identity.oid
    assert log_kwargs["model_name"] == "gpt-4"
    assert "SCRUBBED" in log_kwargs["input_text"]
    assert "SCRUBBED" in log_kwargs["output_text"]
