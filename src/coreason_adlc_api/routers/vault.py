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
from sqlmodel.ext.asyncio.session import AsyncSession

from coreason_adlc_api.auth.identity import (
    UserIdentity,
    parse_and_validate_token,
)

# Assuming get_current_user wraps parse_and_validate
from coreason_adlc_api.db import get_db
from coreason_adlc_api.vault.schemas import CreateSecretRequest, SecretResponse
from coreason_adlc_api.vault.service import VaultService

router = APIRouter(prefix="/vault", tags=["Vault"])


async def get_vault_service(
    session: AsyncSession = Depends(get_db), user: UserIdentity = Depends(parse_and_validate_token)
) -> VaultService:
    return VaultService(session, user)


@router.post("/secrets", response_model=SecretResponse, status_code=status.HTTP_201_CREATED)
async def create_or_update_secret(
    request: CreateSecretRequest, service: VaultService = Depends(get_vault_service)
) -> SecretResponse:
    """
    Encrypts and stores a new API key.
    Requires Authentication.
    """
    # Authorization is handled in service

    # We map request.service_name to 'key_name' in internal model, or similar?
    # Schema says service_name, DB says key_name.

    secret_id = await service.store_secret(
        project_id=request.auc_id, key_name=request.service_name, secret_value=request.raw_api_key
    )

    return SecretResponse(
        secret_id=secret_id,
        auc_id=request.auc_id,
        service_name=request.service_name,
        created_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
    )
