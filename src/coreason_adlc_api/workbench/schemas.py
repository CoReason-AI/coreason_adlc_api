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
from typing import Any, Dict, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


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
    oas_content: Dict[str, Any]
    runtime_env: Optional[str] = None


class DraftUpdate(BaseModel):
    title: Optional[str] = None
    oas_content: Optional[Dict[str, Any]] = None
    runtime_env: Optional[str] = None


class DraftResponse(BaseModel):
    draft_id: UUID
    user_uuid: Optional[UUID]
    auc_id: str
    title: str
    oas_content: Dict[str, Any]
    runtime_env: Optional[str] = None
    status: ApprovalStatus = ApprovalStatus.DRAFT
    locked_by_user: Optional[UUID] = Field(default=None)
    lock_expiry: Optional[datetime] = None  # Not directly in DB, calculated
    mode: AccessMode = AccessMode.EDIT  # Calculated
    created_at: datetime
    updated_at: datetime
    version: int = 1

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


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

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class PublishRequest(BaseModel):
    content_hash: str  # Verify integrity
    signature: str


class ArtifactResponse(BaseModel):
    id: UUID
    project_id: str
    version: str
    content_hash: str
    signature: str
    created_at: datetime
    created_by: UUID


class ReviewRequest(BaseModel):
    decision: str  # APPROVE / REJECT
    comment: Optional[str] = None
