# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, status

from coreason_adlc_api.auth.identity import UserIdentity, parse_and_validate_token
from coreason_adlc_api.workbench.schemas import (
    AgentArtifact,
    DraftCreate,
    DraftResponse,
    DraftUpdate,
    ValidationResponse,
)
from coreason_adlc_api.workbench.service_governed import WorkbenchService

router = APIRouter(prefix="/workbench", tags=["Workbench"])


@router.get("/drafts", response_model=list[DraftResponse])
async def list_drafts(auc_id: str, identity: UserIdentity = Depends(parse_and_validate_token)) -> list[DraftResponse]:
    """
    Returns list of drafts filterable by auc_id.
    """
    res = await WorkbenchService().list_drafts(auc_id, identity.oid, identity.groups)
    return res


@router.post("/drafts", response_model=DraftResponse, status_code=status.HTTP_201_CREATED)
async def create_new_draft(
    draft: DraftCreate,
    identity: UserIdentity = Depends(parse_and_validate_token),
    x_coreason_sig: Optional[str] = Header(None, alias="x-coreason-sig"),
) -> DraftResponse:
    """
    Creates a new agent draft.
    """
    res = await WorkbenchService().create_draft(draft, identity.oid, identity.groups, signature=x_coreason_sig)
    return res


@router.get("/drafts/{draft_id}", response_model=DraftResponse)
async def get_draft(draft_id: UUID, identity: UserIdentity = Depends(parse_and_validate_token)) -> DraftResponse:
    """
    Returns draft content and acquires lock.
    """
    res = await WorkbenchService().get_draft(draft_id, identity.oid, identity.groups)
    return res


@router.put("/drafts/{draft_id}", response_model=DraftResponse)
async def update_existing_draft(
    draft_id: UUID, update: DraftUpdate, identity: UserIdentity = Depends(parse_and_validate_token)
) -> DraftResponse:
    """
    Updates draft content.
    (Requires active Lock)
    """
    res = await WorkbenchService().update_draft(draft_id, update, identity.oid, identity.groups)
    return res


@router.post("/drafts/{draft_id}/lock")
async def heartbeat_lock(draft_id: UUID, identity: UserIdentity = Depends(parse_and_validate_token)) -> dict[str, bool]:
    """
    Refreshes the lock expiry.
    """
    res = await WorkbenchService().lock_draft(draft_id, identity.oid, identity.groups)
    return res


@router.post("/validate", response_model=ValidationResponse)
async def validate_draft(
    draft: DraftCreate, identity: UserIdentity = Depends(parse_and_validate_token)
) -> ValidationResponse:
    """
    Stateless validation of a draft.
    Checks for:
    1. Budget limits (read-only)
    2. PII presence (recursive)
    Does NOT save to DB.
    """
    res = await WorkbenchService().validate_draft(draft, identity.oid, identity.groups)
    return res


# --- Approval Workflow Endpoints ---


@router.post("/drafts/{draft_id}/submit", response_model=DraftResponse)
async def submit_draft(draft_id: UUID, identity: UserIdentity = Depends(parse_and_validate_token)) -> DraftResponse:
    """
    Submits a draft for approval.
    Transitions: DRAFT/REJECTED -> PENDING
    """
    res = await WorkbenchService().submit_draft(draft_id, identity.oid, identity.groups)
    return res


@router.post("/drafts/{draft_id}/approve", response_model=DraftResponse)
async def approve_draft(draft_id: UUID, identity: UserIdentity = Depends(parse_and_validate_token)) -> DraftResponse:
    """
    Approves a pending draft.
    Transitions: PENDING -> APPROVED
    Requires: MANAGER role
    """
    res = await WorkbenchService().approve_draft(draft_id, identity.oid, identity.groups)
    return res


@router.post("/drafts/{draft_id}/reject", response_model=DraftResponse)
async def reject_draft(draft_id: UUID, identity: UserIdentity = Depends(parse_and_validate_token)) -> DraftResponse:
    """
    Rejects a pending draft.
    Transitions: PENDING -> REJECTED
    Requires: MANAGER role
    """
    res = await WorkbenchService().reject_draft(draft_id, identity.oid, identity.groups)
    return res


# --- Artifact Assembly & Publication Endpoints ---


@router.get("/drafts/{draft_id}/assemble", response_model=AgentArtifact)
async def get_artifact_assembly(
    draft_id: UUID, identity: UserIdentity = Depends(parse_and_validate_token)
) -> AgentArtifact:
    """
    Returns the assembled AgentArtifact for an APPROVED draft.
    """
    res = await WorkbenchService().assemble_artifact(draft_id, identity.oid, identity.groups)
    return res


@router.post("/drafts/{draft_id}/publish", response_model=dict[str, str])
async def publish_agent_artifact(
    draft_id: UUID,
    identity: UserIdentity = Depends(parse_and_validate_token),
    x_coreason_sig: str = Header(..., alias="x-coreason-sig"),
) -> dict[str, str]:
    """
    Publishes the signed artifact.
    """
    # Note: request body is removed as per plan
    res = await WorkbenchService().publish_artifact(
        draft_id=draft_id, signature=x_coreason_sig, user_oid=identity.oid, groups=identity.groups
    )
    return res
