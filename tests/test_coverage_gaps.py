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

# Ensure router is included (it was included in previous test file, but app state persists?
# Usually best to include safe check or just rely on it being idempotent or already there)
# Note: app is imported from coreason_adlc_api.app.
# If tests run in same process, it might be already modified.
# But pytest isolates slightly. Let's assume we need to override dependency.

client = TestClient(app)


@pytest.fixture
def mock_user_identity() -> Any:
    user = UserIdentity(oid=uuid.uuid4(), email="test@example.com", groups=[uuid.uuid4()], full_name="Test User")
    app.dependency_overrides[parse_and_validate_token] = lambda: user
    yield user
    del app.dependency_overrides[parse_and_validate_token]


def test_interceptor_proxy_exception(mock_user_identity: Any) -> None:
    """Test exception during proxy call (Lines 86-89 in interceptor.py)."""
    with (
        mock.patch("coreason_adlc_api.routers.interceptor.check_budget_guardrail") as mock_budget,
        mock.patch("coreason_adlc_api.routers.interceptor.execute_inference_proxy") as mock_proxy,
    ):
        mock_budget.return_value = True
        mock_proxy.side_effect = Exception("Proxy Failure")

        payload = {"model": "gpt-4", "messages": [], "auc_id": "proj-1"}

        # Should raise 500 or let exception propagate?
        # interceptor.py re-raises. FastAPI converts unhandled exceptions to 500.
        with pytest.raises(Exception, match="Proxy Failure"):
            client.post("/api/v1/chat/completions", json=payload)


def test_interceptor_malformed_response(mock_user_identity: Any) -> None:
    """Test malformed response from LLM (Lines 95-96 in interceptor.py)."""
    with (
        mock.patch("coreason_adlc_api.routers.interceptor.check_budget_guardrail") as mock_budget,
        mock.patch("coreason_adlc_api.routers.interceptor.execute_inference_proxy") as mock_proxy,
        mock.patch("coreason_adlc_api.routers.interceptor.scrub_pii_payload") as mock_scrub,
        mock.patch("coreason_adlc_api.routers.interceptor.async_log_telemetry"),
    ):
        mock_budget.return_value = True
        # Return response that lacks "choices"
        mock_proxy.return_value = {"error": "something"}
        mock_scrub.return_value = "scrubbed"

        payload = {"model": "gpt-4", "messages": [], "auc_id": "proj-1"}

        response = client.post("/api/v1/chat/completions", json=payload)

        assert response.status_code == 200
        # Response content should be "" (empty string) because extraction failed
        # But we return the RAW response object.
        assert response.json() == {"error": "something"}
