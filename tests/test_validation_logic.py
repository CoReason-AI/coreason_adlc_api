from typing import Any, Callable
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from coreason_adlc_api.app import app
from coreason_adlc_api.middleware.budget import check_budget_status

# PII Recursion tests removed as they test external library logic.


# Test Budget Check Status
@pytest.mark.asyncio
async def test_check_budget_status_under_limit() -> None:
    user_id = uuid4()
    # Mock QuotaGuard, not Redis directly
    with patch("coreason_adlc_api.middleware.budget.QuotaGuard") as mock_guard_cls:
        mock_instance = AsyncMock()
        mock_guard_cls.return_value = mock_instance
        # check_status returns boolean
        mock_instance.check_status.return_value = True

        assert await check_budget_status(user_id) is True


@pytest.mark.asyncio
async def test_check_budget_status_over_limit() -> None:
    user_id = uuid4()
    with patch("coreason_adlc_api.middleware.budget.QuotaGuard") as mock_guard_cls:
        mock_instance = AsyncMock()
        mock_guard_cls.return_value = mock_instance
        mock_instance.check_status.return_value = False

        assert await check_budget_status(user_id) is False


@pytest.mark.asyncio
async def test_check_budget_status_error() -> None:
    user_id = uuid4()
    with patch("coreason_adlc_api.middleware.budget.QuotaGuard") as mock_guard_cls:
        mock_instance = AsyncMock()
        mock_guard_cls.return_value = mock_instance
        mock_instance.check_status.side_effect = Exception("Redis Down")

        # Fail closed -> False
        assert await check_budget_status(user_id) is False


def test_client_validate_draft() -> None:
    from coreason_adlc_api.client import CoreasonClient

    client = CoreasonClient()
    draft_data = {"auc_id": "test-project", "title": "Test Draft", "oas_content": {"content": "Test"}}

    with patch.object(client, "post") as mock_post:
        mock_response = MagicMock()
        mock_response.json.return_value = {"is_valid": False, "issues": ["PII Detected"]}
        mock_post.return_value = mock_response

        issues = client.validate_draft(draft_data)

        assert issues == ["PII Detected"]
        mock_post.assert_called_with("/workbench/validate", json=draft_data)


def test_workbench_validate_endpoint_integration(mock_oidc_factory: Callable[[dict[str, Any] | None], str]) -> None:
    """
    Integration test for POST /workbench/validate to cover router logic.
    """
    client = TestClient(app)
    token = mock_oidc_factory(None)
    headers = {"Authorization": f"Bearer {token}"}

    draft_payload = {"auc_id": "test-project", "title": "Validation Test", "oas_content": {"content": "Secret Data"}}

    # Mock the internal logic checks
    # Note: scrub_pii_recursive is imported in router from veritas (synchronous)
    # check_budget_status is async
    with (
        patch("coreason_adlc_api.routers.workbench.check_budget_status", new_callable=AsyncMock) as mock_budget,
        patch("coreason_adlc_api.routers.workbench.scrub_pii_recursive") as mock_pii,
    ):
        # Scenario 1: All Valid
        mock_budget.return_value = True
        mock_pii.return_value = draft_payload["oas_content"]  # No change -> No PII

        resp = client.post("/api/v1/workbench/validate", json=draft_payload, headers=headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data["is_valid"] is True
        assert data["issues"] == []

        # Scenario 2: Budget Failure
        mock_budget.return_value = False
        resp = client.post("/api/v1/workbench/validate", json=draft_payload, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["is_valid"] is False
        assert "Budget Limit Reached" in resp.json()["issues"]

        # Scenario 3: PII Detected
        mock_budget.return_value = True
        mock_pii.return_value = {"content": "<REDACTED>"}  # Changed
        resp = client.post("/api/v1/workbench/validate", json=draft_payload, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["is_valid"] is False
        assert "PII Detected" in resp.json()["issues"]

        # Scenario 4: PII Check Exception
        mock_pii.side_effect = Exception("PII Crash")
        resp = client.post("/api/v1/workbench/validate", json=draft_payload, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["is_valid"] is False
        assert "PII Check Failed" in resp.json()["issues"]
