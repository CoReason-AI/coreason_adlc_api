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

from coreason_veritas.governance import governed_execution
from fastapi import HTTPException, status

from coreason_adlc_api.auth.identity import map_groups_to_projects
from coreason_adlc_api.db import get_pool
from coreason_adlc_api.middleware.budget import check_budget_status
from coreason_adlc_api.middleware.pii import scrub_pii_recursive
from coreason_adlc_api.workbench.locking import refresh_lock
from coreason_adlc_api.workbench.schemas import (
    AgentArtifact,
    ApprovalStatus,
    DraftCreate,
    DraftResponse,
    DraftUpdate,
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


class WorkbenchService:
    """
    Governed Service for Workbench operations.
    Enforces GxP compliance via coreason-veritas.
    """

    async def _derive_roles(self, groups: list[UUID]) -> list[str]:
        """
        Derives user roles from their group memberships.
        """
        pool = get_pool()
        query = "SELECT role_name FROM identity.group_mappings WHERE sso_group_oid = ANY($1::uuid[])"
        rows = await pool.fetch(query, groups)
        return [r["role_name"] for r in rows]

    async def _verify_project_access(self, groups: list[UUID], auc_id: str) -> None:
        """
        Verifies that the user has access to the given project (AUC ID).
        """
        allowed_projects = await map_groups_to_projects(groups)
        if auc_id not in allowed_projects:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"User is not authorized to access project {auc_id}",
            )

    @governed_execution(user_id_arg="user_oid", allow_unsigned=True)  # type: ignore[misc]
    async def list_drafts(
        self, auc_id: str, user_oid: UUID, groups: list[UUID]
    ) -> list[DraftResponse]:
        """
        Returns list of drafts filterable by auc_id.
        """
        await self._verify_project_access(groups, auc_id)
        return await get_drafts(auc_id)

    @governed_execution(user_id_arg="user_oid", allow_unsigned=True)  # type: ignore[misc]
    async def create_draft(
        self, draft: DraftCreate, user_oid: UUID, groups: list[UUID], signature: str | None = None
    ) -> DraftResponse:
        """
        Creates a new agent draft.
        """
        await self._verify_project_access(groups, draft.auc_id)
        return await create_draft(draft, user_oid)

    @governed_execution(user_id_arg="user_oid", allow_unsigned=True)  # type: ignore[misc]
    async def get_draft(
        self, draft_id: UUID, user_oid: UUID, groups: list[UUID]
    ) -> DraftResponse:
        """
        Returns draft content and acquires lock.
        """
        roles = await self._derive_roles(groups)
        draft = await get_draft_by_id(draft_id, user_oid, roles)
        if not draft:
            raise HTTPException(status_code=404, detail="Draft not found")

        await self._verify_project_access(groups, draft.auc_id)
        return draft

    @governed_execution(user_id_arg="user_oid", allow_unsigned=True)  # type: ignore[misc]
    async def update_draft(
        self, draft_id: UUID, update: DraftUpdate, user_oid: UUID, groups: list[UUID]
    ) -> DraftResponse:
        """
        Updates draft content.
        """
        # Check access by fetching the draft briefly
        # (assumes no lock acquired if just for check, but get_draft_by_id checks lock)
        # We need to know auc_id to verify access.

        current_draft = await get_draft_by_id(draft_id, user_oid, [])
        if not current_draft:
            raise HTTPException(status_code=404, detail="Draft not found")

        await self._verify_project_access(groups, current_draft.auc_id)
        return await update_draft(draft_id, update, user_oid)

    @governed_execution(user_id_arg="user_oid", allow_unsigned=True)  # type: ignore[misc]
    async def heartbeat_lock(
        self, draft_id: UUID, user_oid: UUID, groups: list[UUID]
    ) -> dict[str, bool]:
        """
        Refreshes the lock expiry.
        """
        # Access control? The router didn't check project access explicitly for heartbeat, only token validation.
        # But probably good to check?
        # The original code:
        # async def heartbeat_lock(
        #    draft_id: UUID, identity: UserIdentity = Depends(parse_and_validate_token)
        # ) -> dict[str, bool]:
        #    await refresh_lock(draft_id, identity.oid)
        #    return {"success": True}
        # It didn't check project access. `refresh_lock` checks if user owns the lock.
        # So we just call refresh_lock.
        await refresh_lock(draft_id, user_oid)
        return {"success": True}

    @governed_execution(user_id_arg="user_oid", allow_unsigned=True)  # type: ignore[misc]
    async def validate_draft(
        self, draft: DraftCreate, user_oid: UUID, groups: list[UUID]
    ) -> ValidationResponse:
        """
        Stateless validation of a draft.
        """
        # Check project access? Original code didn't check access explicitly, just budget and PII.
        # But probably good to check if user can access the project they are validating for?
        # Original:
        # async def validate_draft(draft: DraftCreate, identity: UserIdentity = Depends(parse_and_validate_token))
        # It didn't call _verify_project_access.
        # I will leave it as is to match behavior, but wrapped in governance.

        issues = []

        # 1. Budget Check
        if not check_budget_status(user_oid):
            issues.append("Budget Limit Reached")

        # 2. PII Check
        try:
            scrubbed_content = scrub_pii_recursive(draft.oas_content)
            # Deep comparison
            if scrubbed_content != draft.oas_content:
                issues.append("PII Detected")
        except Exception:
            issues.append("PII Check Failed")

        return ValidationResponse(is_valid=(len(issues) == 0), issues=issues)

    @governed_execution(user_id_arg="user_oid", allow_unsigned=True)  # type: ignore[misc]
    async def submit_draft(
        self, draft_id: UUID, user_oid: UUID, groups: list[UUID]
    ) -> DraftResponse:
        """
        Submits a draft for approval.
        """
        current_draft = await get_draft_by_id(draft_id, user_oid, [])
        if not current_draft:
            raise HTTPException(status_code=404, detail="Draft not found")
        await self._verify_project_access(groups, current_draft.auc_id)
        return await transition_draft_status(draft_id, user_oid, ApprovalStatus.PENDING)

    @governed_execution(user_id_arg="user_oid", allow_unsigned=True)  # type: ignore[misc]
    async def approve_draft(
        self, draft_id: UUID, user_oid: UUID, groups: list[UUID]
    ) -> DraftResponse:
        """
        Approves a pending draft.
        """
        roles = await self._derive_roles(groups)
        if "MANAGER" not in roles:
            raise HTTPException(status_code=403, detail="Only managers can approve drafts")

        current_draft = await get_draft_by_id(draft_id, user_oid, [])
        if not current_draft:
            raise HTTPException(status_code=404, detail="Draft not found")
        await self._verify_project_access(groups, current_draft.auc_id)
        return await transition_draft_status(draft_id, user_oid, ApprovalStatus.APPROVED)

    @governed_execution(user_id_arg="user_oid", allow_unsigned=True)  # type: ignore[misc]
    async def reject_draft(
        self, draft_id: UUID, user_oid: UUID, groups: list[UUID]
    ) -> DraftResponse:
        """
        Rejects a pending draft.
        """
        roles = await self._derive_roles(groups)
        if "MANAGER" not in roles:
            raise HTTPException(status_code=403, detail="Only managers can reject drafts")

        current_draft = await get_draft_by_id(draft_id, user_oid, [])
        if not current_draft:
            raise HTTPException(status_code=404, detail="Draft not found")
        await self._verify_project_access(groups, current_draft.auc_id)
        return await transition_draft_status(draft_id, user_oid, ApprovalStatus.REJECTED)

    @governed_execution(user_id_arg="user_oid", allow_unsigned=True)  # type: ignore[misc]
    async def get_artifact_assembly(
        self, draft_id: UUID, user_oid: UUID, groups: list[UUID]
    ) -> AgentArtifact:
        """
        Returns the assembled AgentArtifact for an APPROVED draft.
        """
        current_draft = await get_draft_by_id(draft_id, user_oid, [])
        if not current_draft:
            raise HTTPException(status_code=404, detail="Draft not found")
        await self._verify_project_access(groups, current_draft.auc_id)

        try:
            return await assemble_artifact(draft_id, user_oid)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @governed_execution(user_id_arg="user_oid", allow_unsigned=False)  # type: ignore[misc]
    async def publish_artifact(
        self, draft_id: UUID, user_oid: UUID, groups: list[UUID], signature: str
    ) -> str:
        """
        Publishes the signed artifact.
        """
        current_draft = await get_draft_by_id(draft_id, user_oid, [])
        if not current_draft:
            raise HTTPException(status_code=404, detail="Draft not found")
        await self._verify_project_access(groups, current_draft.auc_id)

        try:
            return await publish_artifact(draft_id, signature, user_oid)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
