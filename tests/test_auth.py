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
from typing import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import jwt
import pytest
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient, Request, Response

from coreason_adlc_api.app import app
from coreason_adlc_api.auth.identity import (
    UserIdentity,
    get_oidc_config,
    map_groups_to_projects,
    parse_and_validate_token,
    upsert_user,
)
from coreason_adlc_api.config import settings

# --- Helpers for RS256 ---


@pytest.fixture(scope="module")
def rsa_key_pair() -> tuple[RSAPrivateKey, RSAPublicKey]:
    """Generates a fresh RSA key pair for testing."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())
    public_key = private_key.public_key()

    return private_key, public_key


@pytest.fixture
def mock_oidc_setup(rsa_key_pair: tuple[RSAPrivateKey, RSAPublicKey]) -> Generator[RSAPrivateKey, None, None]:
    """Mocks the OIDC discovery and JWKS client to return the local public key."""
    private_key, public_key = rsa_key_pair

    # Mock OIDC Config
    config = {
        "device_authorization_endpoint": "https://mock.idp/device",
        "token_endpoint": "https://mock.idp/token",
        "jwks_uri": "https://mock.idp/.well-known/jwks.json",
        "issuer": f"{settings.OIDC_DOMAIN.rstrip('/')}/",
    }

    # Mock PyJWKClient
    mock_jwk_client = MagicMock()
    mock_signing_key = MagicMock()
    mock_signing_key.key = public_key
    mock_jwk_client.get_signing_key_from_jwt.return_value = mock_signing_key

    with patch("coreason_adlc_api.auth.identity._OIDC_CONFIG_CACHE", config):
        with patch("coreason_adlc_api.auth.identity._JWKS_CLIENT", mock_jwk_client):
            yield private_key


@pytest.fixture
def mock_token(mock_oidc_setup: RSAPrivateKey) -> tuple[str, str, str]:
    private_key = mock_oidc_setup
    user_uuid = str(uuid.uuid4())
    group_uuid = str(uuid.uuid4())

    payload = {
        "sub": user_uuid,
        "oid": user_uuid,
        "name": "Test User",
        "email": "test@coreason.ai",
        "groups": [group_uuid],
        "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1),
        "iss": f"{settings.OIDC_DOMAIN.rstrip('/')}/",
        "aud": settings.OIDC_AUDIENCE,
    }

    token = jwt.encode(payload, private_key, algorithm="RS256")
    return (token, user_uuid, group_uuid)


@pytest.mark.asyncio
async def test_get_oidc_config() -> None:
    # Test valid fetch
    mock_req = Request("GET", "https://example.auth0.com/.well-known/openid-configuration")
    mock_resp = Response(
        200, json={"jwks_uri": "http://jwks", "device_authorization_endpoint": "http://device"}, request=mock_req
    )

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    # Force clear cache
    with patch("coreason_adlc_api.auth.identity._OIDC_CONFIG_CACHE", None):
        with patch("coreason_adlc_api.auth.identity.get_http_client", return_value=mock_client):
            config = await get_oidc_config()
            assert config["jwks_uri"] == "http://jwks"


@pytest.mark.asyncio
async def test_get_oidc_config_failure() -> None:
    mock_client = AsyncMock()
    # Use httpx.RequestError to be caught by httpx.HTTPError
    mock_client.get.side_effect = httpx.RequestError("Network Error", request=Request("GET", "url"))
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("coreason_adlc_api.auth.identity._OIDC_CONFIG_CACHE", None):
        with patch("coreason_adlc_api.auth.identity.get_http_client", return_value=mock_client):
            with pytest.raises(HTTPException) as exc:
                await get_oidc_config()
            assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_get_oidc_config_missing_jwks_uri() -> None:
    mock_req = Request("GET", "https://example.auth0.com/.well-known/openid-configuration")
    mock_resp = Response(
        200,
        json={
            "device_authorization_endpoint": "http://device"
            # missing jwks_uri
        },
        request=mock_req,
    )

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("coreason_adlc_api.auth.identity._OIDC_CONFIG_CACHE", None):
        with patch("coreason_adlc_api.auth.identity._JWKS_CLIENT", None):
            with patch("coreason_adlc_api.auth.identity.get_http_client", return_value=mock_client):
                with patch("coreason_adlc_api.auth.identity.logger") as mock_logger:
                    await get_oidc_config()
                    mock_logger.error.assert_called_with("OIDC discovery missing jwks_uri")


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
async def test_parse_token_expired(mock_oidc_setup: RSAPrivateKey) -> None:
    private_key = mock_oidc_setup
    payload = {
        "oid": str(uuid.uuid4()),
        "exp": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1),
        "iss": f"{settings.OIDC_DOMAIN.rstrip('/')}/",
        "aud": settings.OIDC_AUDIENCE,
    }
    token = jwt.encode(payload, private_key, algorithm="RS256")
    header = f"Bearer {token}"

    with pytest.raises(HTTPException) as exc:
        await parse_and_validate_token(header)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_parse_token_invalid_issuer(mock_oidc_setup: RSAPrivateKey) -> None:
    private_key = mock_oidc_setup
    payload = {"oid": str(uuid.uuid4()), "iss": "wrong-issuer", "aud": settings.OIDC_AUDIENCE}
    token = jwt.encode(payload, private_key, algorithm="RS256")
    header = f"Bearer {token}"

    with pytest.raises(HTTPException) as exc:
        await parse_and_validate_token(header)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_parse_token_missing_oid_sub(mock_oidc_setup: RSAPrivateKey) -> None:
    private_key = mock_oidc_setup
    payload = {
        "email": "test@coreason.ai",
        "iss": f"{settings.OIDC_DOMAIN.rstrip('/')}/",
        "aud": settings.OIDC_AUDIENCE,
    }
    token = jwt.encode(payload, private_key, algorithm="RS256")
    header = f"Bearer {token}"

    with pytest.raises(HTTPException) as exc:
        await parse_and_validate_token(header)
    assert exc.value.status_code == 401  # Malformed token claims


@pytest.mark.asyncio
async def test_parse_token_non_uuid_oid(mock_oidc_setup: RSAPrivateKey) -> None:
    private_key = mock_oidc_setup
    payload = {
        "sub": "auth0|12345",
        "email": "test@coreason.ai",
        "name": "Test User",
        "iss": f"{settings.OIDC_DOMAIN.rstrip('/')}/",
        "aud": settings.OIDC_AUDIENCE,
    }
    token = jwt.encode(payload, private_key, algorithm="RS256")
    header = f"Bearer {token}"

    identity = await parse_and_validate_token(header)
    # Check that it converted using uuid5
    expected = uuid.UUID(int=int(str(uuid.uuid5(uuid.NAMESPACE_DNS, "auth0|12345")).replace("-", ""), 16))
    assert identity.oid == expected


@pytest.mark.asyncio
async def test_parse_token_bad_group_uuid(mock_oidc_setup: RSAPrivateKey) -> None:
    private_key = mock_oidc_setup
    payload = {
        "sub": str(uuid.uuid4()),
        "email": "test@coreason.ai",
        "name": "Test User",
        "groups": ["bad-uuid"],
        "iss": f"{settings.OIDC_DOMAIN.rstrip('/')}/",
        "aud": settings.OIDC_AUDIENCE,
    }
    token = jwt.encode(payload, private_key, algorithm="RS256")
    header = f"Bearer {token}"

    identity = await parse_and_validate_token(header)
    assert len(identity.groups) == 0


@pytest.mark.asyncio
async def test_parse_token_jwks_missing(mock_oidc_setup: RSAPrivateKey) -> None:
    # If config loads but JWKS client isn't set (e.g. cached config missing uri)
    with patch("coreason_adlc_api.auth.identity._JWKS_CLIENT", None):
        # Also need to make get_oidc_config return something without setting client, or fail
        with patch("coreason_adlc_api.auth.identity.get_oidc_config", return_value={}):
            with pytest.raises(HTTPException) as exc:
                await parse_and_validate_token("Bearer token")
            assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_parse_token_invalid_signature_error(mock_oidc_setup: RSAPrivateKey) -> None:
    private_key = mock_oidc_setup
    token = jwt.encode({"sub": str(uuid.uuid4())}, private_key, algorithm="RS256")

    with patch("jwt.decode", side_effect=jwt.InvalidTokenError("bad")):
        with pytest.raises(HTTPException) as exc:
            await parse_and_validate_token(f"Bearer {token}")
        assert exc.value.status_code == 401


# Logic Tests with Mocked DB (Updated for SQLModel)


@pytest.mark.asyncio
async def test_upsert_user(mock_db_session) -> None:
    user_uuid = uuid.uuid4()
    identity = UserIdentity(oid=user_uuid, email="upsert@coreason.ai", groups=[], full_name="Upsert Test")

    # Patch session factory
    with patch("coreason_adlc_api.auth.identity.async_session_factory") as mock_factory:
        mock_factory.return_value.__aenter__.return_value = mock_db_session

        # Configure mock to return None (new user) or existing
        # By default mock_db_session.exec.return_value.first.return_value is None

        await upsert_user(identity)

        # Atomic upsert uses exec with insert statement
        assert mock_db_session.exec.called
        assert mock_db_session.commit.called


@pytest.mark.asyncio
async def test_upsert_user_failure(mock_db_session) -> None:
    user_uuid = uuid.uuid4()
    identity = UserIdentity(oid=user_uuid, email="upsert@coreason.ai", groups=[], full_name="Upsert Test")

    mock_db_session.commit.side_effect = Exception("DB Error")

    with patch("coreason_adlc_api.auth.identity.async_session_factory") as mock_factory:
        mock_factory.return_value.__aenter__.return_value = mock_db_session
        with patch("coreason_adlc_api.auth.identity.logger") as mock_logger:
            await upsert_user(identity)
            mock_logger.error.assert_called()


@pytest.mark.asyncio
async def test_map_groups_to_projects(mock_db_session) -> None:
    group_oid = uuid.uuid4()
    user_id = uuid.uuid4()

    # We query by user_id in new implementation, not group_oid.
    identity = UserIdentity(oid=user_id, email="test@ex.com", groups=[group_oid], full_name="User")

    # Mock SQLModel select results
    # Query returns allowed_auc_ids list (as scalars if we select ProjectAccessModel.project_id)
    # result.all() returns list of rows/scalars.

    # When using `session.exec(select(col))`, it returns a Result object.
    # The code `list(result.all())` expects the `all()` method to return the list of values.
    # If the mocked `all()` returns `["project-alpha", "project-beta"]`, `list()` will wrap it if it's not already a list or consume it.

    # Fix: Ensure mock returns a list of valid project IDs directly.
    mock_db_session.exec.return_value.all.return_value = ["project-alpha", "project-beta"]

    with patch("coreason_adlc_api.auth.identity.async_session_factory") as mock_factory:
        mock_factory.return_value.__aenter__.return_value = mock_db_session

        # Pass identity object now, not list of groups
        projects = await map_groups_to_projects(identity)

        assert len(projects) == 2
        assert "project-alpha" in projects
        assert "project-beta" in projects


@pytest.mark.asyncio
async def test_map_groups_failure(mock_db_session) -> None:
    identity = UserIdentity(oid=uuid.uuid4(), email="test@ex.com", groups=[], full_name="User")

    mock_db_session.exec.side_effect = Exception("DB Error")

    with patch("coreason_adlc_api.auth.identity.async_session_factory") as mock_factory:
        mock_factory.return_value.__aenter__.return_value = mock_db_session

        with patch("coreason_adlc_api.auth.identity.logger") as mock_logger:
            projects = await map_groups_to_projects(identity)
            assert projects == []
            mock_logger.error.assert_called()


@pytest.mark.asyncio
async def test_auth_endpoints_proxy(mock_oidc_setup: RSAPrivateKey) -> None:
    # Use get_http_client patch to control internal requests

    with patch("coreason_adlc_api.routers.auth.upsert_user", new=AsyncMock()) as mock_upsert:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            # Mock Client for internal requests
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None

            # 1. Device Code
            mock_device_resp = Response(
                200,
                json={
                    "device_code": "dc-123",
                    "user_code": "ABCD-1234",
                    "verification_uri": "https://idp.com/activate",
                    "expires_in": 600,
                },
                request=Request("POST", "https://mock.idp/device"),
            )

            mock_client.post.return_value = mock_device_resp

            with patch("coreason_adlc_api.routers.auth.get_http_client", return_value=mock_client):
                resp = await ac.post("/api/v1/auth/device-code")
                assert resp.status_code == 200
                data = resp.json()
                assert data["device_code"] == "dc-123"
                # Ensure we called the right endpoint on the internal client
                assert mock_client.post.call_args[0][0] == "https://mock.idp/device"

            # 2. Token Poll - Pending
            mock_pending = Response(
                400, json={"error": "authorization_pending"}, request=Request("POST", "https://mock.idp/token")
            )
            mock_client.post.return_value = mock_pending

            with patch("coreason_adlc_api.routers.auth.get_http_client", return_value=mock_client):
                resp = await ac.post("/api/v1/auth/token", json={"device_code": "dc-123"})
                assert resp.status_code == 400
                assert resp.json()["detail"] == "authorization_pending"

            # 3. Token Poll - Success
            # We need a token that can be "decoded" unverified by the router
            private_key = mock_oidc_setup
            valid_payload = {"sub": str(uuid.uuid4()), "email": "test@coreason.ai", "name": "Test User"}
            valid_token = jwt.encode(valid_payload, private_key, algorithm="RS256")

            mock_success = Response(
                200,
                json={"access_token": valid_token, "expires_in": 3600, "token_type": "Bearer"},
                request=Request("POST", "https://mock.idp/token"),
            )

            mock_client.post.return_value = mock_success

            with patch("coreason_adlc_api.routers.auth.get_http_client", return_value=mock_client):
                resp = await ac.post("/api/v1/auth/token", json={"device_code": "dc-123"})
                assert resp.status_code == 200
                assert resp.json()["access_token"] == valid_token
                # upsert_user should be called
                mock_upsert.assert_called_once()


@pytest.mark.asyncio
async def test_auth_endpoints_upsert_failure(mock_oidc_setup: RSAPrivateKey) -> None:
    # Test fallback when token decoding fails (e.g. missing email)

    with patch("coreason_adlc_api.routers.auth.upsert_user", new=AsyncMock()) as mock_upsert:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None

            private_key = mock_oidc_setup
            # Missing email => UserIdentity validation fails => Exception caught
            invalid_payload = {"sub": str(uuid.uuid4())}
            invalid_token = jwt.encode(invalid_payload, private_key, algorithm="RS256")

            mock_success = Response(
                200,
                json={"access_token": invalid_token, "expires_in": 3600, "token_type": "Bearer"},
                request=Request("POST", "https://mock.idp/token"),
            )

            mock_client.post.return_value = mock_success

            with patch("coreason_adlc_api.routers.auth.get_http_client", return_value=mock_client):
                resp = await ac.post("/api/v1/auth/token", json={"device_code": "dc-123"})
                assert resp.status_code == 200
                # Token returned but upsert skipped
                mock_upsert.assert_not_called()


@pytest.mark.asyncio
async def test_device_code_missing_endpoint() -> None:
    with patch("coreason_adlc_api.routers.auth.get_oidc_config", return_value={}):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post("/api/v1/auth/device-code")
            assert resp.status_code == 501


@pytest.mark.asyncio
async def test_device_code_http_error() -> None:
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    # Simulate HTTP error
    mock_client.post.side_effect = httpx.HTTPStatusError("Bad Request", request=MagicMock(), response=Response(502))

    with patch(
        "coreason_adlc_api.routers.auth.get_oidc_config", return_value={"device_authorization_endpoint": "http://url"}
    ):
        with patch("coreason_adlc_api.routers.auth.get_http_client", return_value=mock_client):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.post("/api/v1/auth/device-code")
                assert resp.status_code == 502


@pytest.mark.asyncio
async def test_token_poll_missing_endpoint() -> None:
    with patch("coreason_adlc_api.routers.auth.get_oidc_config", return_value={}):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post("/api/v1/auth/token", json={"device_code": "123"})
            assert resp.status_code == 501


@pytest.mark.asyncio
async def test_token_poll_public_client() -> None:
    # Test branch where OIDC_CLIENT_SECRET is None
    with patch("coreason_adlc_api.config.settings.OIDC_CLIENT_SECRET", None):
        with patch("coreason_adlc_api.routers.auth.get_oidc_config", return_value={"token_endpoint": "http://url"}):
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.post.return_value = Response(
                200, json={"access_token": "token", "expires_in": 60}, request=Request("POST", "url")
            )

            with patch("coreason_adlc_api.routers.auth.get_http_client", return_value=mock_client):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    await ac.post("/api/v1/auth/token", json={"device_code": "123"})
                    # Verify secret removed
                    call_args = mock_client.post.call_args[1]
                    assert "client_secret" not in call_args["data"]


@pytest.mark.asyncio
async def test_token_poll_expired_token_error() -> None:
    with patch("coreason_adlc_api.routers.auth.get_oidc_config", return_value={"token_endpoint": "http://url"}):
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.post.return_value = Response(400, json={"error": "expired_token"}, request=Request("POST", "url"))

        with patch("coreason_adlc_api.routers.auth.get_http_client", return_value=mock_client):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.post("/api/v1/auth/token", json={"device_code": "123"})
                assert resp.status_code == 400
                assert resp.json()["detail"] == "expired_token"


@pytest.mark.asyncio
async def test_token_poll_non_UUID_oid_in_router(mock_oidc_setup: RSAPrivateKey) -> None:
    # Test non-UUID sub fallback inside router logic
    private_key = mock_oidc_setup
    valid_payload = {"sub": "auth0|5678", "email": "test@coreason.ai", "name": "Test User"}
    valid_token = jwt.encode(valid_payload, private_key, algorithm="RS256")

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.post.return_value = Response(200, json={"access_token": valid_token}, request=Request("POST", "url"))

    with patch("coreason_adlc_api.routers.auth.get_oidc_config", return_value={"token_endpoint": "http://url"}):
        with patch("coreason_adlc_api.routers.auth.get_http_client", return_value=mock_client):
            with patch("coreason_adlc_api.routers.auth.upsert_user", new=AsyncMock()) as mock_upsert:
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    await ac.post("/api/v1/auth/token", json={"device_code": "123"})
                    mock_upsert.assert_called_once()
                    # Verify ID converted
                    args = mock_upsert.call_args[0][0]
                    assert isinstance(args.oid, uuid.UUID)


@pytest.mark.asyncio
async def test_token_poll_http_status_error() -> None:
    with patch("coreason_adlc_api.routers.auth.get_oidc_config", return_value={"token_endpoint": "http://url"}):
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.post.side_effect = httpx.HTTPStatusError(
            "Gone", request=MagicMock(), response=Response(410, text="Gone")
        )

        with patch("coreason_adlc_api.routers.auth.get_http_client", return_value=mock_client):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.post("/api/v1/auth/token", json={"device_code": "123"})
                assert resp.status_code == 410


@pytest.mark.asyncio
async def test_token_poll_network_error() -> None:
    with patch("coreason_adlc_api.routers.auth.get_oidc_config", return_value={"token_endpoint": "http://url"}):
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.post.side_effect = httpx.ConnectError("Connection Failed", request=MagicMock())

        with patch("coreason_adlc_api.routers.auth.get_http_client", return_value=mock_client):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.post("/api/v1/auth/token", json={"device_code": "123"})
                assert resp.status_code == 502
