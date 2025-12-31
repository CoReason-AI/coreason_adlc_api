# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

import logging
from typing import List, Dict, Any, Generator

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel.ext.asyncio.session import AsyncSession

from coreason_adlc_api.auth.identity import get_current_user, UserIdentity
from coreason_adlc_api.workbench.schemas import (
    DraftCreate, DraftResponse, DraftUpdate, ArtifactResponse, PublishRequest,
    ReviewRequest
)
from coreason_adlc_api.workbench.service import WorkbenchService
from coreason_adlc_api.workbench.locking import DraftLockManager
from coreason_adlc_api.db import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workbench", tags=["workbench"])

async def get_service(
    session: AsyncSession = Depends(get_db),
    user: UserIdentity = Depends(get_current_user)
) -> WorkbenchService:
    return WorkbenchService(session, user)

async def get_lock_manager(
    session: AsyncSession = Depends(get_db),
    user: UserIdentity = Depends(get_current_user)
) -> DraftLockManager:
    return DraftLockManager(session, user)


@router.post("/drafts", response_model=DraftResponse, status_code=201)
async def create_draft(
    draft_in: DraftCreate,
    service: WorkbenchService = Depends(get_service)
) -> DraftResponse:
    """
    Creates a new draft for a project.
    """
    return await service.create_draft(draft_in)


@router.get("/drafts/{draft_id}", response_model=DraftResponse)
async def get_draft(
    draft_id: str,
    service: WorkbenchService = Depends(get_service)
) -> DraftResponse:
    """
    Retrieves a draft by ID.
    """
    return await service.get_draft(draft_id)


@router.put("/drafts/{draft_id}", response_model=DraftResponse)
async def update_draft(
    draft_id: str,
    draft_in: DraftUpdate,
    service: WorkbenchService = Depends(get_service),
    lock_manager: DraftLockManager = Depends(get_lock_manager)
) -> DraftResponse:
    """
    Updates a draft. Must have a valid lock or acquire one implicitly if allowed.
    """
    # Ensure lock is held or acquire it
    # For now, let's assume service handles logical checks, but locking is explicit in API usually.
    # Actually, simplistic: Acquire lock -> Update -> Release/Keep?
    # Better: service.update_draft handles check.

    # We can rely on service to check if user has lock.
    return await service.update_draft(draft_id, draft_in)


@router.post("/drafts/{draft_id}/lock", response_model=bool)
async def lock_draft(
    draft_id: str,
    force: bool = False,
    lock_manager: DraftLockManager = Depends(get_lock_manager)
) -> bool:
    """
    Acquires an exclusive lock on the draft for editing.
    """
    return await lock_manager.acquire_lock(draft_id, force=force)


@router.delete("/drafts/{draft_id}/lock", response_model=bool)
async def unlock_draft(
    draft_id: str,
    lock_manager: DraftLockManager = Depends(get_lock_manager)
) -> bool:
    """
    Releases the lock on the draft.
    """
    return await lock_manager.release_lock(draft_id)


@router.post("/drafts/{draft_id}/publish", response_model=ArtifactResponse)
async def publish_draft(
    draft_id: str,
    publish_req: PublishRequest,
    service: WorkbenchService = Depends(get_service)
) -> ArtifactResponse:
    """
    Publishes a draft as an immutable artifact.
    """
    return await service.publish_artifact(draft_id, publish_req)


@router.post("/drafts/{draft_id}/review", response_model=DraftResponse)
async def review_draft(
    draft_id: str,
    review_req: ReviewRequest,
    service: WorkbenchService = Depends(get_service)
) -> DraftResponse:
    """
    Submits a review (Approve/Reject) for a draft.
    """
    if review_req.decision == "APPROVE":
        return await service.approve_draft(draft_id)
    else:
        return await service.reject_draft(draft_id, review_req.comment)
