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

from coreason_adlc_api.db import get_pool
from coreason_adlc_api.workbench.locking import acquire_draft_lock, verify_lock_for_update
from coreason_adlc_api.workbench.schemas import ApprovalStatus, DraftCreate, DraftResponse, DraftUpdate


async def create_draft(draft: DraftCreate, user_uuid: UUID) -> DraftResponse:
    pool = get_pool()
    query = """
        INSERT INTO workbench.agent_drafts
        (user_uuid, auc_id, title, oas_content, runtime_env)
        VALUES ($1, $2, $3, $4::jsonb, $5)
        RETURNING *;
    """
    row = await pool.fetchrow(
        query, user_uuid, draft.auc_id, draft.title, json.dumps(draft.oas_content), draft.runtime_env
    )
    if not row:
        raise RuntimeError("Failed to create draft")
    return DraftResponse.model_validate(dict(row))


async def get_drafts(auc_id: str, include_deleted: bool = False) -> List[DraftResponse]:
    pool = get_pool()
    query = """
        SELECT * FROM workbench.agent_drafts
        WHERE auc_id = $1 AND ($2 = TRUE OR is_deleted = FALSE)
        ORDER BY updated_at DESC;
    """
    rows = await pool.fetch(query, auc_id, include_deleted)
    return [DraftResponse.model_validate(dict(r)) for r in rows]


async def get_draft_by_id(draft_id: UUID, user_uuid: UUID, roles: List[str]) -> Optional[DraftResponse]:
    # Try to acquire lock
    try:
        mode = await acquire_draft_lock(draft_id, user_uuid, roles)
    except HTTPException as e:
        if e.status_code == 404:
            return None
        raise e

    pool = get_pool()
    query = "SELECT * FROM workbench.agent_drafts WHERE draft_id = $1;"
    row = await pool.fetchrow(query, draft_id)
    if not row:
        return None

    resp = DraftResponse.model_validate(dict(row))
    resp.mode = mode
    return resp


async def _check_status_for_update(draft_id: UUID) -> None:
    pool = get_pool()
    query = "SELECT status FROM workbench.agent_drafts WHERE draft_id = $1"
    status_row = await pool.fetchrow(query, draft_id)
    if not status_row:
        raise HTTPException(status_code=404, detail="Draft not found")

    status = status_row["status"]
    if status not in (ApprovalStatus.DRAFT, ApprovalStatus.REJECTED):
        raise HTTPException(
            status_code=409, detail=f"Cannot edit draft in '{status}' status. Must be DRAFT or REJECTED."
        )


async def update_draft(draft_id: UUID, update: DraftUpdate, user_uuid: UUID) -> DraftResponse:
    # Verify Lock
    await verify_lock_for_update(draft_id, user_uuid)

    # Verify Status (Cannot edit if PENDING or APPROVED)
    await _check_status_for_update(draft_id)

    pool = get_pool()

    # Dynamic update query construction could be cleaner, but simple approach for now
    fields: List[str] = []
    args: List[Any] = []
    idx = 1

    if update.title is not None:
        fields.append(f"title = ${idx}")
        args.append(update.title)
        idx += 1
    if update.oas_content is not None:
        fields.append(f"oas_content = ${idx}::jsonb")
        args.append(json.dumps(update.oas_content))
        idx += 1
    if update.runtime_env is not None:
        fields.append(f"runtime_env = ${idx}")
        args.append(update.runtime_env)
        idx += 1

    if not fields:
        # No updates
        # We pass empty roles list here because update_draft assumes we already hold the lock (verified above)
        # So re-acquiring lock inside get_draft_by_id should succeed as we are the owner.
        current = await get_draft_by_id(draft_id, user_uuid, [])
        if not current:
            raise HTTPException(status_code=404, detail="Draft not found")
        return current

    fields.append("updated_at = NOW()")

    # WHERE clause
    where_clause = f"WHERE draft_id = ${idx}"
    args.append(draft_id)

    query = f"""
        UPDATE workbench.agent_drafts
        SET {", ".join(fields)}
        {where_clause}
        RETURNING *;
    """

    row = await pool.fetchrow(query, *args)
    if not row:
        raise HTTPException(status_code=404, detail="Draft not found")

    return DraftResponse.model_validate(dict(row))


async def transition_draft_status(draft_id: UUID, user_uuid: UUID, new_status: ApprovalStatus) -> DraftResponse:
    """
    Handles state transitions:
    - DRAFT -> PENDING (Submit)
    - PENDING -> APPROVED (Approve)
    - PENDING -> REJECTED (Reject)
    - REJECTED -> PENDING (Re-submit)
    """
    pool = get_pool()

    # Get current status
    query = "SELECT status FROM workbench.agent_drafts WHERE draft_id = $1"
    row = await pool.fetchrow(query, draft_id)
    if not row:
        raise HTTPException(status_code=404, detail="Draft not found")

    current_status = row["status"]

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
        raise HTTPException(status_code=409, detail=f"Invalid transition from {current_status} to {new_status}")

    # Perform Update
    update_query = """
        UPDATE workbench.agent_drafts
        SET status = $1, updated_at = NOW()
        WHERE draft_id = $2
        RETURNING *;
    """
    updated_row = await pool.fetchrow(update_query, new_status.value, draft_id)

    # We return the response. Note: We might need to mock locking info or fetch it fully.
    # For simplicity, we re-fetch via get_draft_by_id to get full context including lock state.
    # But get_draft_by_id attempts to acquire lock.
    # Since we are just changing status, let's just return the object directly to avoid side-effects.

    # Construct response manually to avoid lock overhead or just assume default lock state for response
    # Actually, best to return consistent response.
    # Let's map it directly.

    res_dict = dict(updated_row)
    # Locking info might be null if we didn't join, but the table has the columns.
    return DraftResponse.model_validate(res_dict)
