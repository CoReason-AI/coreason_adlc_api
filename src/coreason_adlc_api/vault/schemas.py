# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

from uuid import UUID

from pydantic import BaseModel, Field


class CreateSecretRequest(BaseModel):
    auc_id: str = Field(..., description="Project ID")
    service_name: str = Field(..., description="Target Service (e.g., openai, deepseek)")
    raw_api_key: str = Field(..., description="The raw API key to encrypt")


class SecretResponse(BaseModel):
    secret_id: UUID
    auc_id: str
    service_name: str
    created_at: str
