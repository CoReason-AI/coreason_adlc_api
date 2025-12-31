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

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import select, col

from coreason_adlc_api.auth.identity import UserIdentity, map_groups_to_projects, parse_and_validate_token
from coreason_adlc_api.db import async_session_factory
from coreason_adlc_api.db_models import GroupMapping
from coreason_adlc_api.middleware.budget import check_budget_status
from coreason_adlc_api.middleware.pii import scrub_pii_recursive
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
from coreason_adlc_api.workbench.service import (
    assemble_artifact,
    create_draft,
    get_draft_by_id,
    get_drafts,
    publish_artifact,
    transition_draft_status,
    update_draft,
)

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
async def list_drafts(auc_id: str, identity: UserIdentity = Depends(parse_and_validate_token)) -> list[DraftResponse]:
    """
    Returns list of drafts filterable by auc_id.
    """
    # Authorization: User must have access to auc_id
    await _verify_project_access(identity, auc_id)
    result = await get_drafts(auc_id)
    return result


@router.post("/drafts", response_model=DraftResponse, status_code=status.HTTP_201_CREATED)
async def create_new_draft(
    draft: DraftCreate, identity: UserIdentity = Depends(parse_and_validate_token)
) -> DraftResponse:
    """
    Creates a new agent draft.
    """
    await _verify_project_access(identity, draft.auc_id)
    return await create_draft(draft, identity.oid)


async def _get_user_roles(group_oids: list[UUID]) -> list[str]:
    # TODO: Refactor into identity module
    async with async_session_factory() as session:
        statement = select(GroupMapping.role_name).where(col(GroupMapping.sso_group_oid).in_(group_oids))
        results = await session.exec(statement)
        return list(results.all())


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

    # Verify Access to the draft's project
    await _verify_project_access(identity, draft.auc_id)

    return draft


@router.put("/drafts/{draft_id}", response_model=DraftResponse)
async def update_existing_draft(
    draft_id: UUID, update: DraftUpdate, identity: UserIdentity = Depends(parse_and_validate_token)
) -> DraftResponse:
    """
    Updates draft content.
    (Requires active Lock)
    """
    # Check access by fetching the draft briefly
    # Note: Optimization could be done here, but robustness first.
    current_draft = await get_draft_by_id(draft_id, identity.oid, [])
    if not current_draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    await _verify_project_access(identity, current_draft.auc_id)

    return await update_draft(draft_id, update, identity.oid)


@router.post("/drafts/{draft_id}/lock")
async def heartbeat_lock(draft_id: UUID, identity: UserIdentity = Depends(parse_and_validate_token)) -> dict[str, bool]:
    """
    Refreshes the lock expiry.
    """
    await refresh_lock(draft_id, identity.oid)
    return {"success": True}


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
    issues = []

    # 1. Budget Check
    if not await check_budget_status(identity.oid):
        issues.append("Budget Limit Reached")

    # 2. PII Check
    try:
        scrubbed_content = await scrub_pii_recursive(draft.oas_content)
        # Deep comparison
        if scrubbed_content != draft.oas_content:
            issues.append("PII Detected")
    except Exception:
        # Fail-closed if PII check fails (e.g. Analyzer missing handled in middleware, but other errors)
        issues.append("PII Check Failed")

    return ValidationResponse(is_valid=(len(issues) == 0), issues=issues)


# --- Approval Workflow Endpoints ---


async def _get_draft_and_verify_access(draft_id: UUID, identity: UserIdentity) -> DraftResponse:
    draft = await get_draft_by_id(draft_id, identity.oid, [])
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    await _verify_project_access(identity, draft.auc_id)
    return draft


@router.post("/drafts/{draft_id}/submit", response_model=DraftResponse)
async def submit_draft(draft_id: UUID, identity: UserIdentity = Depends(parse_and_validate_token)) -> DraftResponse:
    """
    Submits a draft for approval.
    Transitions: DRAFT/REJECTED -> PENDING
    """
    await _get_draft_and_verify_access(draft_id, identity)
    return await transition_draft_status(draft_id, identity.oid, ApprovalStatus.PENDING)


@router.post("/drafts/{draft_id}/approve", response_model=DraftResponse)
async def approve_draft(draft_id: UUID, identity: UserIdentity = Depends(parse_and_validate_token)) -> DraftResponse:
    """
    Approves a pending draft.
    Transitions: PENDING -> APPROVED
    Requires: MANAGER role
    """
    roles = await _get_user_roles(identity.groups)
    if "MANAGER" not in roles:
        raise HTTPException(status_code=403, detail="Only managers can approve drafts")

    await _get_draft_and_verify_access(draft_id, identity)
    return await transition_draft_status(draft_id, identity.oid, ApprovalStatus.APPROVED)


@router.post("/drafts/{draft_id}/reject", response_model=DraftResponse)
async def reject_draft(draft_id: UUID, identity: UserIdentity = Depends(parse_and_validate_token)) -> DraftResponse:
    """
    Rejects a pending draft.
    Transitions: PENDING -> REJECTED
    Requires: MANAGER role
    """
    roles = await _get_user_roles(identity.groups)
    if "MANAGER" not in roles:
        raise HTTPException(status_code=403, detail="Only managers can reject drafts")

    await _get_draft_and_verify_access(draft_id, identity)
    return await transition_draft_status(draft_id, identity.oid, ApprovalStatus.REJECTED)


# --- Artifact Assembly & Publication Endpoints ---


@router.get("/drafts/{draft_id}/assemble", response_model=AgentArtifact)
async def get_artifact_assembly(
    draft_id: UUID, identity: UserIdentity = Depends(parse_and_validate_token)
) -> AgentArtifact:
    """
    Returns the assembled AgentArtifact for an APPROVED draft.
    """
    await _get_draft_and_verify_access(draft_id, identity)
    try:
        return await assemble_artifact(draft_id, identity.oid)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/drafts/{draft_id}/publish", response_model=dict[str, str])
async def publish_agent_artifact(
    draft_id: UUID, request: PublishRequest, identity: UserIdentity = Depends(parse_and_validate_token)
) -> dict[str, str]:
    """
    Publishes the signed artifact.
    """
    await _get_draft_and_verify_access(draft_id, identity)
    try:
        url = await publish_artifact(draft_id, request.signature, identity.oid)
        return {"url": url}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
