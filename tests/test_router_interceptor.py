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
        mock.patch(
            "coreason_adlc_api.routers.interceptor.litellm.model_cost",
            {
                "gpt-4": {
                    "input_cost_per_token": 0.03,
                    "output_cost_per_token": 0.06,
                }
            },
        ),
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


def test_interceptor_cost_estimation_fallback(mock_user_identity: Any, mock_middleware: Any) -> None:
    mock_budget, mock_proxy, mock_scrub, mock_log, mock_token_counter = mock_middleware

    # Simulate litellm failure
    mock_token_counter.side_effect = Exception("LiteLLM Down")

    payload = {
        "model": "gpt-4",
        "messages": [{"role": "user", "content": "hello world"}],
        "auc_id": "proj-1",
        "estimated_cost": 0.5,  # Client input
    }

    response = client.post("/api/v1/chat/completions", json=payload)

    assert response.status_code == 200

    # Fallback cost is 0.01
    mock_budget.assert_called_once_with(mock_user_identity.oid, 0.01)


def test_interceptor_proxy_exception(mock_user_identity: Any, mock_middleware: Any) -> None:
    mock_budget, mock_proxy, mock_scrub, mock_log, mock_token_counter = mock_middleware

    mock_proxy.side_effect = Exception("Proxy Failed")

    payload = {
        "model": "gpt-4",
        "messages": [{"role": "user", "content": "hello"}],
        "auc_id": "proj-1",
    }

    with pytest.raises(Exception, match="Proxy Failed"):
        client.post("/api/v1/chat/completions", json=payload)


def test_interceptor_malformed_response(mock_user_identity: Any, mock_middleware: Any) -> None:
    mock_budget, mock_proxy, mock_scrub, mock_log, mock_token_counter = mock_middleware

    # Return response that lacks choices/message/content structure
    mock_proxy.return_value = {"error": "something"}

    payload = {
        "model": "gpt-4",
        "messages": [{"role": "user", "content": "hello"}],
        "auc_id": "proj-1",
    }

    response = client.post("/api/v1/chat/completions", json=payload)

    assert response.status_code == 200
    # Telemetry should log empty output (scrubbed)
    mock_log.assert_called()
    assert "SCRUBBED" in mock_log.call_args[1]["output_text"]


def test_interceptor_cost_estimation_model_unknown(mock_user_identity: Any, mock_middleware: Any) -> None:
    """
    Test scenario where token counting succeeds, but model cost lookup fails.
    This triggers the inner except block in estimate_request_cost.
    """
    mock_budget, mock_proxy, mock_scrub, mock_log, mock_token_counter = mock_middleware

    # Token counter works
    mock_token_counter.return_value = 100

    # But model cost lookup returns None or raises ValueError (simulated via side_effect on the mock dict if possible,
    # but we patched the DICT itself. We can't easily make dict.get raise.
    # Instead, we'll patch with a dict that doesn't have the model key.)

    # We need to re-patch the model_cost for this specific test case to return empty
    with mock.patch("coreason_adlc_api.routers.interceptor.litellm.model_cost", {}):
        payload = {
            "model": "unknown-model",
            "messages": [{"role": "user", "content": "hello"}],
            "auc_id": "proj-1",
        }

        response = client.post("/api/v1/chat/completions", json=payload)
        assert response.status_code == 200

        # Calculation logic in inner except block:
        # input_cost_per_token = 0.0000005
        # output_cost_per_token = 0.0000015
        # estimated_output = 500
        # total = (100 * 0.0000005) + (500 * 0.0000015)
        #       = 0.00005 + 0.00075 = 0.0008

        expected_cost = (100 * 0.0000005) + (500 * 0.0000015)

        mock_budget.assert_called_with(mock_user_identity.oid, expected_cost)
