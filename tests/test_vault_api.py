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
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from coreason_adlc_api.app import app
from coreason_adlc_api.vault.service import retrieve_decrypted_secret, store_secret


@pytest.fixture
def mock_auth_header(mock_oidc_factory: Any) -> str:
    user_uuid = str(uuid.uuid4())
    token = mock_oidc_factory(
        {
            "sub": user_uuid,
            "oid": user_uuid,
            "name": "Vault Tester",
            "email": "vault@coreason.ai",
        }
    )
    return f"Bearer {token}"


@pytest.mark.asyncio
async def test_store_secret_api(mock_auth_header: str) -> None:
    """Test POST /vault/secrets endpoint via API."""

    # Mock store_secret service call
    with (
        patch("coreason_adlc_api.routers.vault.store_secret", new=AsyncMock(return_value=uuid.uuid4())) as mock_store,
        patch("coreason_adlc_api.routers.vault.map_groups_to_projects", new=AsyncMock(return_value=["project-omega"])),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            payload = {"auc_id": "project-omega", "service_name": "openai", "raw_api_key": "sk-test-key"}
            resp = await ac.post("/api/v1/vault/secrets", json=payload, headers={"Authorization": mock_auth_header})

            if resp.status_code != 201:
                print(resp.json())
            assert resp.status_code == 201
            data = resp.json()
            assert data["auc_id"] == "project-omega"
            assert "secret_id" in data

            # Verify mock called with correct identity
            mock_store.assert_called_once()
            args = mock_store.call_args
            # args: (auc_id, service_name, raw_api_key, user_uuid)
            assert args.kwargs["auc_id"] == "project-omega"
            assert args.kwargs["raw_api_key"] == "sk-test-key"


@pytest.mark.asyncio
async def test_retrieve_decrypted_secret_logic(mock_db_session: AsyncMock) -> None:
    """Test the internal retrieval logic with mocked DB."""

    # Mock row
    mock_row = ["mock_encrypted_string"]
    mock_db_session.execute.return_value.fetchone.return_value = mock_row

    with patch("coreason_adlc_api.vault.service.vault_crypto") as mock_crypto:
        mock_crypto.decrypt_secret.return_value = "decrypted-key"

        result = await retrieve_decrypted_secret(mock_db_session, "project-omega", "openai")

        assert result == "decrypted-key"
        mock_db_session.execute.assert_called_once()
        mock_crypto.decrypt_secret.assert_called_once_with("mock_encrypted_string")


@pytest.mark.asyncio
async def test_retrieve_secret_not_found(mock_db_session: AsyncMock) -> None:
    """Test retrieval when secret does not exist."""
    mock_db_session.execute.return_value.fetchone.return_value = None

    with pytest.raises(ValueError, match="No secret found"):
        await retrieve_decrypted_secret(mock_db_session, "project-omega", "missing")


@pytest.mark.asyncio
async def test_store_secret_logic(mock_db_session: AsyncMock) -> None:
    """Test the internal store logic with mocked DB."""
    generated_uuid = uuid.uuid4()
    mock_row = [generated_uuid]
    mock_db_session.execute.return_value.fetchone.return_value = mock_row

    with patch("coreason_adlc_api.vault.service.vault_crypto") as mock_crypto:
        mock_crypto.encrypt_secret.return_value = "encrypted-data"

        sid = await store_secret(mock_db_session, "project-omega", "openai", "raw-key", uuid.uuid4())

        assert sid == generated_uuid
        mock_db_session.execute.assert_called_once()
        mock_db_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_store_secret_failure(mock_db_session: AsyncMock) -> None:
    """Test store_secret handling of DB errors."""
    # Simulate DB error
    mock_db_session.execute.side_effect = Exception("DB Connection Lost")

    with patch("coreason_adlc_api.vault.service.vault_crypto") as mock_crypto:
        mock_crypto.encrypt_secret.return_value = "encrypted-data"

        with pytest.raises(HTTPException) as exc:
            await store_secret(mock_db_session, "project-omega", "openai", "raw-key", uuid.uuid4())

        assert exc.value.status_code == 500
        mock_db_session.rollback.assert_called_once()


@pytest.mark.asyncio
async def test_store_secret_no_id_returned(mock_db_session: AsyncMock) -> None:
    """Test store_secret handling when insert returns no row (unlikely but defensive)."""
    mock_db_session.execute.return_value.fetchone.return_value = None

    with patch("coreason_adlc_api.vault.service.vault_crypto") as mock_crypto:
        mock_crypto.encrypt_secret.return_value = "encrypted-data"

        with pytest.raises(HTTPException) as exc:
            await store_secret(mock_db_session, "project-omega", "openai", "raw-key", uuid.uuid4())

        assert exc.value.status_code == 500


@pytest.mark.asyncio
async def test_store_secret_api_forbidden(mock_auth_header: str) -> None:
    """Test POST /vault/secrets endpoint - Forbidden."""
    with patch("coreason_adlc_api.routers.vault.map_groups_to_projects", new=AsyncMock(return_value=["other-project"])):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            payload = {"auc_id": "project-omega", "service_name": "openai", "raw_api_key": "sk-test-key"}
            resp = await ac.post("/api/v1/vault/secrets", json=payload, headers={"Authorization": mock_auth_header})

            assert resp.status_code == 403
