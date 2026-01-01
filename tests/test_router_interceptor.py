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
from coreason_adlc_api.middleware.budget import BudgetService
from coreason_adlc_api.middleware.proxy import InferenceProxyService
from coreason_adlc_api.routers.interceptor import (
    get_budget_service,
    get_proxy_service,
)

client = TestClient(app)


@pytest.fixture
def mock_user_identity() -> Any:
    user = UserIdentity(oid=uuid.uuid4(), email="test@example.com", groups=[uuid.uuid4()], full_name="Test User")
    app.dependency_overrides[parse_and_validate_token] = lambda: user
    yield user
    del app.dependency_overrides[parse_and_validate_token]


@pytest.fixture
def mock_services() -> Any:
    mock_budget = mock.AsyncMock(spec=BudgetService)
    mock_proxy = mock.AsyncMock(spec=InferenceProxyService)

    app.dependency_overrides[get_budget_service] = lambda: mock_budget
    app.dependency_overrides[get_proxy_service] = lambda: mock_proxy

    # Defaults
    mock_budget.check_budget_guardrail.return_value = True
    # Return a valid dict that matches the response model structure partially or fully
    # Since response_model is ChatCompletionResponse, we need to provide compatible data.
    mock_proxy.execute_inference.return_value = {
        "id": "chatcmpl-123",
        "created": 1677652288,
        "model": "gpt-4",
        "choices": [{"message": {"content": "response content"}, "index": 0, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    }
    mock_proxy.estimate_request_cost.return_value = 1.23  # Specific estimated cost

    yield mock_budget, mock_proxy

    del app.dependency_overrides[get_budget_service]
    del app.dependency_overrides[get_proxy_service]


@pytest.fixture
def mock_ier_logger() -> Any:
    # Patch the class in the router module
    with mock.patch("coreason_adlc_api.routers.interceptor.IERLogger") as m:
        instance = mock.MagicMock()
        m.return_value = instance
        yield instance


@pytest.fixture
def mock_scrub() -> Any:
    with mock.patch("coreason_adlc_api.routers.interceptor.scrub_pii_payload") as m:
        # Need to return a coroutine because router calls await
        async def side_effect(x: str) -> str:
            return f"SCRUBBED[{x}]"

        m.side_effect = side_effect
        yield m


def test_interceptor_flow_success(
    mock_user_identity: Any, mock_services: Any, mock_scrub: Any, mock_ier_logger: Any
) -> None:
    mock_budget, mock_proxy = mock_services

    payload = {
        "model": "gpt-4",
        "messages": [{"role": "user", "content": "hello world"}],
        "auc_id": "proj-1",
        "estimated_cost": 0.0001,
    }

    response = client.post("/api/v1/chat/completions", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["choices"][0]["message"]["content"] == "response content"
    assert data["id"] == "chatcmpl-123"

    # Verify Budget Check with estimated cost from service
    mock_budget.check_budget_guardrail.assert_called_once_with(mock_user_identity.oid, 1.23)

    # Verify Proxy Call
    mock_proxy.execute_inference.assert_called_once()
    kwargs = mock_proxy.execute_inference.call_args[1]
    assert kwargs["model"] == "gpt-4"
    assert kwargs["auc_id"] == "proj-1"
    assert kwargs["messages"] == [{"role": "user", "content": "hello world"}]

    # Verify Scrubbing
    assert mock_scrub.call_count == 2  # Input and Output

    # Verify Telemetry via Veritas IERLogger
    mock_ier_logger.log_llm_transaction.assert_called_once()
    log_kwargs = mock_ier_logger.log_llm_transaction.call_args[1]
    assert log_kwargs["user_id"] == str(mock_user_identity.oid)
    assert log_kwargs["model"] == "gpt-4"
    assert "SCRUBBED" in log_kwargs["prompt_preview"]
    assert "SCRUBBED" in log_kwargs["response_preview"]
    assert log_kwargs["input_tokens"] == 10
    assert log_kwargs["output_tokens"] == 20
    assert isinstance(log_kwargs["cost_usd"], float)


def test_interceptor_proxy_exception(mock_user_identity: Any, mock_services: Any) -> None:
    mock_budget, mock_proxy = mock_services

    mock_proxy.execute_inference.side_effect = Exception("Proxy Failed")

    payload = {
        "model": "gpt-4",
        "messages": [{"role": "user", "content": "hello"}],
        "auc_id": "proj-1",
    }

    with pytest.raises(Exception, match="Proxy Failed"):
        client.post("/api/v1/chat/completions", json=payload)


def test_interceptor_malformed_response(
    mock_user_identity: Any, mock_services: Any, mock_scrub: Any, mock_ier_logger: Any
) -> None:
    mock_budget, mock_proxy = mock_services

    # Let's return valid structural data but empty content to simulate "malformed" content extraction case
    mock_proxy.execute_inference.return_value = {
        "id": "err",
        "created": 1,
        "model": "gpt-4",
        "choices": [],  # Empty choices
    }

    payload = {
        "model": "gpt-4",
        "messages": [{"role": "user", "content": "hello"}],
        "auc_id": "proj-1",
    }

    response = client.post("/api/v1/chat/completions", json=payload)
    assert response.status_code == 200

    # Telemetry should log empty output
    mock_ier_logger.log_llm_transaction.assert_called()
    assert "SCRUBBED" in mock_ier_logger.log_llm_transaction.call_args[1]["response_preview"]
