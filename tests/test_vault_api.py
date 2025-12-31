# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient
from coreason_adlc_api.app import app
from coreason_adlc_api.auth.identity import UserIdentity
from coreason_adlc_api.vault.service import VaultService

# We need to mock get_vault_service dependency in the app, or mock its internals.
# Since we are testing API, mocking the service is cleaner.

@pytest.fixture
def client():
    return TestClient(app)

@pytest.fixture
def mock_user_identity():
    return UserIdentity(
        oid=uuid4(),
        email="test@example.com",
        groups=[],
        full_name="Test User"
    )

@pytest.fixture
def mock_vault_service():
    service = MagicMock(spec=VaultService)
    service.store_secret = AsyncMock()
    service.get_secret = AsyncMock()
    return service

def test_store_secret_endpoint(client, mock_user_identity, mock_vault_service):
    # Override dependencies
    app.dependency_overrides["coreason_adlc_api.routers.vault.get_vault_service"] = lambda: mock_vault_service
    app.dependency_overrides["coreason_adlc_api.auth.identity.parse_and_validate_token"] = lambda: mock_user_identity

    mock_vault_service.store_secret.return_value = uuid4()

    response = client.post(
        "/api/v1/vault/secrets",
        json={
            "auc_id": "test-project",
            "service_name": "openai_api_key",
            "raw_api_key": "sk-1234567890"
        },
        headers={"Authorization": "Bearer mock_token"}
    )

    assert response.status_code == 201
    data = response.json()
    assert data["auc_id"] == "test-project"
    assert "secret_id" in data

    mock_vault_service.store_secret.assert_awaited_once()

    # Clean up overrides
    app.dependency_overrides = {}
