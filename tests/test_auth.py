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
from coreason_adlc_api.app import app
from coreason_adlc_api.auth.identity import (
    UserIdentity,
    map_groups_to_projects,
    parse_and_validate_token,
    upsert_user,
)
from coreason_adlc_api.config import settings
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def mock_token() -> tuple[str, str, str]:
    user_uuid = str(uuid.uuid4())
    group_uuid = str(uuid.uuid4())

    payload = {
        "sub": user_uuid,
        "oid": user_uuid,
        "name": "Test User",
        "email": "test@coreason.ai",
        "groups": [group_uuid],
        "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1),
    }
    return (
        jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM),
        user_uuid,
        group_uuid,
    )


@pytest.mark.asyncio
async def test_parse_and_validate_token(mock_token: tuple[str, str, str]) -> None:
    token, user_uuid, group_uuid = mock_token
    header = f"Bearer {token}"

    identity = await parse_and_validate_token(header)

    assert str(identity.oid) == user_uuid
    assert identity.email == "test@coreason.ai"
    assert identity.full_name == "Test User"
    assert str(identity.groups[0]) == group_uuid


@pytest.mark.asyncio
async def test_parse_token_invalid_header() -> None:
    with pytest.raises(HTTPException) as exc:
        await parse_and_validate_token("InvalidHeader")
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_parse_token_expired() -> None:
    payload = {
        "oid": str(uuid.uuid4()),
        "exp": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1),
    }
    token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    header = f"Bearer {token}"

    with pytest.raises(HTTPException) as exc:
        await parse_and_validate_token(header)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_parse_token_invalid_signature() -> None:
    token = jwt.encode({"oid": str(uuid.uuid4())}, "wrong-secret", algorithm=settings.JWT_ALGORITHM)
    header = f"Bearer {token}"

    with pytest.raises(HTTPException) as exc:
        await parse_and_validate_token(header)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_parse_token_malformed_claims() -> None:
    # Missing required 'oid' or bad format
    token = jwt.encode({"sub": "no-oid"}, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    header = f"Bearer {token}"

    with pytest.raises(HTTPException) as exc:
        await parse_and_validate_token(header)
    assert exc.value.status_code == 401


# Logic Tests with Mocked DB


@pytest.mark.asyncio
async def test_upsert_user() -> None:
    user_uuid = uuid.uuid4()
    identity = UserIdentity(oid=user_uuid, email="upsert@coreason.ai", groups=[], full_name="Upsert Test")

    mock_pool = AsyncMock()
    with patch("coreason_adlc_api.auth.identity.get_pool", return_value=mock_pool):
        await upsert_user(identity)
        mock_pool.execute.assert_called_once()
        args = mock_pool.execute.call_args[0]
        assert "INSERT INTO identity.users" in args[0]
        assert args[1] == user_uuid


@pytest.mark.asyncio
async def test_upsert_user_failure() -> None:
    user_uuid = uuid.uuid4()
    identity = UserIdentity(oid=user_uuid, email="upsert@coreason.ai", groups=[], full_name="Upsert Test")

    mock_pool = AsyncMock()
    mock_pool.execute.side_effect = Exception("DB Error")

    with patch("coreason_adlc_api.auth.identity.get_pool", return_value=mock_pool):
        # Should NOT raise, just log error
        await upsert_user(identity)


@pytest.mark.asyncio
async def test_map_groups_to_projects() -> None:
    group_oid = uuid.uuid4()

    mock_pool = AsyncMock()
    # Mock return value for fetch
    mock_pool.fetch.return_value = [
        {"auc_id": "project-alpha"},
        {"auc_id": "project-beta"},
        {"auc_id": "project-alpha"},  # Duplicate to test dedupe
    ]

    with patch("coreason_adlc_api.auth.identity.get_pool", return_value=mock_pool):
        projects = await map_groups_to_projects([group_oid])

        mock_pool.fetch.assert_called_once()
        assert len(projects) == 2
        assert "project-alpha" in projects
        assert "project-beta" in projects


@pytest.mark.asyncio
async def test_map_groups_failure() -> None:
    group_oid = uuid.uuid4()

    mock_pool = AsyncMock()
    mock_pool.fetch.side_effect = Exception("DB Error")

    with patch("coreason_adlc_api.auth.identity.get_pool", return_value=mock_pool):
        projects = await map_groups_to_projects([group_oid])
        assert projects == []


@pytest.mark.asyncio
async def test_auth_endpoints() -> None:
    # Mock upsert_user where it is IMPORTED in routers/auth.py
    with patch("coreason_adlc_api.routers.auth.upsert_user", new=AsyncMock()) as mock_upsert:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            # Device Code
            resp = await ac.post("/api/v1/auth/device-code")
            assert resp.status_code == 200
            data = resp.json()
            assert "device_code" in data

            # Token Poll
            resp = await ac.post("/api/v1/auth/token", json={"device_code": data["device_code"]})
            assert resp.status_code == 200
            token_data = resp.json()
            assert "access_token" in token_data

            # Verify side-effect
            mock_upsert.assert_called_once()
