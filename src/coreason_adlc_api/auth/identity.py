# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

import asyncio
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, cast
from uuid import UUID

import httpx
import jwt
from fastapi import Header, HTTPException, status
from loguru import logger
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import select

from coreason_adlc_api.auth.schemas import UserIdentity
from coreason_adlc_api.config import settings
from coreason_adlc_api.db import async_session_factory
from coreason_adlc_api.db_models import ProjectAccessModel
from coreason_adlc_api.db_models import UserIdentityModel as User
from coreason_adlc_api.utils import get_http_client

__all__ = [
    "UserIdentity",
    "parse_and_validate_token",
    "map_groups_to_projects",
    "upsert_user",
    "get_oidc_config",
    "get_current_user",
]


# Global cache for OIDC configuration
_OIDC_CONFIG_CACHE: Optional[Dict[str, Any]] = None
_JWKS_CLIENT: Optional[jwt.PyJWKClient] = None


async def get_oidc_config() -> Dict[str, Any]:
    """
    Fetches OIDC configuration from the discovery endpoint (cached).
    """
    global _OIDC_CONFIG_CACHE, _JWKS_CLIENT

    if _OIDC_CONFIG_CACHE:
        return _OIDC_CONFIG_CACHE

    discovery_url = f"{settings.OIDC_DOMAIN.rstrip('/')}/.well-known/openid-configuration"
    try:
        async with get_http_client() as client:
            resp = await client.get(discovery_url)
            resp.raise_for_status()
            config = resp.json()
            _OIDC_CONFIG_CACHE = config

            # Initialize JWKS Client
            jwks_uri = config.get("jwks_uri")
            if jwks_uri:
                _JWKS_CLIENT = jwt.PyJWKClient(jwks_uri)
            else:
                logger.error("OIDC discovery missing jwks_uri")

            return cast(Dict[str, Any], config)
    except httpx.HTTPError as e:
        logger.error(f"Failed to fetch OIDC configuration: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Identity Provider unavailable"
        ) from e


async def parse_and_validate_token(authorization: str = Header(..., alias="Authorization")) -> UserIdentity:
    """
    Parses the Bearer token, validates signature using RS256 and upstream JWKS, and extracts identity.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication header format. Expected 'Bearer <token>'",
        )

    token = authorization.split(" ")[1]

    # Ensure OIDC config is loaded (for JWKS client)
    if _JWKS_CLIENT is None:
        await get_oidc_config()

    if _JWKS_CLIENT is None:
        # Fallback if config failed or no JWKS URI
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Authentication service unavailable"
        )

    try:
        # Offload blocking network call to thread executor
        loop = asyncio.get_running_loop()
        signing_key = await loop.run_in_executor(None, _JWKS_CLIENT.get_signing_key_from_jwt, token)

        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.OIDC_AUDIENCE,
            issuer=f"{settings.OIDC_DOMAIN.rstrip('/')}/",
        )

        # Map claims to UserIdentity
        # Standard OIDC claims: sub (subject), email, name
        # Custom claims or group mapping logic required

        # We assume 'sub' maps to 'oid' if it's a UUID, otherwise we might need another strategy.
        # For now, we'll try to use 'sub' or a custom 'oid' claim if present.
        # If 'sub' is not a UUID (e.g. Auth0 auth0|...), we might hash it or look it up.
        # Requirement says: "oid" claim. We'll stick to expectation or fallback to sub.

        raw_oid = payload.get("oid") or payload.get("sub")
        if not raw_oid:
            raise ValueError("Token missing required claim: oid or sub")

        # Handle non-UUID subjects (e.g. Auth0 string IDs) by hashing or similar if strict UUID required
        # But `UserIdentity` expects UUID.
        # For this implementation, we assume the upstream IdP provides a UUID-compatible ID or we generate one from it?
        # To be safe and compliant with existing schema, we try to parse UUID.
        try:
            oid = UUID(raw_oid)
        except ValueError:
            # If not a valid UUID, generate a deterministic UUID from the string ID
            oid = UUID(int=int(str(uuid.uuid5(uuid.NAMESPACE_DNS, raw_oid)).replace("-", ""), 16))

        email = payload.get("email")
        name = payload.get("name")

        # Groups: standard OIDC doesn't always send groups.
        # We might expect a custom claim 'groups' or 'https://schema.org/groups'
        # Fallback to empty list if not present.
        raw_groups = payload.get("groups", [])
        groups = []
        for g in raw_groups:
            try:
                groups.append(UUID(g))
            except ValueError:
                continue  # Skip non-UUID group IDs

        return UserIdentity(oid=oid, email=email, groups=groups, full_name=name)

    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has expired") from None
    except jwt.InvalidTokenError as e:
        logger.warning(f"Invalid token attempt: {e}")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from None
    except Exception as e:
        logger.error(f"Token parsing error: {e}")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed token claims") from None


# Alias for simple dependency
get_current_user = parse_and_validate_token


async def map_groups_to_projects(identity: UserIdentity, session: Optional[Any] = None) -> List[str]:
    """
    Determines allowed project IDs for the user.
    Uses ProjectAccessModel to look up grants.
    Accepts an optional session for testing or dependency injection.
    """
    # For now, if no groups/roles logic is complex, just return projects where user is assigned.
    # The original implementation queried 'GroupMapping', but we switched to ProjectAccessModel for simplicity/standard RBAC.

    # If session is None, use a fresh one (e.g. called from utility)
    # But usually called with session.

    local_session = False
    if session is None:
        session = async_session_factory()
        local_session = True

    try:
        # Logic: Select project_id from ProjectAccessModel where user_id == identity.id
        # Mypy correction: identity.id -> identity.oid
        statement = select(ProjectAccessModel.project_id).where(ProjectAccessModel.user_id == identity.oid)

        # If using AsyncSession from SQLModel, we need await exec
        # But session might be a factory if local_session=True? No, we instantiated it.
        # Wait, async_session_factory() returns a session context manager usually?
        # async_session_factory is async_sessionmaker. Calling it returns a session.

        if local_session:
            async with session as s:  # type: ignore
                result = await s.exec(statement)
                return list(result.all())
        else:
            result = await session.exec(statement)
            return list(result.all())

    except Exception as e:
        logger.error(f"Failed to map projects: {e}")
        return []


async def upsert_user(identity: UserIdentity) -> None:
    """
    Upserts the user into identity.users on login.
    """
    try:
        email = identity.email
        if not email:
            logger.warning(f"Skipping upsert for user {identity.oid} without email")
            return

        # Atomic upsert
        async with async_session_factory() as session:
            stmt = (
                insert(User)
                .values(
                    id=identity.oid,  # UserIdentityModel uses 'id'
                    sub=str(identity.oid),  # Assuming sub matches oid for now, or we should store raw sub
                    email=email,
                    name=identity.full_name or "Unknown",
                    roles=[],  # Default empty
                    updated_at=datetime.utcnow(),
                )
                .on_conflict_do_update(
                    index_elements=["sub"],  # sub is unique constraint
                    set_=dict(email=email, name=identity.full_name or "Unknown", updated_at=datetime.utcnow()),
                )
            )
            await session.exec(stmt)  # type: ignore[call-overload]
            await session.commit()

    except Exception as e:
        logger.error(f"Failed to upsert user {identity.oid}: {e}")
