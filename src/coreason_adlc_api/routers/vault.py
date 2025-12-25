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

from fastapi import APIRouter, Depends, status

from coreason_adlc_api.auth.identity import UserIdentity, parse_and_validate_token
from coreason_adlc_api.vault.schemas import CreateSecretRequest, SecretResponse
from coreason_adlc_api.vault.service import store_secret

router = APIRouter(prefix="/vault", tags=["Vault"])


@router.post("/secrets", response_model=SecretResponse, status_code=status.HTTP_201_CREATED)
async def create_or_update_secret(
    request: CreateSecretRequest, identity: UserIdentity = Depends(parse_and_validate_token)
) -> SecretResponse:
    """
    Encrypts and stores a new API key.
    Requires Authentication.
    """
    # Authorization check: Does user have access to this auc_id?
    # TODO: In real implementation, check identity.groups against auc_id via map_groups_to_projects
    # For now, we assume if they can login, they can add secrets (Atomic Unit 2 scope)

    secret_id = await store_secret(
        auc_id=request.auc_id,
        service_name=request.service_name,
        raw_api_key=request.raw_api_key,
        user_uuid=identity.oid,
    )

    return SecretResponse(
        secret_id=secret_id,
        auc_id=request.auc_id,
        service_name=request.service_name,
        created_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
    )
