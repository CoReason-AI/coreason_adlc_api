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

from coreason_adlc_api.auth.identity import UserIdentity, parse_and_validate_token
from fastapi import APIRouter, Depends

router = APIRouter(prefix="/models", tags=["Models"])


@router.get("/{model_id}/schema", response_model=Dict[str, Any])
async def get_model_schema(
    model_id: str,
    identity: UserIdentity = Depends(parse_and_validate_token),
) -> Dict[str, Any]:
    """
    Returns the JSON Schema for the given model's configuration parameters.
    Used for Server-Driven UI rendering.
    """
    model_id_lower = model_id.lower()

    if "deepseek" in model_id_lower or "reasoning" in model_id_lower:
        # Schema for Reasoning models
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "title": f"Configuration for {model_id}",
            "properties": {
                "reasoning_effort": {
                    "type": "string",
                    "title": "Reasoning Effort",
                    "description": "The amount of reasoning effort to apply.",
                    "enum": ["low", "medium", "high"],
                    "default": "medium",
                }
            },
            "required": ["reasoning_effort"],
            "additionalProperties": False,
        }
    else:
        # Default Schema (Temperature, Top P)
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "title": f"Configuration for {model_id}",
            "properties": {
                "temperature": {
                    "type": "number",
                    "title": "Temperature",
                    "description": "Sampling temperature. Higher values mean more randomness.",
                    "minimum": 0.0,
                    "maximum": 2.0,
                    "default": 0.7,
                },
                "top_p": {
                    "type": "number",
                    "title": "Top P",
                    "description": "Nucleus sampling probability.",
                    "minimum": 0.0,
                    "maximum": 1.0,
                    "default": 1.0,
                },
            },
            "required": ["temperature", "top_p"],
            "additionalProperties": False,
        }

    return schema
