from typing import Any, Callable
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

from coreason_adlc_api.app import app
from coreason_adlc_api.middleware.budget import check_budget_status
from coreason_adlc_api.middleware.pii import scrub_pii_recursive


# Test PII Recursion
def test_scrub_pii_recursive_dict() -> None:
    data = {"key1": "John Doe", "nested": {"key2": "john.doe@example.com", "safe": "Nothing here"}}

    # We mock scrub_pii_payload to simulate PII detection
    with patch("coreason_adlc_api.middleware.pii.scrub_pii_payload") as mock_scrub:

        def side_effect(val: str) -> str:
            if "John Doe" in val:
                return "<REDACTED PERSON>"
            if "john.doe@example.com" in val:
                return "<REDACTED EMAIL>"
            return val

        mock_scrub.side_effect = side_effect

        scrubbed = scrub_pii_recursive(data)

        assert scrubbed["key1"] == "<REDACTED PERSON>"
        assert scrubbed["nested"]["key2"] == "<REDACTED EMAIL>"
        assert scrubbed["nested"]["safe"] == "Nothing here"


def test_scrub_pii_recursive_list() -> None:
    data = ["John Doe", "Safe"]
    with patch("coreason_adlc_api.middleware.pii.scrub_pii_payload") as mock_scrub:
        mock_scrub.side_effect = lambda x: "<REDACTED PERSON>" if "John" in x else x

        scrubbed = scrub_pii_recursive(data)
        assert scrubbed[0] == "<REDACTED PERSON>"
        assert scrubbed[1] == "Safe"


def test_scrub_pii_recursive_primitive() -> None:
    """Test recursion on a primitive type (int) to cover the 'else' branch."""
    data = 12345
    scrubbed = scrub_pii_recursive(data)
    assert scrubbed == 12345


# Test Budget Check Status
def test_check_budget_status_under_limit() -> None:
    user_id = uuid4()
    with patch("coreason_adlc_api.middleware.budget.get_redis_client") as mock_get_client:
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis

        # Scenario: Spend is 10.0 (micros = 10,000,000), limit is 50.0 (50,000,000)
        mock_redis.get.return_value = b"10000000"

        assert check_budget_status(user_id) is True


def test_check_budget_status_over_limit() -> None:
    user_id = uuid4()
    with patch("coreason_adlc_api.middleware.budget.get_redis_client") as mock_get_client:
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis

        # Scenario: Spend is 60.0 (micros = 60,000,000)
        mock_redis.get.return_value = b"60000000"

        assert check_budget_status(user_id) is False


def test_check_budget_status_no_key() -> None:
    user_id = uuid4()
    with patch("coreason_adlc_api.middleware.budget.get_redis_client") as mock_get_client:
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis

        mock_redis.get.return_value = None

        assert check_budget_status(user_id) is True


def test_check_budget_status_error() -> None:
    user_id = uuid4()
    with patch("coreason_adlc_api.middleware.budget.get_redis_client") as mock_get_client:
        # We need the client call to succeed but the client.get to raise
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis
        mock_redis.get.side_effect = Exception("Redis Down")

        # Fail closed -> False
        assert check_budget_status(user_id) is False


# Test Router Endpoint Logic (Unit level via Router function calls if possible, or Client)
# We can test the validate_draft function in the client, but that requires a running app or full mock.
# Easier to test the logic by mocking the components used in the router.
# But since we added an endpoint, let's verify via client by mocking httpx.


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
    with (
        patch("coreason_adlc_api.routers.workbench.check_budget_status") as mock_budget,
        patch("coreason_adlc_api.routers.workbench.scrub_pii_recursive") as mock_pii,
    ):
        # Scenario 1: All Valid
        mock_budget.return_value = True
        mock_pii.return_value = draft_payload["oas_content"]  # No change -> No PII

        resp = client.post("/api/v1/workbench/validate", json=draft_payload, headers=headers)
        # Note: Depending on router registration, prefix might be /api/v1/workbench or just /workbench
        # Memory says "/api/v1" prefix.

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
