# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

from uuid import UUID

from coreason_adlc_api.auth.identity import UserIdentity, parse_and_validate_token
from coreason_adlc_api.db import get_pool
from coreason_adlc_api.workbench.locking import refresh_lock
from coreason_adlc_api.workbench.schemas import DraftCreate, DraftResponse, DraftUpdate
from coreason_adlc_api.workbench.service import create_draft, get_draft_by_id, get_drafts, update_draft
from fastapi import APIRouter, Depends, HTTPException, status

router = APIRouter(prefix="/workbench", tags=["Workbench"])


@router.get("/drafts", response_model=list[DraftResponse])
async def list_drafts(auc_id: str, identity: UserIdentity = Depends(parse_and_validate_token)) -> list[DraftResponse]:
    """
    Returns list of drafts filterable by auc_id.
    """
    # Authorization: User must have access to auc_id
    # TODO: Check identity.groups via map_groups logic
    return await get_drafts(auc_id)


@router.post("/drafts", response_model=DraftResponse, status_code=status.HTTP_201_CREATED)
async def create_new_draft(
    draft: DraftCreate, identity: UserIdentity = Depends(parse_and_validate_token)
) -> DraftResponse:
    """
    Creates a new agent draft.
    """
    return await create_draft(draft, identity.oid)


@router.get("/drafts/{draft_id}", response_model=DraftResponse)
async def get_draft(draft_id: UUID, identity: UserIdentity = Depends(parse_and_validate_token)) -> DraftResponse:
    """
    Returns draft content and acquires lock.
    """
    # Fetch Roles (Mocked logic or via group mapping if roles were stored there)
    roles = await _get_user_roles(identity.groups)

    draft = await get_draft_by_id(draft_id, identity.oid, roles)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    return draft


@router.put("/drafts/{draft_id}", response_model=DraftResponse)
async def update_existing_draft(
    draft_id: UUID, update: DraftUpdate, identity: UserIdentity = Depends(parse_and_validate_token)
) -> DraftResponse:
    """
    Updates draft content.
    (Requires active Lock)
    """
    return await update_draft(draft_id, update, identity.oid)


@router.post("/drafts/{draft_id}/lock")
async def heartbeat_lock(draft_id: UUID, identity: UserIdentity = Depends(parse_and_validate_token)) -> dict[str, bool]:
    """
    Refreshes the lock expiry.
    """
    await refresh_lock(draft_id, identity.oid)
    return {"success": True}


async def _get_user_roles(group_oids: list[UUID]) -> list[str]:
    # TODO: Refactor into identity module
    pool = get_pool()
    query = "SELECT role_name FROM identity.group_mappings WHERE sso_group_oid = ANY($1::uuid[])"
    rows = await pool.fetch(query, group_oids)
    return [r["role_name"] for r in rows]
