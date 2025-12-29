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

from coreason_adlc_api.auth.identity import UserIdentity, map_groups_to_projects
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
from coreason_veritas import governed_execution
from fastapi import HTTPException, status


class WorkbenchService:
    """
    Service layer wrapped with GxP governance via Coreason Veritas.
    """

    async def _verify_project_access(self, identity: UserIdentity, auc_id: str) -> None:
        """
        Verifies that the user has access to the given project (AUC ID).
        """
        allowed_projects = await map_groups_to_projects(identity.groups)
        if auc_id not in allowed_projects:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"User is not authorized to access project {auc_id}",
            )

    async def _get_user_roles(self, group_oids: list[UUID]) -> list[str]:
        # TODO: Refactor into identity module
        pool = get_pool()
        query = "SELECT role_name FROM identity.group_mappings WHERE sso_group_oid = ANY($1::uuid[])"
        rows = await pool.fetch(query, group_oids)
        return [r["role_name"] for r in rows]

    async def _get_draft_and_verify_access(self, draft_id: UUID, identity: UserIdentity) -> DraftResponse:
        draft = await get_draft_by_id(draft_id, identity.oid, [])
        if not draft:
            raise HTTPException(status_code=404, detail="Draft not found")
        await self._verify_project_access(identity, draft.auc_id)
        return draft

    @governed_execution(
        allow_unsigned=True, asset_id_arg="auc_id", user_id_arg="user_oid", signature_arg="signature"
    )
    async def list_drafts(
        self, auc_id: str, user_oid: UUID, identity: UserIdentity, signature: Optional[str] = None
    ) -> list[DraftResponse]:
        """
        Returns list of drafts filterable by auc_id.
        """
        await self._verify_project_access(identity, auc_id)
        result = await get_drafts(auc_id)
        return result

    @governed_execution(
        allow_unsigned=True, asset_id_arg="draft", user_id_arg="user_oid", signature_arg="signature"
    )
    async def create_draft(
        self, draft: DraftCreate, user_oid: UUID, identity: UserIdentity, signature: Optional[str] = None
    ) -> DraftResponse:
        """
        Creates a new draft with governance wrapper.
        Allows unsigned execution (Genesis/Drafting phase).
        """
        await self._verify_project_access(identity, draft.auc_id)
        return await create_draft(draft, user_oid)

    @governed_execution(
        allow_unsigned=True, asset_id_arg="draft_id", user_id_arg="user_oid", signature_arg="signature"
    )
    async def get_draft(
        self, draft_id: UUID, user_oid: UUID, identity: UserIdentity, signature: Optional[str] = None
    ) -> DraftResponse:
        """
        Returns draft content and acquires lock.
        """
        roles = await self._get_user_roles(identity.groups)
        draft = await get_draft_by_id(draft_id, identity.oid, roles)
        if not draft:
            raise HTTPException(status_code=404, detail="Draft not found")

        await self._verify_project_access(identity, draft.auc_id)
        return draft

    @governed_execution(
        allow_unsigned=True, asset_id_arg="draft_id", user_id_arg="user_oid", signature_arg="signature"
    )
    async def update_draft(
        self,
        draft_id: UUID,
        update: DraftUpdate,
        user_oid: UUID,
        identity: UserIdentity,
        signature: Optional[str] = None,
    ) -> DraftResponse:
        """
        Updates draft content.
        """
        current_draft = await get_draft_by_id(draft_id, identity.oid, [])
        if not current_draft:
            raise HTTPException(status_code=404, detail="Draft not found")

        await self._verify_project_access(identity, current_draft.auc_id)
        return await update_draft(draft_id, update, identity.oid)

    @governed_execution(
        allow_unsigned=True, asset_id_arg="draft_id", user_id_arg="user_oid", signature_arg="signature"
    )
    async def refresh_lock(
        self, draft_id: UUID, user_oid: UUID, identity: UserIdentity, signature: Optional[str] = None
    ) -> dict[str, bool]:
        """
        Refreshes the lock expiry.
        """
        await refresh_lock(draft_id, identity.oid)
        return {"success": True}

    @governed_execution(
        allow_unsigned=True, asset_id_arg="draft", user_id_arg="user_oid", signature_arg="signature"
    )
    async def validate_draft(
        self, draft: DraftCreate, user_oid: UUID, identity: UserIdentity, signature: Optional[str] = None
    ) -> ValidationResponse:
        """
        Stateless validation of a draft.
        """
        issues = []
        if not check_budget_status(identity.oid):
            issues.append("Budget Limit Reached")

        try:
            scrubbed_content = scrub_pii_recursive(draft.oas_content)
            if scrubbed_content != draft.oas_content:
                issues.append("PII Detected")
        except Exception:
            issues.append("PII Check Failed")

        return ValidationResponse(is_valid=(len(issues) == 0), issues=issues)

    @governed_execution(
        allow_unsigned=True, asset_id_arg="draft_id", user_id_arg="user_oid", signature_arg="signature"
    )
    async def submit_draft(
        self, draft_id: UUID, user_oid: UUID, identity: UserIdentity, signature: Optional[str] = None
    ) -> DraftResponse:
        """
        Submits a draft for approval.
        """
        await self._get_draft_and_verify_access(draft_id, identity)
        return await transition_draft_status(draft_id, identity.oid, ApprovalStatus.PENDING)

    @governed_execution(
        allow_unsigned=True, asset_id_arg="draft_id", user_id_arg="user_oid", signature_arg="signature"
    )
    async def approve_draft(
        self, draft_id: UUID, user_oid: UUID, identity: UserIdentity, signature: Optional[str] = None
    ) -> DraftResponse:
        """
        Approves a pending draft.
        Requires: MANAGER role.
        """
        roles = await self._get_user_roles(identity.groups)
        if "MANAGER" not in roles:
            raise HTTPException(status_code=403, detail="Only managers can approve drafts")

        await self._get_draft_and_verify_access(draft_id, identity)
        return await transition_draft_status(draft_id, identity.oid, ApprovalStatus.APPROVED)

    @governed_execution(
        allow_unsigned=True, asset_id_arg="draft_id", user_id_arg="user_oid", signature_arg="signature"
    )
    async def reject_draft(
        self, draft_id: UUID, user_oid: UUID, identity: UserIdentity, signature: Optional[str] = None
    ) -> DraftResponse:
        """
        Rejects a pending draft.
        Requires: MANAGER role.
        """
        roles = await self._get_user_roles(identity.groups)
        if "MANAGER" not in roles:
            raise HTTPException(status_code=403, detail="Only managers can reject drafts")

        await self._get_draft_and_verify_access(draft_id, identity)
        return await transition_draft_status(draft_id, identity.oid, ApprovalStatus.REJECTED)

    @governed_execution(
        allow_unsigned=True, asset_id_arg="draft_id", user_id_arg="user_oid", signature_arg="signature"
    )
    async def assemble_artifact(
        self, draft_id: UUID, user_oid: UUID, identity: UserIdentity, signature: Optional[str] = None
    ) -> AgentArtifact:
        """
        Returns the assembled AgentArtifact for an APPROVED draft.
        """
        await self._get_draft_and_verify_access(draft_id, identity)
        try:
            return await assemble_artifact(draft_id, identity.oid)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @governed_execution(
        allow_unsigned=False, asset_id_arg="draft_id", user_id_arg="user_oid", signature_arg="signature"
    )
    async def publish_artifact(
        self,
        draft_id: UUID,
        request: PublishRequest,
        user_oid: UUID,
        identity: UserIdentity,
        signature: Optional[str],
    ) -> dict[str, str]:
        """
        Publishes an artifact with strict governance.
        Requires valid signature.
        """
        await self._get_draft_and_verify_access(draft_id, identity)

        if signature is None:
            raise ValueError("Signature is required for publishing artifact")

        try:
            url = await publish_artifact(draft_id, signature, user_oid)
            return {"url": url}
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
