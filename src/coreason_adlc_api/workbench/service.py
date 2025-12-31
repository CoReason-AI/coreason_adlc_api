# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

import json
from datetime import datetime
from typing import Any, List, Optional
from uuid import UUID

from fastapi import HTTPException
from loguru import logger
from sqlmodel import select, col

from coreason_adlc_api.db import async_session_factory
from coreason_adlc_api.db_models import AgentDraft
from coreason_adlc_api.workbench.locking import acquire_draft_lock, verify_lock_for_update
from coreason_adlc_api.workbench.schemas import (
    AgentArtifact,
    ApprovalStatus,
    DraftCreate,
    DraftResponse,
    DraftUpdate,
)


async def create_draft(draft: DraftCreate, user_uuid: UUID) -> DraftResponse:
    try:
        async with async_session_factory() as session:
            db_draft = AgentDraft(
                user_uuid=user_uuid,
                auc_id=draft.auc_id,
                title=draft.title,
                oas_content=draft.oas_content,
                runtime_env=draft.runtime_env,
            )
            session.add(db_draft)
            await session.commit()
            await session.refresh(db_draft)
            return DraftResponse.model_validate(db_draft)
    except Exception as e:
        logger.error(f"Failed to create draft: {e}")
        raise RuntimeError("Failed to create draft") from e


async def get_drafts(auc_id: str, include_deleted: bool = False) -> List[DraftResponse]:
    async with async_session_factory() as session:
        query = select(AgentDraft).where(AgentDraft.auc_id == auc_id)
        if not include_deleted:
            query = query.where(AgentDraft.is_deleted == False)  # noqa: E712

        query = query.order_by(col(AgentDraft.updated_at).desc())

        result = await session.exec(query)
        drafts = result.all()
        return [DraftResponse.model_validate(d) for d in drafts]


async def get_draft_by_id(draft_id: UUID, user_uuid: UUID, roles: List[str]) -> Optional[DraftResponse]:
    # Try to acquire lock
    try:
        mode = await acquire_draft_lock(draft_id, user_uuid, roles)
    except HTTPException as e:
        if e.status_code == 404:
            return None
        raise e

    async with async_session_factory() as session:
        statement = select(AgentDraft).where(AgentDraft.draft_id == draft_id)
        result = await session.exec(statement)
        draft = result.first()

    if not draft:
        return None

    resp = DraftResponse.model_validate(draft)
    resp.mode = mode
    return resp


async def _check_status_for_update(draft_id: UUID) -> None:
    async with async_session_factory() as session:
        statement = select(AgentDraft.status).where(AgentDraft.draft_id == draft_id)
        result = await session.exec(statement)
        status = result.first()

    if not status:
        raise HTTPException(status_code=404, detail="Draft not found")

    if status not in (ApprovalStatus.DRAFT, ApprovalStatus.REJECTED):
        raise HTTPException(
            status_code=409, detail=f"Cannot edit draft in '{status}' status. Must be DRAFT or REJECTED."
        )


async def update_draft(draft_id: UUID, update: DraftUpdate, user_uuid: UUID) -> DraftResponse:
    # Verify Lock
    await verify_lock_for_update(draft_id, user_uuid)

    # Verify Status (Cannot edit if PENDING or APPROVED)
    await _check_status_for_update(draft_id)

    async with async_session_factory() as session:
        statement = select(AgentDraft).where(AgentDraft.draft_id == draft_id)
        result = await session.exec(statement)
        draft = result.first()

        if not draft:
            raise HTTPException(status_code=404, detail="Draft not found")

        updated = False
        if update.title is not None:
            draft.title = update.title
            updated = True
        if update.oas_content is not None:
            draft.oas_content = update.oas_content
            updated = True
        if update.runtime_env is not None:
            draft.runtime_env = update.runtime_env
            updated = True

        if updated:
            draft.updated_at = datetime.utcnow()
            session.add(draft)
            await session.commit()
            await session.refresh(draft)

        return DraftResponse.model_validate(draft)


async def transition_draft_status(draft_id: UUID, user_uuid: UUID, new_status: ApprovalStatus) -> DraftResponse:
    """
    Handles state transitions:
    - DRAFT -> PENDING (Submit)
    - PENDING -> APPROVED (Approve)
    - PENDING -> REJECTED (Reject)
    - REJECTED -> PENDING (Re-submit)
    """
    async with async_session_factory() as session:
        statement = select(AgentDraft).where(AgentDraft.draft_id == draft_id)
        result = await session.exec(statement)
        draft = result.first()

        if not draft:
            raise HTTPException(status_code=404, detail="Draft not found")

        current_status = ApprovalStatus(draft.status)

        # Validate Transitions
        allowed = False
        if current_status == ApprovalStatus.DRAFT and new_status == ApprovalStatus.PENDING:
            allowed = True
        elif current_status == ApprovalStatus.REJECTED and new_status == ApprovalStatus.PENDING:
            allowed = True
        elif current_status == ApprovalStatus.PENDING and new_status in (ApprovalStatus.APPROVED, ApprovalStatus.REJECTED):
            # Check permissions for approval/rejection (Manager only)
            # This function assumes the caller checks roles, but we can double check here if needed.
            # For now, we rely on the router to check for MANAGER role.
            allowed = True
        else:
            allowed = False

        if not allowed:
            raise HTTPException(status_code=409, detail=f"Invalid transition from {current_status.value} to {new_status.value}")

        # Perform Update
        draft.status = new_status.value
        draft.updated_at = datetime.utcnow()
        session.add(draft)
        await session.commit()
        await session.refresh(draft)

        return DraftResponse.model_validate(draft)


async def assemble_artifact(draft_id: UUID, user_oid: UUID) -> AgentArtifact:
    """
    Assembles the canonical AgentArtifact from a draft.
    Requires draft to be APPROVED.
    """
    # Use get_draft_by_id as standard accessor.
    # Note: get_draft_by_id attempts to acquire a lock.
    # If the draft is APPROVED, it's typically read-only or final, so lock might be irrelevant or we accept shared lock.
    # Passing empty roles list as we are not checking editing rights here, just assembly rights
    # (checked by caller via approval status?)
    # Actually, we rely on the draft status check.

    draft = await get_draft_by_id(draft_id, user_oid, [])
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    if draft.status != ApprovalStatus.APPROVED:
        raise ValueError("Draft must be APPROVED to assemble")

    artifact = AgentArtifact(
        id=draft.draft_id,
        auc_id=draft.auc_id,
        version="1.0.0",  # Placeholder versioning strategy
        content=draft.oas_content,
        compliance_hash="sha256:mock_compliance_verification_hash",
        # Use draft.updated_at (or created_at) to ensure deterministic output for signing
        created_at=draft.updated_at,
    )
    return artifact


async def publish_artifact(draft_id: UUID, signature: str, user_oid: UUID) -> str:
    """
    Publishes the signed artifact.
    """
    # 1. Assemble (checks approval)
    artifact = await assemble_artifact(draft_id, user_oid)

    # 2. Inject Signature
    artifact.author_signature = signature

    # 3. Mock Git Push
    logger.info(f"Pushing artifact {artifact.id} to GitLab for user {user_oid}...")
    mock_url = f"https://gitlab.example.com/agents/{draft_id}/v1"

    return mock_url
