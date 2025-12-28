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
from httpx import ASGITransport, AsyncClient

from coreason_adlc_api.app import app
from coreason_adlc_api.config import settings
from coreason_adlc_api.vault.service import retrieve_decrypted_secret, store_secret


@pytest.fixture
def mock_auth_header() -> str:
    user_uuid = str(uuid.uuid4())
    payload = {
        "sub": user_uuid,
        "oid": user_uuid,
        "name": "Vault Tester",
        "email": "vault@coreason.ai",
        "groups": [],
        "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1),
    }
    token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
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
async def test_retrieve_decrypted_secret_logic() -> None:
    """Test the internal retrieval logic with mocked DB."""

    mock_pool = AsyncMock()
    # Mock row
    mock_row = {
        "encrypted_value": "mock_encrypted_string"
    }  # This string must be valid base64 if decrypt is called real

    # But wait, retrieve_decrypted_secret calls vault_crypto.decrypt_secret
    # If we don't mock vault_crypto, it will try to decrypt "mock_encrypted_string" and fail.

    with (
        patch("coreason_adlc_api.vault.service.get_pool", return_value=mock_pool),
        patch("coreason_adlc_api.vault.service.vault_crypto") as mock_crypto,
    ):
        mock_pool.fetchrow.return_value = mock_row
        mock_crypto.decrypt_secret.return_value = "decrypted-key"

        result = await retrieve_decrypted_secret("project-omega", "openai")

        assert result == "decrypted-key"
        mock_pool.fetchrow.assert_called_once()
        mock_crypto.decrypt_secret.assert_called_once_with("mock_encrypted_string")


@pytest.mark.asyncio
async def test_retrieve_secret_not_found() -> None:
    """Test retrieval when secret does not exist."""
    mock_pool = AsyncMock()
    mock_pool.fetchrow.return_value = None

    with patch("coreason_adlc_api.vault.service.get_pool", return_value=mock_pool):
        with pytest.raises(ValueError, match="No secret found"):
            await retrieve_decrypted_secret("project-omega", "missing")


@pytest.mark.asyncio
async def test_store_secret_logic() -> None:
    """Test the internal store logic with mocked DB."""
    mock_pool = AsyncMock()
    mock_row = {"secret_id": uuid.uuid4()}
    mock_pool.fetchrow.return_value = mock_row

    with (
        patch("coreason_adlc_api.vault.service.get_pool", return_value=mock_pool),
        patch("coreason_adlc_api.vault.service.vault_crypto") as mock_crypto,
    ):
        mock_crypto.encrypt_secret.return_value = "encrypted-data"

        sid = await store_secret("project-omega", "openai", "raw-key", uuid.uuid4())

        assert sid == mock_row["secret_id"]
        mock_pool.fetchrow.assert_called_once()
        # Verify SQL args
        args = mock_pool.fetchrow.call_args[0]
        assert "INSERT INTO vault.secrets" in args[0]
        assert "encrypted-data" in args  # should be passed


@pytest.mark.asyncio
async def test_store_secret_failure() -> None:
    """Test store_secret handling of DB errors."""
    mock_pool = AsyncMock()
    # Simulate DB error
    mock_pool.fetchrow.side_effect = Exception("DB Connection Lost")

    with (
        patch("coreason_adlc_api.vault.service.get_pool", return_value=mock_pool),
        patch("coreason_adlc_api.vault.service.vault_crypto") as mock_crypto,
    ):
        mock_crypto.encrypt_secret.return_value = "encrypted-data"

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await store_secret("project-omega", "openai", "raw-key", uuid.uuid4())

        assert exc.value.status_code == 500


@pytest.mark.asyncio
async def test_store_secret_no_id_returned() -> None:
    """Test store_secret handling when insert returns no row (unlikely but defensive)."""
    mock_pool = AsyncMock()
    mock_pool.fetchrow.return_value = None

    with (
        patch("coreason_adlc_api.vault.service.get_pool", return_value=mock_pool),
        patch("coreason_adlc_api.vault.service.vault_crypto") as mock_crypto,
    ):
        mock_crypto.encrypt_secret.return_value = "encrypted-data"

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await store_secret("project-omega", "openai", "raw-key", uuid.uuid4())

        assert exc.value.status_code == 500


@pytest.mark.asyncio
async def test_store_secret_api_forbidden(mock_auth_header: str) -> None:
    """Test POST /vault/secrets endpoint - Forbidden."""
    with patch("coreason_adlc_api.routers.vault.map_groups_to_projects", new=AsyncMock(return_value=["other-project"])):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            payload = {"auc_id": "project-omega", "service_name": "openai", "raw_api_key": "sk-test-key"}
            resp = await ac.post("/api/v1/vault/secrets", json=payload, headers={"Authorization": mock_auth_header})

            assert resp.status_code == 403
