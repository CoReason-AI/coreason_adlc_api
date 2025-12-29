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
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AccessMode(str, Enum):
    EDIT = "EDIT"
    SAFE_VIEW = "SAFE_VIEW"


class ApprovalStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class DraftCreate(BaseModel):
    auc_id: str
    title: str
    oas_content: dict[str, Any]
    runtime_env: str | None = None


class DraftUpdate(BaseModel):
    title: str | None = None
    oas_content: dict[str, Any] | None = None
    runtime_env: str | None = None


class DraftResponse(BaseModel):
    draft_id: UUID
    user_uuid: UUID | None
    auc_id: str
    title: str
    oas_content: dict[str, Any]
    runtime_env: str | None = None
    status: ApprovalStatus = ApprovalStatus.DRAFT
    locked_by_user: UUID | None = None
    lock_expiry: datetime | None = None
    mode: AccessMode = AccessMode.EDIT
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ValidationResponse(BaseModel):
    is_valid: bool
    issues: list[str]  # e.g., ["PII Detected", "Budget Limit Reached"]


class AgentArtifact(BaseModel):
    id: UUID
    auc_id: str
    version: str
    content: dict[str, Any]
    compliance_hash: str
    author_signature: str | None = None
    created_at: datetime
