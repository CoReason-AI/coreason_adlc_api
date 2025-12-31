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
from typing import List, Optional, Any, Dict
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel, Relationship
from sqlalchemy import Column, String, JSON, ARRAY, text
from sqlalchemy.dialects.postgresql import TSVECTOR


# -----------------------------------------------------------------------------
# Identity Schema
# -----------------------------------------------------------------------------

class User(SQLModel, table=True):
    __tablename__ = "users"
    __table_args__ = {"schema": "identity"}

    user_uuid: UUID = Field(default=None, primary_key=True)
    email: str = Field(unique=True, max_length=255)
    full_name: Optional[str] = Field(default=None, max_length=255)
    created_at: Optional[datetime] = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"server_default": text("now()")}
    )
    last_login: Optional[datetime] = Field(default=None)


class GroupMapping(SQLModel, table=True):
    __tablename__ = "group_mappings"
    __table_args__ = {"schema": "identity"}

    mapping_id: UUID = Field(default_factory=uuid4, primary_key=True)
    sso_group_oid: UUID = Field(unique=True)
    role_name: str = Field(max_length=50)
    allowed_auc_ids: List[str] = Field(sa_column=Column(ARRAY(String)))
    description: Optional[str] = Field(default=None, max_length=255)


# -----------------------------------------------------------------------------
# Vault Schema
# -----------------------------------------------------------------------------

class Secret(SQLModel, table=True):
    __tablename__ = "secrets"
    __table_args__ = (
        {"schema": "vault"},
    )

    secret_id: UUID = Field(default_factory=uuid4, primary_key=True)
    auc_id: str = Field(max_length=50)
    service_name: str = Field(max_length=50)
    encrypted_value: str = Field()  # TEXT
    encryption_key_id: Optional[str] = Field(default=None, max_length=50)
    created_by: Optional[UUID] = Field(default=None, foreign_key="identity.users.user_uuid")
    created_at: Optional[datetime] = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"server_default": text("now()")}
    )


# -----------------------------------------------------------------------------
# Workbench Schema
# -----------------------------------------------------------------------------

class AgentDraft(SQLModel, table=True):
    __tablename__ = "agent_drafts"
    __table_args__ = {"schema": "workbench"}

    draft_id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_uuid: Optional[UUID] = Field(default=None, foreign_key="identity.users.user_uuid")
    auc_id: str = Field(max_length=50)
    title: str = Field(max_length=255)
    oas_content: Dict[str, Any] = Field(default={}, sa_column=Column(JSON))
    runtime_env: Optional[str] = Field(default=None, max_length=64)
    status: str = Field(default="DRAFT", max_length=20)  # Check constraint managed in DDL
    agent_tools_index: Optional[Any] = Field(default=None, sa_column=Column(TSVECTOR))
    locked_by_user: Optional[UUID] = Field(default=None, foreign_key="identity.users.user_uuid")
    lock_expiry: Optional[datetime] = Field(default=None)
    is_deleted: bool = Field(default=False)
    created_at: Optional[datetime] = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"server_default": text("now()")}
    )
    updated_at: Optional[datetime] = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"server_default": text("now()")}
    )


# -----------------------------------------------------------------------------
# Telemetry Schema
# -----------------------------------------------------------------------------

class TelemetryLog(SQLModel, table=True):
    __tablename__ = "telemetry_logs"
    __table_args__ = {"schema": "telemetry"}

    # Note: Partitioned tables in PG usually don't enforce global PK easily.
    # We define it here for SQLModel but the actual table is partitioned.
    log_id: UUID = Field(default_factory=uuid4, primary_key=True)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    user_uuid: Optional[UUID] = Field(default=None)
    auc_id: Optional[str] = Field(default=None, max_length=50)
    model_name: Optional[str] = Field(default=None, max_length=100)
    request_payload: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    response_payload: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    cost_usd: Optional[float] = Field(default=None)
    latency_ms: Optional[int] = Field(default=None)
