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

from coreason_adlc_api.db import get_pool
from coreason_adlc_api.workbench.locking import acquire_draft_lock, verify_lock_for_update
from coreason_adlc_api.workbench.schemas import DraftCreate, DraftResponse, DraftUpdate
from fastapi import HTTPException


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


async def update_draft(draft_id: UUID, update: DraftUpdate, user_uuid: UUID) -> DraftResponse:
    # Verify Lock
    await verify_lock_for_update(draft_id, user_uuid)

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
