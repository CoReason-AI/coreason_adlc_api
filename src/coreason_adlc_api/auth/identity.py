# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

from typing import List
from uuid import UUID

import jwt
from coreason_adlc_api.auth.schemas import UserIdentity
from coreason_adlc_api.db import get_pool
from fastapi import Header, HTTPException, status
from loguru import logger

__all__ = [
    "UserIdentity",
    "parse_and_validate_token",
    "map_groups_to_projects",
    "upsert_user",
    "JWT_SECRET",
    "JWT_ALGORITHM",
]

# TODO: Move to settings or fetch from IdP (JWKS)
# For now, using a placeholder secret for dev
JWT_SECRET = "dev-secret-change-me"
JWT_ALGORITHM = "HS256"


async def parse_and_validate_token(authorization: str = Header(..., alias="Authorization")) -> UserIdentity:
    """
    Parses the Bearer token, validates signature, and extracts identity.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication header format. Expected 'Bearer <token>'",
        )

    token = authorization.split(" ")[1]

    try:
        # In production, this should verify against IdP's JWKS
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM], options={"verify_aud": False})

        raw_oid = payload.get("oid")
        if not raw_oid:
            raise ValueError("Token missing required claim: oid")

        oid = UUID(raw_oid)
        email = payload.get("email")
        groups = [UUID(g) for g in payload.get("groups", [])]
        name = payload.get("name")

        return UserIdentity(oid=oid, email=email, groups=groups, full_name=name)

    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has expired") from None
    except jwt.InvalidTokenError as e:
        logger.warning(f"Invalid token attempt: {e}")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from None
    except ValueError as e:
        logger.error(f"Token parsing error: {e}")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed token claims") from None


async def map_groups_to_projects(group_oids: List[UUID]) -> List[str]:
    """
    Queries identity.group_mappings to determine allowed AUC IDs for the user's groups.
    """
    pool = get_pool()

    # asyncpg requires native python types usually, but UUID is supported.
    # The query needs to handle the array check.

    query = """
        SELECT unnest(allowed_auc_ids) as auc_id
        FROM identity.group_mappings
        WHERE sso_group_oid = ANY($1::uuid[])
    """

    try:
        rows = await pool.fetch(query, group_oids)
        # Deduplicate results
        projects = list({row["auc_id"] for row in rows})
        return projects
    except Exception as e:
        logger.error(f"Failed to map groups to projects: {e}")
        # Fail safe: return empty list rather than exposing internal error
        return []


async def upsert_user(identity: UserIdentity) -> None:
    """
    Upserts the user into identity.users on login.
    """
    pool = get_pool()
    query = """
        INSERT INTO identity.users (user_uuid, email, full_name, last_login)
        VALUES ($1, $2, $3, NOW())
        ON CONFLICT (user_uuid) DO UPDATE
        SET email = EXCLUDED.email,
            full_name = EXCLUDED.full_name,
            last_login = EXCLUDED.last_login;
    """
    try:
        await pool.execute(query, identity.oid, identity.email, identity.full_name)
    except Exception as e:
        logger.error(f"Failed to upsert user {identity.oid}: {e}")
        # Non-blocking error, but should be noted
