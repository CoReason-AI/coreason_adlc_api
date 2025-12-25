# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr


class User(BaseModel):
    user_uuid: UUID
    email: EmailStr
    full_name: str | None = None
    created_at: datetime
    last_login: datetime | None = None


class GroupMapping(BaseModel):
    mapping_id: UUID
    sso_group_oid: UUID
    role_name: str
    allowed_auc_ids: list[str]
    description: str | None = None


class DeviceCodeResponse(BaseModel):
    device_code: str
    user_code: str
    verification_uri: str
    expires_in: int
    interval: int


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int


class UserIdentity(BaseModel):
    oid: UUID
    email: EmailStr
    groups: list[UUID]
    full_name: str | None = None
