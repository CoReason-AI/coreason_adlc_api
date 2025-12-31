# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

import uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

# --- Auth ---


class UserIdentityModel(SQLModel, table=True):
    __tablename__ = "users"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    sub: str = Field(index=True, unique=True)
    email: str
    name: str
    roles: List[str] = Field(sa_column=Column(JSONB))  # type: ignore
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ProjectAccessModel(SQLModel, table=True):
    __tablename__ = "project_access"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    project_id: str = Field(index=True)
    role: str  # e.g. "viewer", "editor"
    granted_at: datetime = Field(default_factory=datetime.utcnow)


# --- Vault ---


class SecretModel(SQLModel, table=True):
    __tablename__ = "secrets"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    project_id: str = Field(index=True)
    key_name: str = Field(index=True)
    encrypted_value: bytes
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # Composite unique constraint handling in SQLModel is usually done via TableArgs
    # __table_args__ = (UniqueConstraint("project_id", "key_name"),)


# Alias for legacy compatibility/proxy usage if needed
# But wait, proxy.py was importing 'Secret', maybe it meant SecretModel or the old Pydantic model?
# The error said "cannot import name 'Secret'".
# Let's verify what proxy.py expects. Assuming it wants the DB model.
Secret = SecretModel

# --- Workbench ---


class DraftModel(SQLModel, table=True):
    __tablename__ = "drafts"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    project_id: str = Field(index=True)
    content: dict = Field(default={}, sa_column=Column(JSONB))  # type: ignore
    status: str = Field(default="DRAFT")  # Draft, Pending, Approved, Rejected
    version: int = Field(default=1)
    created_by: uuid.UUID = Field(foreign_key="users.id")
    locked_by: Optional[uuid.UUID] = Field(default=None, foreign_key="users.id")
    locked_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ArtifactModel(SQLModel, table=True):
    __tablename__ = "artifacts"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    project_id: str = Field(index=True)
    draft_id: uuid.UUID = Field(foreign_key="drafts.id")
    version: str  # e.g. "1.0.0"
    content_hash: str
    signature: str
    published_by: uuid.UUID = Field(foreign_key="users.id")
    published_at: datetime = Field(default_factory=datetime.utcnow)


# --- Telemetry ---


class TelemetryLog(SQLModel, table=True):
    __tablename__ = "telemetry_logs"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    timestamp: datetime = Field(default_factory=datetime.utcnow, index=True)
    user_uuid: uuid.UUID = Field(
        index=True
    )  # Not strictly FK to decouple log storage from user deletion? Or loose coupling.
    auc_id: str = Field(index=True)
    model_name: str
    request_payload: str  # Or JSON? "request_payload" in original schema was text
    response_payload: str
    cost_usd: float
    latency_ms: float
