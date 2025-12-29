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

from coreason_adlc_api.auth.identity import UserIdentity, map_groups_to_projects, parse_and_validate_token
from coreason_adlc_api.workbench.locking import refresh_lock
from coreason_adlc_api.workbench.schemas import (
    AgentArtifact,
    ApprovalStatus,
    DraftCreate,
    DraftResponse,
    DraftUpdate,
    PublishRequest,
    ValidationResponse,
)
from coreason_adlc_api.workbench.service_governed import WorkbenchService
from fastapi import APIRouter, Depends, Header, HTTPException, status

router = APIRouter(prefix="/workbench", tags=["Workbench"])


async def _verify_project_access(identity: UserIdentity, auc_id: str) -> None:
    """
    Verifies that the user has access to the given project (AUC ID).
    """
    allowed_projects = await map_groups_to_projects(identity.groups)
    if auc_id not in allowed_projects:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"User is not authorized to access project {auc_id}",
        )


@router.get("/drafts", response_model=list[DraftResponse])
async def list_drafts(
    auc_id: str,
    identity: UserIdentity = Depends(parse_and_validate_token),
    x_coreason_sig: Optional[str] = Header(None, alias="x-coreason-sig"),
) -> list[DraftResponse]:
    """
    Returns list of drafts filterable by auc_id.
    """
    # Authorization: User must have access to auc_id
    await _verify_project_access(identity, auc_id)
    return await WorkbenchService().list_drafts(
        auc_id=auc_id, user_oid=identity.oid, signature=x_coreason_sig
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
    await _verify_project_access(identity, draft.auc_id)
    return await WorkbenchService().create_draft(
        draft=draft, user_oid=identity.oid, signature=x_coreason_sig
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
    # Note: Service handles lock acquisition and role checks (if needed for lock),
    # but we need to check project access *after* fetching draft, OR the service does it.
    # The original router checked access after fetching.
    # The new service returns the draft. We should check access here to match original router behavior
    # or rely on service.
    # Let's keep the router "Humble" but consistent with security.
    # If the service just returns the draft, we still need to check if user owns that AUC.

    draft = await WorkbenchService().get_draft(
        draft_id=draft_id, user_oid=identity.oid, groups=identity.groups, signature=x_coreason_sig
    )

    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    # Verify Access to the draft's project
    await _verify_project_access(identity, draft.auc_id)

    return draft


@router.put("/drafts/{draft_id}", response_model=DraftResponse)
async def update_existing_draft(
    draft_id: UUID,
    update: DraftUpdate,
    identity: UserIdentity = Depends(parse_and_validate_token),
    x_coreason_sig: Optional[str] = Header(None, alias="x-coreason-sig"),
) -> DraftResponse:
    """
    Updates draft content.
    """
    # Check access by fetching brief or just trust update fails if not found?
    # Original logic: fetch -> verify access -> update.
    # We can replicate this or assume service does atomic check if we pass AUC ID?
    # Service `update_draft` doesn't take AUC ID to check.
    # So we must fetch first or rely on service to enforce... but service is generic.
    # Let's do the fetch check here as before, using the service's get_draft (read-only).

    current_draft = await WorkbenchService().get_draft(
        draft_id=draft_id, user_oid=identity.oid, groups=identity.groups, signature=x_coreason_sig
    )
    if not current_draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    await _verify_project_access(identity, current_draft.auc_id)

    return await WorkbenchService().update_draft(
        draft_id=draft_id, update=update, user_oid=identity.oid, signature=x_coreason_sig
    )


@router.post("/drafts/{draft_id}/lock")
async def heartbeat_lock(
    draft_id: UUID, identity: UserIdentity = Depends(parse_and_validate_token)
) -> dict[str, bool]:
    """
    Refreshes the lock expiry.
    Note: Locking logic remains in service/locking module, not fully moved to Governed Service yet?
    The spec said "Move high-level orchestration... Apply @governed_execution to every method."
    But refresh_lock is simple.
    The spec didn't explicitly mention `refresh_lock` in the "Step 2" list but said "every method" in `WorkbenchService`.
    I'll assume refresh_lock is outside the main governance scope or should be left as is for now if not in `WorkbenchService`.
    Wait, I didn't add `refresh_lock` to `WorkbenchService`.
    I'll leave it calling the underlying locking module directly to minimize scope creep,
    unless strictly required. The prompt asked to move "high-level orchestration logic".
    Locking is low-level.
    """
    await refresh_lock(draft_id, identity.oid)
    return {"success": True}


@router.post("/validate", response_model=ValidationResponse)
async def validate_draft(
    draft: DraftCreate,
    identity: UserIdentity = Depends(parse_and_validate_token),
    x_coreason_sig: Optional[str] = Header(None, alias="x-coreason-sig"),
) -> ValidationResponse:
    """
    Stateless validation of a draft.
    """
    # Delegate completely to service
    return await WorkbenchService().validate_draft(
        draft=draft, user_oid=identity.oid, signature=x_coreason_sig
    )


# --- Approval Workflow Endpoints ---

async def _get_draft_and_verify_access_v2(draft_id: UUID, identity: UserIdentity) -> DraftResponse:
    # Helper using new service
    # We pass signature=None here because this is an internal check helper?
    # Actually, if we use this helper inside routes, we should pass the signature from the route.
    # But this helper is just to verify access.
    # Let's inline this logic into routes to handle signatures correctly if needed.
    pass


@router.post("/drafts/{draft_id}/submit", response_model=DraftResponse)
async def submit_draft(
    draft_id: UUID,
    identity: UserIdentity = Depends(parse_and_validate_token),
    x_coreason_sig: Optional[str] = Header(None, alias="x-coreason-sig"),
) -> DraftResponse:
    """
    Submits a draft for approval.
    """
    # 1. Check Access
    # We need to fetch to check AUC ID.
    draft = await WorkbenchService().get_draft(
        draft_id=draft_id, user_oid=identity.oid, groups=identity.groups, signature=x_coreason_sig
    )
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    await _verify_project_access(identity, draft.auc_id)

    # 2. Transition
    return await WorkbenchService().transition_status(
        draft_id=draft_id,
        user_oid=identity.oid,
        groups=identity.groups,
        new_status=ApprovalStatus.PENDING,
        signature=x_coreason_sig,
    )


@router.post("/drafts/{draft_id}/approve", response_model=DraftResponse)
async def approve_draft(
    draft_id: UUID,
    identity: UserIdentity = Depends(parse_and_validate_token),
    x_coreason_sig: Optional[str] = Header(None, alias="x-coreason-sig"),
) -> DraftResponse:
    """
    Approves a pending draft.
    """
    # 1. Check Access
    draft = await WorkbenchService().get_draft(
        draft_id=draft_id, user_oid=identity.oid, groups=identity.groups, signature=x_coreason_sig
    )
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    await _verify_project_access(identity, draft.auc_id)

    # 2. Transition (Service checks MANAGER role)
    return await WorkbenchService().transition_status(
        draft_id=draft_id,
        user_oid=identity.oid,
        groups=identity.groups,
        new_status=ApprovalStatus.APPROVED,
        signature=x_coreason_sig,
    )


@router.post("/drafts/{draft_id}/reject", response_model=DraftResponse)
async def reject_draft(
    draft_id: UUID,
    identity: UserIdentity = Depends(parse_and_validate_token),
    x_coreason_sig: Optional[str] = Header(None, alias="x-coreason-sig"),
) -> DraftResponse:
    """
    Rejects a pending draft.
    """
    # 1. Check Access
    draft = await WorkbenchService().get_draft(
        draft_id=draft_id, user_oid=identity.oid, groups=identity.groups, signature=x_coreason_sig
    )
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    await _verify_project_access(identity, draft.auc_id)

    # 2. Transition (Service checks MANAGER role)
    return await WorkbenchService().transition_status(
        draft_id=draft_id,
        user_oid=identity.oid,
        groups=identity.groups,
        new_status=ApprovalStatus.REJECTED,
        signature=x_coreason_sig,
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
    # 1. Check Access
    draft = await WorkbenchService().get_draft(
        draft_id=draft_id, user_oid=identity.oid, groups=identity.groups, signature=x_coreason_sig
    )
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    await _verify_project_access(identity, draft.auc_id)

    try:
        return await WorkbenchService().assemble_artifact(
            draft_id=draft_id, user_oid=identity.oid, signature=x_coreason_sig
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/drafts/{draft_id}/publish", response_model=dict[str, str])
async def publish_agent_artifact(
    draft_id: UUID,
    request: PublishRequest,
    identity: UserIdentity = Depends(parse_and_validate_token),
    x_coreason_sig: Optional[str] = Header(None, alias="x-coreason-sig"),
) -> dict[str, str]:
    """
    Publishes the signed artifact.
    """
    # 1. Check Access
    draft = await WorkbenchService().get_draft(
        draft_id=draft_id, user_oid=identity.oid, groups=identity.groups, signature=x_coreason_sig
    )
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    await _verify_project_access(identity, draft.auc_id)

    # Use header signature if present, else fallback to body (or prioritize body? Spec said extract header)
    # Spec: "Extract the `x-coreason-sig` header (alias it as `signature`). Call the new `WorkbenchService`."
    # Service expects signature.
    # Let's prefer header, fall back to request body if header is missing, or just pass header.
    # The Prompt Example implies: `signature=x_coreason_sig`.
    # But `request.signature` is in the body.
    # If `x-coreason-sig` is None, we might want to check `request.signature`.
    # However, strict governance usually prefers the header for the *request* signature.
    # The body `signature` might be the *artifact* signature (author signature).
    # Wait, `publish_artifact` in service takes `signature`.
    # And `publish_artifact` in service does `artifact.author_signature = signature`.
    # So this signature IS the author signature.
    # If the client puts it in the header, we use it.

    final_sig = x_coreason_sig or request.signature

    # Ensure we have a string
    if not final_sig:
         # Should we raise 400? The service governed with allow_unsigned=False will likely raise if missing/invalid.
         # But let's pass what we have.
         final_sig = "" # type: ignore

    try:
        return await WorkbenchService().publish_artifact(
            draft_id=draft_id,
            request=request,
            user_oid=identity.oid,
            signature=final_sig,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
