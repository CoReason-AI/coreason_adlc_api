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

from coreason_adlc_api.auth.identity import UserIdentity, parse_and_validate_token
from coreason_adlc_api.workbench.schemas import (
    AgentArtifact,
    DraftCreate,
    DraftResponse,
    DraftUpdate,
    PublishRequest,
    ValidationResponse,
)
from coreason_adlc_api.workbench.service_governed import WorkbenchService
from fastapi import APIRouter, Depends, Header, status

router = APIRouter(prefix="/workbench", tags=["Workbench"])


@router.get("/drafts", response_model=list[DraftResponse])
async def list_drafts(
    auc_id: str,
    identity: UserIdentity = Depends(parse_and_validate_token),
    x_coreason_sig: Optional[str] = Header(None, alias="x-coreason-sig"),
) -> list[DraftResponse]:
    """
    Returns list of drafts filterable by auc_id.
    """
    return await WorkbenchService().list_drafts(  # type: ignore[no-any-return]
        auc_id=auc_id, user_oid=identity.oid, groups=identity.groups, signature=x_coreason_sig
    )


@router.post("/drafts", response_model=DraftResponse, status_code=status.HTTP_201_CREATED)
async def create_new_draft(
    draft: DraftCreate,
    identity: UserIdentity = Depends(parse_and_validate_token),
    x_coreason_sig: Optional[str] = Header(None, alias="x-coreason-sig"),
) -> DraftResponse:
    """
    Creates a new agent draft.
    """
    return await WorkbenchService().create_new_draft(  # type: ignore[no-any-return]
        draft=draft, user_oid=identity.oid, groups=identity.groups, signature=x_coreason_sig
    )


@router.get("/drafts/{draft_id}", response_model=DraftResponse)
async def get_draft(
    draft_id: UUID,
    identity: UserIdentity = Depends(parse_and_validate_token),
    x_coreason_sig: Optional[str] = Header(None, alias="x-coreason-sig"),
) -> DraftResponse:
    """
    Returns draft content and acquires lock.
    """
    return await WorkbenchService().get_draft(  # type: ignore[no-any-return]
        draft_id=draft_id, user_oid=identity.oid, groups=identity.groups, signature=x_coreason_sig
    )


@router.put("/drafts/{draft_id}", response_model=DraftResponse)
async def update_existing_draft(
    draft_id: UUID,
    update: DraftUpdate,
    identity: UserIdentity = Depends(parse_and_validate_token),
    x_coreason_sig: Optional[str] = Header(None, alias="x-coreason-sig"),
) -> DraftResponse:
    """
    Updates draft content.
    (Requires active Lock)
    """
    return await WorkbenchService().update_existing_draft(  # type: ignore[no-any-return]
        draft_id=draft_id, update=update, user_oid=identity.oid, groups=identity.groups, signature=x_coreason_sig
    )


@router.post("/drafts/{draft_id}/lock")
async def heartbeat_lock(
    draft_id: UUID,
    identity: UserIdentity = Depends(parse_and_validate_token),
    x_coreason_sig: Optional[str] = Header(None, alias="x-coreason-sig"),
) -> dict[str, bool]:
    """
    Refreshes the lock expiry.
    """
    return await WorkbenchService().heartbeat_lock(  # type: ignore[no-any-return]
        draft_id=draft_id, user_oid=identity.oid, groups=identity.groups, signature=x_coreason_sig
    )


@router.post("/validate", response_model=ValidationResponse)
async def validate_draft(
    draft: DraftCreate,
    identity: UserIdentity = Depends(parse_and_validate_token),
    x_coreason_sig: Optional[str] = Header(None, alias="x-coreason-sig"),
) -> ValidationResponse:
    """
    Stateless validation of a draft.
    """
    return await WorkbenchService().validate_draft(  # type: ignore[no-any-return]
        draft=draft, user_oid=identity.oid, groups=identity.groups, signature=x_coreason_sig
    )


# --- Approval Workflow Endpoints ---


@router.post("/drafts/{draft_id}/submit", response_model=DraftResponse)
async def submit_draft(
    draft_id: UUID,
    identity: UserIdentity = Depends(parse_and_validate_token),
    x_coreason_sig: Optional[str] = Header(None, alias="x-coreason-sig"),
) -> DraftResponse:
    """
    Submits a draft for approval.
    Transitions: DRAFT/REJECTED -> PENDING
    """
    return await WorkbenchService().submit_draft(  # type: ignore[no-any-return]
        draft_id=draft_id, user_oid=identity.oid, groups=identity.groups, signature=x_coreason_sig
    )


@router.post("/drafts/{draft_id}/approve", response_model=DraftResponse)
async def approve_draft(
    draft_id: UUID,
    identity: UserIdentity = Depends(parse_and_validate_token),
    x_coreason_sig: Optional[str] = Header(None, alias="x-coreason-sig"),
) -> DraftResponse:
    """
    Approves a pending draft.
    Transitions: PENDING -> APPROVED
    Requires: MANAGER role
    """
    return await WorkbenchService().approve_draft(  # type: ignore[no-any-return]
        draft_id=draft_id, user_oid=identity.oid, groups=identity.groups, signature=x_coreason_sig
    )


@router.post("/drafts/{draft_id}/reject", response_model=DraftResponse)
async def reject_draft(
    draft_id: UUID,
    identity: UserIdentity = Depends(parse_and_validate_token),
    x_coreason_sig: Optional[str] = Header(None, alias="x-coreason-sig"),
) -> DraftResponse:
    """
    Rejects a pending draft.
    Transitions: PENDING -> REJECTED
    Requires: MANAGER role
    """
    return await WorkbenchService().reject_draft(  # type: ignore[no-any-return]
        draft_id=draft_id, user_oid=identity.oid, groups=identity.groups, signature=x_coreason_sig
    )


# --- Artifact Assembly & Publication Endpoints ---


@router.get("/drafts/{draft_id}/assemble", response_model=AgentArtifact)
async def get_artifact_assembly(
    draft_id: UUID,
    identity: UserIdentity = Depends(parse_and_validate_token),
    x_coreason_sig: Optional[str] = Header(None, alias="x-coreason-sig"),
) -> AgentArtifact:
    """
    Returns the assembled AgentArtifact for an APPROVED draft.
    """
    return await WorkbenchService().get_artifact_assembly(  # type: ignore[no-any-return]
        draft_id=draft_id, user_oid=identity.oid, groups=identity.groups, signature=x_coreason_sig
    )


@router.post("/drafts/{draft_id}/publish", response_model=dict[str, str])
async def publish_agent_artifact(
    draft_id: UUID,
    request: PublishRequest,
    identity: UserIdentity = Depends(parse_and_validate_token),
    x_coreason_sig: str = Header(..., alias="x-coreason-sig"),
) -> dict[str, str]:
    """
    Publishes the signed artifact.
    """
    return await WorkbenchService().publish_artifact(  # type: ignore[no-any-return]
        draft_id=draft_id,
        request=request,
        signature=x_coreason_sig,
        user_oid=identity.oid,
        groups=identity.groups,
    )
