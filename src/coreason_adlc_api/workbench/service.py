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
from typing import Any, List, Optional
from uuid import UUID

from fastapi import HTTPException
from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from coreason_adlc_api.workbench.locking import acquire_draft_lock, verify_lock_for_update
from coreason_adlc_api.workbench.schemas import (
    AgentArtifact,
    ApprovalStatus,
    DraftCreate,
    DraftResponse,
    DraftUpdate,
)


async def create_draft(session: AsyncSession, draft: DraftCreate, user_uuid: UUID) -> DraftResponse:
    stmt = text("""
        INSERT INTO workbench.agent_drafts
        (user_uuid, auc_id, title, oas_content, runtime_env)
        VALUES (:user_uuid, :auc_id, :title, :oas_content, :runtime_env)
        RETURNING *;
    """)
    result = await session.execute(
        stmt,
        {
            "user_uuid": user_uuid,
            "auc_id": draft.auc_id,
            "title": draft.title,
            "oas_content": json.dumps(draft.oas_content),
            "runtime_env": draft.runtime_env,
        },
    )
    await session.commit()

    row = result.mappings().fetchone()
    if not row:
        raise RuntimeError("Failed to create draft")

    return DraftResponse.model_validate(dict(row))


async def get_drafts(session: AsyncSession, auc_id: str, include_deleted: bool = False) -> List[DraftResponse]:
    stmt = text("""
        SELECT * FROM workbench.agent_drafts
        WHERE auc_id = :auc_id AND (:include_deleted = TRUE OR is_deleted = FALSE)
        ORDER BY updated_at DESC;
    """)
    result = await session.execute(stmt, {"auc_id": auc_id, "include_deleted": include_deleted})
    rows = result.mappings().all()
    return [DraftResponse.model_validate(dict(r)) for r in rows]


async def get_draft_by_id(
    session: AsyncSession, draft_id: UUID, user_uuid: UUID, roles: List[str]
) -> Optional[DraftResponse]:
    # Try to acquire lock
    try:
        mode = await acquire_draft_lock(session, draft_id, user_uuid, roles)
    except HTTPException as e:
        if e.status_code == 404:
            return None
        raise e

    stmt = text("SELECT * FROM workbench.agent_drafts WHERE draft_id = :draft_id")
    result = await session.execute(stmt, {"draft_id": draft_id})
    row = result.mappings().fetchone()

    if not row:
        return None

    resp = DraftResponse.model_validate(dict(row))
    resp.mode = mode
    return resp


async def _check_status_for_update(session: AsyncSession, draft_id: UUID) -> None:
    stmt = text("SELECT status FROM workbench.agent_drafts WHERE draft_id = :draft_id")
    result = await session.execute(stmt, {"draft_id": draft_id})
    status_row = result.fetchone()

    if not status_row:
        raise HTTPException(status_code=404, detail="Draft not found")

    status = status_row[0]
    if status not in (ApprovalStatus.DRAFT, ApprovalStatus.REJECTED):
        raise HTTPException(
            status_code=409, detail=f"Cannot edit draft in '{status}' status. Must be DRAFT or REJECTED."
        )


async def update_draft(session: AsyncSession, draft_id: UUID, update: DraftUpdate, user_uuid: UUID) -> DraftResponse:
    # Verify Lock
    await verify_lock_for_update(session, draft_id, user_uuid)

    # Verify Status (Cannot edit if PENDING or APPROVED)
    await _check_status_for_update(session, draft_id)

    # Dynamic update query construction
    fields: List[str] = []
    params: dict[str, Any] = {"draft_id": draft_id}

    if update.title is not None:
        fields.append("title = :title")
        params["title"] = update.title

    if update.oas_content is not None:
        fields.append("oas_content = :oas_content")
        params["oas_content"] = json.dumps(update.oas_content)

    if update.runtime_env is not None:
        fields.append("runtime_env = :runtime_env")
        params["runtime_env"] = update.runtime_env

    if not fields:
        # No updates
        current = await get_draft_by_id(session, draft_id, user_uuid, [])
        if not current:
            raise HTTPException(status_code=404, detail="Draft not found")
        return current

    fields.append("updated_at = NOW()")

    query = f"""
        UPDATE workbench.agent_drafts
        SET {", ".join(fields)}
        WHERE draft_id = :draft_id
        RETURNING *;
    """

    stmt = text(query)
    result = await session.execute(stmt, params)
    await session.commit()

    row = result.mappings().fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Draft not found")

    return DraftResponse.model_validate(dict(row))


async def transition_draft_status(
    session: AsyncSession, draft_id: UUID, user_uuid: UUID, new_status: ApprovalStatus
) -> DraftResponse:
    """
    Handles state transitions:
    - DRAFT -> PENDING (Submit)
    - PENDING -> APPROVED (Approve)
    - PENDING -> REJECTED (Reject)
    - REJECTED -> PENDING (Re-submit)
    """
    # Get current status
    stmt = text("SELECT status FROM workbench.agent_drafts WHERE draft_id = :draft_id")
    result = await session.execute(stmt, {"draft_id": draft_id})
    row = result.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Draft not found")

    current_status = row[0]

    # Validate Transitions
    allowed = False
    if current_status == ApprovalStatus.DRAFT and new_status == ApprovalStatus.PENDING:
        allowed = True
    elif current_status == ApprovalStatus.REJECTED and new_status == ApprovalStatus.PENDING:
        allowed = True
    elif current_status == ApprovalStatus.PENDING and new_status == ApprovalStatus.APPROVED:
        allowed = True
    elif current_status == ApprovalStatus.PENDING and new_status == ApprovalStatus.REJECTED:
        allowed = True
    else:
        allowed = False

    if not allowed:
        raise HTTPException(status_code=409, detail=f"Invalid transition from {current_status} to {new_status}")

    # Perform Update
    update_stmt = text("""
        UPDATE workbench.agent_drafts
        SET status = :status, updated_at = NOW()
        WHERE draft_id = :draft_id
        RETURNING *;
    """)
    result = await session.execute(update_stmt, {"status": new_status.value, "draft_id": draft_id})
    await session.commit()

    updated_row = result.mappings().fetchone()
    if not updated_row:
        raise HTTPException(status_code=404, detail="Draft not found")

    res_dict = dict(updated_row)
    # Locking info might be null if we didn't join, but the table has the columns.
    return DraftResponse.model_validate(res_dict)


async def assemble_artifact(session: AsyncSession, draft_id: UUID, user_oid: UUID) -> AgentArtifact:
    """
    Assembles the canonical AgentArtifact from a draft.
    Requires draft to be APPROVED.
    """
    # Use get_draft_by_id as standard accessor.
    draft = await get_draft_by_id(session, draft_id, user_oid, [])
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


async def publish_artifact(session: AsyncSession, draft_id: UUID, signature: str, user_oid: UUID) -> str:
    """
    Publishes the signed artifact.
    """
    # 1. Assemble (checks approval)
    artifact = await assemble_artifact(session, draft_id, user_oid)

    # 2. Inject Signature
    artifact.author_signature = signature

    # 3. Mock Git Push
    logger.info(f"Pushing artifact {artifact.id} to GitLab for user {user_oid}...")
    mock_url = f"https://gitlab.example.com/agents/{draft_id}/v1"

    return mock_url
