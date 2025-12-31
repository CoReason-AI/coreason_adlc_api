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
from typing import Any, Optional, Dict
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
    project_id: str # Renamed from auc_id to match service usage
    content: Dict[str, Any] # Renamed from oas_content/title split for simplicity in new service


class DraftUpdate(BaseModel):
    content: Optional[Dict[str, Any]] = None


class DraftResponse(BaseModel):
    id: UUID = Field(alias="draft_id") # Map id -> draft_id if needed, or stick to id
    project_id: str
    content: Dict[str, Any]
    status: ApprovalStatus
    created_by: UUID
    locked_by: Optional[UUID] = None
    locked_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    version: int

    model_config = ConfigDict(from_attributes=True)


class ValidationResponse(BaseModel):
    is_valid: bool
    issues: list[str]  # e.g., ["PII Detected", "Budget Limit Reached"]


class AgentArtifact(BaseModel):
    id: UUID
    project_id: str
    version: str
    content: dict[str, Any]
    content_hash: str # Renamed from compliance_hash?
    author_signature: str | None = None
    created_at: datetime


class PublishRequest(BaseModel):
    content_hash: str # Verify integrity
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
    decision: str # APPROVE / REJECT
    comment: Optional[str] = None
