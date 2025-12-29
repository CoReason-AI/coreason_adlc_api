# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

from typing import List, Optional
from uuid import UUID

from coreason_veritas import governed_execution
from fastapi import HTTPException, status

from coreason_adlc_api.auth.identity import map_groups_to_projects
from coreason_adlc_api.db import get_pool
from coreason_adlc_api.middleware.budget import check_budget_status
from coreason_adlc_api.middleware.pii import scrub_pii_recursive
from coreason_adlc_api.workbench import schemas, service
from coreason_adlc_api.workbench.locking import refresh_lock


class WorkbenchService:
    async def _derive_roles(self, groups: List[UUID]) -> List[str]:
        pool = get_pool()
        query = "SELECT role_name FROM identity.group_mappings WHERE sso_group_oid = ANY($1::uuid[])"
        rows = await pool.fetch(query, groups)
        return [r["role_name"] for r in rows]

    async def _verify_project_access(self, groups: List[UUID], auc_id: str) -> None:
        allowed_projects = await map_groups_to_projects(groups)
        if auc_id not in allowed_projects:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"User is not authorized to access project {auc_id}",
            )

    @governed_execution(  # type: ignore[misc]
        asset_id_arg="auc_id", user_id_arg="user_oid", signature_arg="signature", allow_unsigned=True
    )
    async def list_drafts(
        self, auc_id: str, user_oid: UUID, groups: List[UUID], signature: Optional[str] = None
    ) -> List[schemas.DraftResponse]:
        await self._verify_project_access(groups, auc_id)
        return await service.get_drafts(auc_id)

    @governed_execution(  # type: ignore[misc]
        asset_id_arg="draft", user_id_arg="user_oid", signature_arg="signature", allow_unsigned=True
    )
    async def create_draft(
        self, draft: schemas.DraftCreate, user_oid: UUID, groups: List[UUID], signature: Optional[str] = None
    ) -> schemas.DraftResponse:
        await self._verify_project_access(groups, draft.auc_id)
        return await service.create_draft(draft, user_oid)

    @governed_execution(  # type: ignore[misc]
        asset_id_arg="draft_id", user_id_arg="user_oid", signature_arg="signature", allow_unsigned=True
    )
    async def get_draft(
        self, draft_id: UUID, user_oid: UUID, groups: List[UUID], signature: Optional[str] = None
    ) -> schemas.DraftResponse:
        roles = await self._derive_roles(groups)
        draft = await service.get_draft_by_id(draft_id, user_oid, roles)
        if not draft:
            raise HTTPException(status_code=404, detail="Draft not found")
        await self._verify_project_access(groups, draft.auc_id)
        return draft

    @governed_execution(  # type: ignore[misc]
        asset_id_arg="draft_id", user_id_arg="user_oid", signature_arg="signature", allow_unsigned=True
    )
    async def update_draft(
        self,
        draft_id: UUID,
        update: schemas.DraftUpdate,
        user_oid: UUID,
        groups: List[UUID],
        signature: Optional[str] = None,
    ) -> schemas.DraftResponse:
        current_draft = await service.get_draft_by_id(draft_id, user_oid, [])
        if not current_draft:
            raise HTTPException(status_code=404, detail="Draft not found")
        await self._verify_project_access(groups, current_draft.auc_id)
        return await service.update_draft(draft_id, update, user_oid)

    @governed_execution(  # type: ignore[misc]
        asset_id_arg="draft_id", user_id_arg="user_oid", signature_arg="signature", allow_unsigned=True
    )
    async def lock_draft(
        self, draft_id: UUID, user_oid: UUID, groups: List[UUID], signature: Optional[str] = None
    ) -> dict[str, bool]:
        await refresh_lock(draft_id, user_oid)
        return {"success": True}

    @governed_execution(  # type: ignore[misc]
        asset_id_arg="draft", user_id_arg="user_oid", signature_arg="signature", allow_unsigned=True
    )
    async def validate_draft(
        self, draft: schemas.DraftCreate, user_oid: UUID, groups: List[UUID], signature: Optional[str] = None
    ) -> schemas.ValidationResponse:
        issues = []
        if not check_budget_status(user_oid):
            issues.append("Budget Limit Reached")

        try:
            scrubbed_content = scrub_pii_recursive(draft.oas_content)
            if scrubbed_content != draft.oas_content:
                issues.append("PII Detected")
        except Exception:
            issues.append("PII Check Failed")

        return schemas.ValidationResponse(is_valid=(len(issues) == 0), issues=issues)

    async def _get_draft_and_verify_access(
        self, draft_id: UUID, user_oid: UUID, groups: List[UUID]
    ) -> schemas.DraftResponse:
        draft = await service.get_draft_by_id(draft_id, user_oid, [])
        if not draft:
            raise HTTPException(status_code=404, detail="Draft not found")
        await self._verify_project_access(groups, draft.auc_id)
        return draft

    @governed_execution(  # type: ignore[misc]
        asset_id_arg="draft_id", user_id_arg="user_oid", signature_arg="signature", allow_unsigned=True
    )
    async def submit_draft(
        self, draft_id: UUID, user_oid: UUID, groups: List[UUID], signature: Optional[str] = None
    ) -> schemas.DraftResponse:
        await self._get_draft_and_verify_access(draft_id, user_oid, groups)
        return await service.transition_draft_status(draft_id, user_oid, schemas.ApprovalStatus.PENDING)

    @governed_execution(  # type: ignore[misc]
        asset_id_arg="draft_id", user_id_arg="user_oid", signature_arg="signature", allow_unsigned=True
    )
    async def approve_draft(
        self, draft_id: UUID, user_oid: UUID, groups: List[UUID], signature: Optional[str] = None
    ) -> schemas.DraftResponse:
        roles = await self._derive_roles(groups)
        if "MANAGER" not in roles:
            raise HTTPException(status_code=403, detail="Only managers can approve drafts")
        await self._get_draft_and_verify_access(draft_id, user_oid, groups)
        return await service.transition_draft_status(draft_id, user_oid, schemas.ApprovalStatus.APPROVED)

    @governed_execution(  # type: ignore[misc]
        asset_id_arg="draft_id", user_id_arg="user_oid", signature_arg="signature", allow_unsigned=True
    )
    async def reject_draft(
        self, draft_id: UUID, user_oid: UUID, groups: List[UUID], signature: Optional[str] = None
    ) -> schemas.DraftResponse:
        roles = await self._derive_roles(groups)
        if "MANAGER" not in roles:
            raise HTTPException(status_code=403, detail="Only managers can reject drafts")
        await self._get_draft_and_verify_access(draft_id, user_oid, groups)
        return await service.transition_draft_status(draft_id, user_oid, schemas.ApprovalStatus.REJECTED)

    @governed_execution(  # type: ignore[misc]
        asset_id_arg="draft_id", user_id_arg="user_oid", signature_arg="signature", allow_unsigned=True
    )
    async def assemble_artifact(
        self, draft_id: UUID, user_oid: UUID, groups: List[UUID], signature: Optional[str] = None
    ) -> schemas.AgentArtifact:
        await self._get_draft_and_verify_access(draft_id, user_oid, groups)
        try:
            return await service.assemble_artifact(draft_id, user_oid)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @governed_execution(  # type: ignore[misc]
        asset_id_arg="draft_id", user_id_arg="user_oid", signature_arg="signature", allow_unsigned=False
    )
    async def publish_artifact(
        self, draft_id: UUID, signature: str, user_oid: UUID, groups: List[UUID]
    ) -> dict[str, str]:
        await self._get_draft_and_verify_access(draft_id, user_oid, groups)
        try:
            url = await service.publish_artifact(draft_id, signature, user_oid)
            return {"url": url}
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
