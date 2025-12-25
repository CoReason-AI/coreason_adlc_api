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

import jwt
from fastapi import APIRouter, Body

from coreason_adlc_api.auth.identity import JWT_ALGORITHM, JWT_SECRET, upsert_user
from coreason_adlc_api.auth.schemas import DeviceCodeResponse, TokenResponse

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/device-code", response_model=DeviceCodeResponse)
async def initiate_device_code_flow() -> DeviceCodeResponse:
    """
    Initiates SSO Device Flow.
    MOCKED for this iteration.
    """
    # In a real implementation, this would call the IdP (e.g., Azure AD, Auth0)
    return DeviceCodeResponse(
        device_code=str(uuid.uuid4()),
        user_code=str(uuid.uuid4())[:8].upper(),
        verification_uri="https://sso.example.com/device",
        expires_in=600,
        interval=5,
    )


@router.post("/token", response_model=TokenResponse)
async def poll_for_token(device_code: str = Body(..., embed=True)) -> TokenResponse:
    """
    Polls for Session Token (JWT).
    MOCKED: Returns a valid JWT for testing purposes immediately.
    """
    # MOCK LOGIC: Generate a valid self-signed JWT using the local dev secret
    # This allows other components to be tested against a "valid" token.

    mock_user_uuid = "00000000-0000-0000-0000-000000000001"
    mock_group_uuid = "11111111-1111-1111-1111-111111111111"

    payload = {
        "sub": mock_user_uuid,
        "oid": mock_user_uuid,
        "name": "Test User",
        "email": "test@coreason.ai",
        "groups": [mock_group_uuid],
        "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1),
    }

    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

    # Side-effect: Ensure user exists in DB so FK constraints don't fail later
    # We call upsert_user logic internally here to simulate a successful login hook
    from coreason_adlc_api.auth.identity import UserIdentity

    identity = UserIdentity(
        oid=uuid.UUID(mock_user_uuid),
        email="test@coreason.ai",
        groups=[uuid.UUID(mock_group_uuid)],
        full_name="Test User",
    )
    await upsert_user(identity)

    return TokenResponse(access_token=token, expires_in=3600)
