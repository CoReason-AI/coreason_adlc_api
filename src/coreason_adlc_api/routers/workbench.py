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

from fastapi import APIRouter, Depends, Header, HTTPException, status

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


@router.get("/drafts", response_model=list[DraftResponse])  # type: ignore[misc]
async def list_drafts(auc_id: str, identity: UserIdentity = Depends(parse_and_validate_token)) -> list[DraftResponse]:
    """
    Returns list of drafts filterable by auc_id.
    """
    return await WorkbenchService().list_drafts(  # type: ignore[no-any-return]
        auc_id=auc_id, user_oid=identity.oid, groups=identity.groups
    )


@router.post("/drafts", response_model=DraftResponse, status_code=status.HTTP_201_CREATED)  # type: ignore[misc]
async def create_new_draft(
    draft: DraftCreate,
    identity: UserIdentity = Depends(parse_and_validate_token),
    x_coreason_sig: Optional[str] = Header(None, alias="x-coreason-sig"),
) -> DraftResponse:
    """
    Creates a new agent draft.
    """
    return await WorkbenchService().create_draft(  # type: ignore[no-any-return]
        draft=draft, user_oid=identity.oid, groups=identity.groups, signature=x_coreason_sig
    )


@router.get("/drafts/{draft_id}", response_model=DraftResponse)  # type: ignore[misc]
async def get_draft(draft_id: UUID, identity: UserIdentity = Depends(parse_and_validate_token)) -> DraftResponse:
    """
    Returns draft content and acquires lock.
    """
    return await WorkbenchService().get_draft(  # type: ignore[no-any-return]
        draft_id=draft_id, user_oid=identity.oid, groups=identity.groups
    )


@router.put("/drafts/{draft_id}", response_model=DraftResponse)  # type: ignore[misc]
async def update_existing_draft(
    draft_id: UUID, update: DraftUpdate, identity: UserIdentity = Depends(parse_and_validate_token)
) -> DraftResponse:
    """
    Updates draft content.
    (Requires active Lock)
    """
    return await WorkbenchService().update_draft(  # type: ignore[no-any-return]
        draft_id=draft_id, update=update, user_oid=identity.oid, groups=identity.groups
    )


@router.post("/drafts/{draft_id}/lock")  # type: ignore[misc]
async def heartbeat_lock(draft_id: UUID, identity: UserIdentity = Depends(parse_and_validate_token)) -> dict[str, bool]:
    """
    Refreshes the lock expiry.
    """
    return await WorkbenchService().heartbeat_lock(  # type: ignore[no-any-return]
        draft_id=draft_id, user_oid=identity.oid, groups=identity.groups
    )


@router.post("/validate", response_model=ValidationResponse)  # type: ignore[misc]
async def validate_draft(
    draft: DraftCreate, identity: UserIdentity = Depends(parse_and_validate_token)
) -> ValidationResponse:
    """
    Stateless validation of a draft.
    """
    return await WorkbenchService().validate_draft(  # type: ignore[no-any-return]
        draft=draft, user_oid=identity.oid, groups=identity.groups
    )


# --- Approval Workflow Endpoints ---


@router.post("/drafts/{draft_id}/submit", response_model=DraftResponse)  # type: ignore[misc]
async def submit_draft(draft_id: UUID, identity: UserIdentity = Depends(parse_and_validate_token)) -> DraftResponse:
    """
    Submits a draft for approval.
    """
    return await WorkbenchService().submit_draft(  # type: ignore[no-any-return]
        draft_id=draft_id, user_oid=identity.oid, groups=identity.groups
    )


@router.post("/drafts/{draft_id}/approve", response_model=DraftResponse)  # type: ignore[misc]
async def approve_draft(draft_id: UUID, identity: UserIdentity = Depends(parse_and_validate_token)) -> DraftResponse:
    """
    Approves a pending draft.
    """
    return await WorkbenchService().approve_draft(  # type: ignore[no-any-return]
        draft_id=draft_id, user_oid=identity.oid, groups=identity.groups
    )


@router.post("/drafts/{draft_id}/reject", response_model=DraftResponse)  # type: ignore[misc]
async def reject_draft(draft_id: UUID, identity: UserIdentity = Depends(parse_and_validate_token)) -> DraftResponse:
    """
    Rejects a pending draft.
    """
    return await WorkbenchService().reject_draft(  # type: ignore[no-any-return]
        draft_id=draft_id, user_oid=identity.oid, groups=identity.groups
    )


# --- Artifact Assembly & Publication Endpoints ---


@router.get("/drafts/{draft_id}/assemble", response_model=AgentArtifact)  # type: ignore[misc]
async def get_artifact_assembly(
    draft_id: UUID, identity: UserIdentity = Depends(parse_and_validate_token)
) -> AgentArtifact:
    """
    Returns the assembled AgentArtifact for an APPROVED draft.
    """
    return await WorkbenchService().get_artifact_assembly(  # type: ignore[no-any-return]
        draft_id=draft_id, user_oid=identity.oid, groups=identity.groups
    )


@router.post("/drafts/{draft_id}/publish", response_model=dict[str, str])  # type: ignore[misc]
async def publish_agent_artifact(
    draft_id: UUID,
    identity: UserIdentity = Depends(parse_and_validate_token),
    x_coreason_sig: Optional[str] = Header(None, alias="x-coreason-sig"),
) -> dict[str, str]:
    """
    Publishes the signed artifact.
    """
    # Strict mode requires signature, but type hint is Optional in header extraction
    # The service will validate it (or allow_unsigned=False will)
    # Strict mode requires signature
    # Decorate with allow_unsigned=False (Strict Mode). It must accept signature (required) and user_oid.
    # If I pass None, the decorator might fail or the service method logic might fail.
    # The prompt says: "Make the service method accept signature explicitly as a string argument."
    # If the header is missing, x_coreason_sig is None.
    # I will stick to the extracted header being Optional (standard for headers),
    # but I will cast or check before calling service if strict mode is required.
    # `governed_execution` with `allow_unsigned=False` checks if `signature` is valid.
    # If I pass `signature=None`, `governed_execution` will raise a GovernanceException.
    # But for type checking sake:
    if x_coreason_sig is None:
        # If strict mode is enforced, we can raise here or let the service fail.
        # Ideally, we should let the service/governance layer handle it to centralize logic.
        # But for mypy, I might need to cast or change service signature to Optional[str].
        # In `service_governed.py`, I defined `signature: str`.
        # So I must ensure it is a string.
        raise HTTPException(status_code=400, detail="Missing x-coreason-sig header")

    url = await WorkbenchService().publish_artifact(
        draft_id=draft_id, user_oid=identity.oid, groups=identity.groups, signature=x_coreason_sig
    )
    return {"url": url}
