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
import uuid
from datetime import datetime, timedelta
from typing import Optional

from coreason_veritas import governed_execution
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from coreason_adlc_api.auth.identity import UserIdentity, map_groups_to_projects
from coreason_adlc_api.db_models import ArtifactModel, DraftModel
from coreason_adlc_api.exceptions import AccessDeniedError, ComplianceViolationError, ResourceNotFoundError
from coreason_adlc_api.workbench.locking import DraftLockManager
from coreason_adlc_api.workbench.schemas import (
    ApprovalStatus,
    ArtifactResponse,
    DraftCreate,
    DraftResponse,
    DraftUpdate,
    PublishRequest,
)

logger = logging.getLogger(__name__)


class WorkbenchService:
    def __init__(self, session: AsyncSession, user: UserIdentity):
        self.session = session
        self.user = user
        self.lock_manager = DraftLockManager(session, user)

    async def _check_access(self, project_id: str) -> None:
        allowed = await map_groups_to_projects(self.user, self.session)
        if project_id not in allowed:
            raise AccessDeniedError(f"Access denied to project {project_id}")

    @governed_execution(asset_id_arg="project_id", signature_arg=None, user_id_arg="user_id", allow_unsigned=True)  # type: ignore
    async def create_draft(self, draft_in: DraftCreate, project_id: str, user_id: str) -> DraftResponse:
        """
        Creates a new draft.
        project_id and user_id are passed explicitly for governance.
        """
        if draft_in.auc_id != project_id:
            raise ValueError("Project ID mismatch")

        await self._check_access(project_id)

        # Force recompile - Pack title and oas_content into DB content field
        db_content = {"title": draft_in.title, "oas_content": draft_in.oas_content, "runtime_env": draft_in.runtime_env}

        draft = DraftModel(
            project_id=project_id,
            content=db_content,
            created_by=uuid.UUID(user_id),
            status=ApprovalStatus.DRAFT.value,
        )
        self.session.add(draft)
        await self.session.commit()
        await self.session.refresh(draft)
        return self._map_to_response(draft)

    async def get_draft(self, draft_id: str) -> DraftResponse:
        query = select(DraftModel).where(DraftModel.id == uuid.UUID(draft_id))
        result = await self.session.exec(query)
        draft = result.one_or_none()

        if not draft:
            raise ResourceNotFoundError(f"Draft {draft_id} not found")

        await self._check_access(draft.project_id)
        return self._map_to_response(draft)

    @governed_execution(asset_id_arg="draft_id", signature_arg=None, user_id_arg="user_id", allow_unsigned=True)  # type: ignore
    async def update_draft(self, draft_id: str, draft_in: DraftUpdate, user_id: str) -> DraftResponse:
        query = select(DraftModel).where(DraftModel.id == uuid.UUID(draft_id))
        result = await self.session.exec(query)
        draft = result.one_or_none()

        if not draft:
            raise ResourceNotFoundError(f"Draft {draft_id} not found")

        await self._check_access(draft.project_id)
        await self.lock_manager.check_lock(draft_id)

        if draft.status not in [ApprovalStatus.DRAFT.value, ApprovalStatus.REJECTED.value]:
            raise ComplianceViolationError("Cannot edit draft in current state")

        # Update content
        current_content = draft.content.copy() if draft.content else {}
        if draft_in.title:
            current_content["title"] = draft_in.title
        if draft_in.oas_content:
            current_content["oas_content"] = draft_in.oas_content
        if draft_in.runtime_env:
            current_content["runtime_env"] = draft_in.runtime_env

        draft.content = current_content
        draft.updated_at = datetime.utcnow()

        self.session.add(draft)
        await self.session.commit()
        await self.session.refresh(draft)
        return self._map_to_response(draft)

    @governed_execution(
        asset_id_arg="draft_id",
        signature_arg="publish_req.signature",
        user_id_arg="user_id",
        allow_unsigned=False,
    )  # type: ignore
    async def publish_artifact(self, draft_id: str, publish_req: PublishRequest, user_id: str) -> ArtifactResponse:
        query = select(DraftModel).where(DraftModel.id == uuid.UUID(draft_id))
        result = await self.session.exec(query)
        draft = result.one_or_none()

        if not draft:
            raise ResourceNotFoundError(f"Draft {draft_id} not found")

        await self._check_access(draft.project_id)

        if draft.status != ApprovalStatus.APPROVED.value:
            raise ComplianceViolationError("Draft must be APPROVED before publishing")

        # Create Artifact
        artifact = ArtifactModel(
            project_id=draft.project_id,
            draft_id=draft.id,
            version=str(draft.version),
            content_hash=publish_req.content_hash,
            signature=publish_req.signature,
            published_by=uuid.UUID(user_id),
        )

        self.session.add(artifact)
        await self.session.commit()
        await self.session.refresh(artifact)

        return ArtifactResponse(
            id=artifact.id,
            project_id=artifact.project_id,
            version=str(artifact.version),
            content_hash=artifact.content_hash,
            signature=artifact.signature,
            created_at=artifact.published_at,
            created_by=artifact.published_by,
        )

    async def approve_draft(self, draft_id: str) -> DraftResponse:
        query = select(DraftModel).where(DraftModel.id == uuid.UUID(draft_id))
        result = await self.session.exec(query)
        draft = result.one_or_none()

        if not draft:
            raise ResourceNotFoundError(f"Draft {draft_id} not found")

        await self._check_access(draft.project_id)

        draft.status = ApprovalStatus.APPROVED.value
        self.session.add(draft)
        await self.session.commit()
        await self.session.refresh(draft)
        return self._map_to_response(draft)

    async def reject_draft(self, draft_id: str, comment: Optional[str]) -> DraftResponse:
        query = select(DraftModel).where(DraftModel.id == uuid.UUID(draft_id))
        result = await self.session.exec(query)
        draft = result.one_or_none()

        if not draft:
            raise ResourceNotFoundError(f"Draft {draft_id} not found")

        await self._check_access(draft.project_id)

        draft.status = ApprovalStatus.REJECTED.value
        self.session.add(draft)
        await self.session.commit()
        await self.session.refresh(draft)
        return self._map_to_response(draft)

    def _map_to_response(self, draft: DraftModel) -> DraftResponse:
        """Helper to map internal DB model to API Schema."""
        content = draft.content or {}

        # Calculate lock expiry if locked
        lock_expiry = None
        if draft.locked_at:
            lock_expiry = draft.locked_at + timedelta(minutes=30)  # Hardcoded timeout from locking.py

        return DraftResponse(
            draft_id=draft.id,
            user_uuid=draft.created_by,
            auc_id=draft.project_id,
            title=content.get("title", "Untitled"),
            oas_content=content.get("oas_content", {}),
            runtime_env=content.get("runtime_env"),
            status=ApprovalStatus(draft.status),
            locked_by_user=draft.locked_by,
            lock_expiry=lock_expiry,
            created_at=draft.created_at,
            updated_at=draft.updated_at,
            version=draft.version,
        )
