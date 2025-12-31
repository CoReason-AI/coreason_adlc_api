# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

from typing import Any, Dict

from fastapi import APIRouter, Depends

from coreason_adlc_api.auth.identity import UserIdentity, parse_and_validate_token
from coreason_adlc_api.services.models import ModelService

router = APIRouter(prefix="/models", tags=["Models"])


@router.get("/{model_id}/schema", response_model=Dict[str, Any])
async def get_model_schema(
    model_id: str,
    identity: UserIdentity = Depends(parse_and_validate_token),
    model_service: ModelService = Depends(),
) -> Dict[str, Any]:
    """
    Returns the JSON Schema for the given model's configuration parameters.
    Used for Server-Driven UI rendering.
    """
    return await model_service.get_model_schema(model_id)
