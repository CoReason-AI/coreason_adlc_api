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
from typing import List, Optional, cast

from fastapi import HTTPException, status
from loguru import logger

from coreason_veritas import governed_execution

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
    PublishRequest,
    ValidationResponse,
)
from coreason_adlc_api.workbench.service import (
    assemble_artifact,
    create_draft,
    get_draft_by_id,
    get_drafts,
    publish_artifact as service_publish_artifact,
    transition_draft_status,
    update_draft,
)


class WorkbenchService:
    """
    Service layer for Workbench operations, enforcing governance and compliance.
    """

    async def _verify_project_access(self, groups: List[UUID], auc_id: str) -> None:
        """
        Verifies that the user has access to the given project (AUC ID).
        """
        allowed_projects = await map_groups_to_projects(groups)
        if auc_id not in allowed_projects:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"User is not authorized to access project {auc_id}",
            )

    async def _get_user_roles(self, group_oids: List[UUID]) -> List[str]:
        # TODO: Refactor into identity module
        pool = get_pool()
        query = "SELECT role_name FROM identity.group_mappings WHERE sso_group_oid = ANY($1::uuid[])"
        rows = await pool.fetch(query, group_oids)
        return [r["role_name"] for r in rows]

    async def _get_draft_and_verify_access(self, draft_id: UUID, user_oid: UUID, groups: List[UUID]) -> DraftResponse:
        draft = await get_draft_by_id(draft_id, user_oid, [])
        if not draft:
            raise HTTPException(status_code=404, detail="Draft not found")
        await self._verify_project_access(groups, draft.auc_id)
        return draft

    @governed_execution(asset_id_arg="auc_id", signature_arg="signature", user_id_arg="user_oid", allow_unsigned=True)
    async def list_drafts(
        self, auc_id: str, user_oid: UUID, groups: List[UUID], signature: Optional[str] = None
    ) -> List[DraftResponse]:
        """
        Returns list of drafts filterable by auc_id.
        """
        await self._verify_project_access(groups, auc_id)
        result = await get_drafts(auc_id)
        return result

    @governed_execution(asset_id_arg="draft", signature_arg="signature", user_id_arg="user_oid", allow_unsigned=True)
    async def create_new_draft(
        self, draft: DraftCreate, user_oid: UUID, groups: List[UUID], signature: Optional[str] = None
    ) -> DraftResponse:
        """
        Creates a new agent draft.
        """
        await self._verify_project_access(groups, draft.auc_id)
        return await create_draft(draft, user_oid)

    @governed_execution(asset_id_arg="draft_id", signature_arg="signature", user_id_arg="user_oid", allow_unsigned=True)
    async def get_draft(
        self, draft_id: UUID, user_oid: UUID, groups: List[UUID], signature: Optional[str] = None
    ) -> DraftResponse:
        """
        Returns draft content and acquires lock.
        """
        roles = await self._get_user_roles(groups)

        draft = await get_draft_by_id(draft_id, user_oid, roles)
        if not draft:
            raise HTTPException(status_code=404, detail="Draft not found")

        await self._verify_project_access(groups, draft.auc_id)

        return draft

    @governed_execution(asset_id_arg="draft_id", signature_arg="signature", user_id_arg="user_oid", allow_unsigned=True)
    async def update_existing_draft(
        self, draft_id: UUID, update: DraftUpdate, user_oid: UUID, groups: List[UUID], signature: Optional[str] = None
    ) -> DraftResponse:
        """
        Updates draft content.
        (Requires active Lock)
        """
        # Check access by fetching the draft briefly
        current_draft = await get_draft_by_id(draft_id, user_oid, [])
        if not current_draft:
            raise HTTPException(status_code=404, detail="Draft not found")

        await self._verify_project_access(groups, current_draft.auc_id)

        return await update_draft(draft_id, update, user_oid)

    @governed_execution(asset_id_arg="draft_id", signature_arg="signature", user_id_arg="user_oid", allow_unsigned=True)
    async def heartbeat_lock(
        self, draft_id: UUID, user_oid: UUID, groups: List[UUID], signature: Optional[str] = None
    ) -> dict[str, bool]:
        """
        Refreshes the lock expiry.
        """
        # Lock refresh doesn't strictly check project access in router previously,
        # but typically you should have access.
        # But refresh_lock checks ownership/lock holding.
        # We will keep it minimal as per router logic, but wrapped.
        await refresh_lock(draft_id, user_oid)
        return {"success": True}

    @governed_execution(asset_id_arg="draft", signature_arg="signature", user_id_arg="user_oid", allow_unsigned=True)
    async def validate_draft(
        self, draft: DraftCreate, user_oid: UUID, groups: List[UUID], signature: Optional[str] = None
    ) -> ValidationResponse:
        """
        Stateless validation of a draft.
        """
        # Does not persist, but useful to audit.
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

    @governed_execution(asset_id_arg="draft_id", signature_arg="signature", user_id_arg="user_oid", allow_unsigned=True)
    async def submit_draft(
        self, draft_id: UUID, user_oid: UUID, groups: List[UUID], signature: Optional[str] = None
    ) -> DraftResponse:
        """
        Submits a draft for approval.
        """
        await self._get_draft_and_verify_access(draft_id, user_oid, groups)
        return await transition_draft_status(draft_id, user_oid, ApprovalStatus.PENDING)

    @governed_execution(asset_id_arg="draft_id", signature_arg="signature", user_id_arg="user_oid", allow_unsigned=True)
    async def approve_draft(
        self, draft_id: UUID, user_oid: UUID, groups: List[UUID], signature: Optional[str] = None
    ) -> DraftResponse:
        """
        Approves a pending draft.
        """
        roles = await self._get_user_roles(groups)
        if "MANAGER" not in roles:
            raise HTTPException(status_code=403, detail="Only managers can approve drafts")

        await self._get_draft_and_verify_access(draft_id, user_oid, groups)
        return await transition_draft_status(draft_id, user_oid, ApprovalStatus.APPROVED)

    @governed_execution(asset_id_arg="draft_id", signature_arg="signature", user_id_arg="user_oid", allow_unsigned=True)
    async def reject_draft(
        self, draft_id: UUID, user_oid: UUID, groups: List[UUID], signature: Optional[str] = None
    ) -> DraftResponse:
        """
        Rejects a pending draft.
        """
        roles = await self._get_user_roles(groups)
        if "MANAGER" not in roles:
            raise HTTPException(status_code=403, detail="Only managers can reject drafts")

        await self._get_draft_and_verify_access(draft_id, user_oid, groups)
        return await transition_draft_status(draft_id, user_oid, ApprovalStatus.REJECTED)

    @governed_execution(asset_id_arg="draft_id", signature_arg="signature", user_id_arg="user_oid", allow_unsigned=True)
    async def get_artifact_assembly(
        self, draft_id: UUID, user_oid: UUID, groups: List[UUID], signature: Optional[str] = None
    ) -> AgentArtifact:
        """
        Returns the assembled AgentArtifact for an APPROVED draft.
        """
        await self._get_draft_and_verify_access(draft_id, user_oid, groups)
        try:
            return await assemble_artifact(draft_id, user_oid)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @governed_execution(asset_id_arg="draft_id", signature_arg="signature", user_id_arg="user_oid", allow_unsigned=False)
    async def publish_artifact(
        self, draft_id: UUID, request: PublishRequest, signature: str, user_oid: UUID, groups: List[UUID]
    ) -> dict[str, str]:
        """
        Publishes the signed artifact.
        """
        await self._get_draft_and_verify_access(draft_id, user_oid, groups)
        try:
            # Service expects signature.
            # Note: service_publish_artifact (from service.py) requires (draft_id, signature, user_oid)
            url = await service_publish_artifact(draft_id, signature, user_oid)
            return {"url": url}
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
