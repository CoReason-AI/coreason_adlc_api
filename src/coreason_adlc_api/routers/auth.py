# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

import jwt
import httpx
import uuid
from coreason_adlc_api.auth.identity import get_oidc_config, upsert_user, UserIdentity
from coreason_adlc_api.auth.schemas import DeviceCodeResponse, TokenResponse
from coreason_adlc_api.config import settings
from coreason_adlc_api.utils import get_http_client
from fastapi import APIRouter, Body, HTTPException, status

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/device-code", response_model=DeviceCodeResponse)
async def initiate_device_code_flow() -> DeviceCodeResponse:
    """
    Initiates SSO Device Flow by proxying to the upstream IdP.
    """
    oidc_config = await get_oidc_config()
    endpoint = oidc_config.get("device_authorization_endpoint")
    if not endpoint:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="IdP does not support device flow"
        )

    payload = {
        "client_id": settings.OIDC_CLIENT_ID,
        "scope": "openid profile email offline_access",
        "audience": settings.OIDC_AUDIENCE,
    }

    try:
        async with get_http_client() as client:
            resp = await client.post(endpoint, data=payload)
            resp.raise_for_status()
            data = resp.json()

            return DeviceCodeResponse(
                device_code=data["device_code"],
                user_code=data["user_code"],
                verification_uri=data["verification_uri"],
                verification_uri_complete=data.get("verification_uri_complete"),
                expires_in=data["expires_in"],
                interval=data.get("interval", 5),
            )
    except httpx.HTTPError as e:
        # Pass through error details if available, or generic error
        detail = "Failed to initiate device flow"
        if hasattr(e, 'response') and e.response:
             detail = e.response.text
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail) from e


@router.post("/token", response_model=TokenResponse)
async def poll_for_token(device_code: str = Body(..., embed=True)) -> TokenResponse:
    """
    Polls for Session Token (JWT) by proxying to the upstream IdP.
    """
    oidc_config = await get_oidc_config()
    endpoint = oidc_config.get("token_endpoint")
    if not endpoint:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="IdP token endpoint missing")

    payload = {
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        "device_code": device_code,
        "client_id": settings.OIDC_CLIENT_ID,
        "client_secret": settings.OIDC_CLIENT_SECRET,  # Confidential client if secret set
    }

    # If no client secret (public client), remove it.
    # Typically backend is confidential.
    if not settings.OIDC_CLIENT_SECRET:
        payload.pop("client_secret")

    try:
        async with get_http_client() as client:
            resp = await client.post(endpoint, data=payload)

            # Handle specific polling errors
            if resp.status_code == 400:
                error_data = resp.json()
                error_code = error_data.get("error")
                if error_code in ["authorization_pending", "slow_down"]:
                     raise HTTPException(
                         status_code=status.HTTP_400_BAD_REQUEST,
                         detail=error_code
                     )
                elif error_code == "expired_token":
                     raise HTTPException(
                         status_code=status.HTTP_400_BAD_REQUEST,
                         detail="expired_token"
                     )

            resp.raise_for_status()
            data = resp.json()

            access_token = data["access_token"]
            expires_in = data.get("expires_in", 3600)

            # Extract user info for upsert
            # We decode unverified here just to extract claims for the DB sync.
            # Real validation happens on subsequent API calls using the token.
            try:
                decoded = jwt.decode(access_token, options={"verify_signature": False})

                raw_oid = decoded.get("oid") or decoded.get("sub")
                if raw_oid:
                    try:
                        oid = uuid.UUID(raw_oid)
                    except ValueError:
                        oid = uuid.UUID(int=int(str(uuid.uuid5(uuid.NAMESPACE_DNS, raw_oid)).replace('-', ''), 16))

                    email = decoded.get("email")
                    name = decoded.get("name")

                    identity = UserIdentity(
                        oid=oid,
                        email=email,
                        full_name=name,
                        groups=[] # Groups handled via graph or claims later
                    )
                    await upsert_user(identity)
            except Exception:
                # Logging handled in upsert_user or ignored if token non-decodable
                pass

            return TokenResponse(access_token=access_token, expires_in=expires_in)

    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text) from e
    except httpx.HTTPError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Upstream IdP unavailable") from e
