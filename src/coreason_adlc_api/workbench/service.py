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
from datetime import datetime
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

    # Mypy correction: user.id -> user.oid
    @governed_execution(
        asset_id_arg="draft_in.project_id", signature_arg=None, user_id_arg="self.user.oid", allow_unsigned=True
    )  # type: ignore
    async def create_draft(self, draft_in: DraftCreate) -> DraftResponse:
        await self._check_access(draft_in.project_id)

        draft = DraftModel(
            project_id=draft_in.project_id,
            content=draft_in.content,
            created_by=self.user.oid,
            status=ApprovalStatus.DRAFT.value,
        )
        self.session.add(draft)
        await self.session.commit()
        await self.session.refresh(draft)
        return DraftResponse.model_validate(draft)

    async def get_draft(self, draft_id: str) -> DraftResponse:
        # Get draft to check project_id first? Or optimize query?
        query = select(DraftModel).where(DraftModel.id == uuid.UUID(draft_id))
        result = await self.session.exec(query)
        draft = result.one_or_none()

        if not draft:
            raise ResourceNotFoundError(f"Draft {draft_id} not found")

        await self._check_access(draft.project_id)
        return DraftResponse.model_validate(draft)

    @governed_execution(asset_id_arg="draft_id", signature_arg=None, user_id_arg="self.user.oid", allow_unsigned=True)  # type: ignore
    async def update_draft(self, draft_id: str, draft_in: DraftUpdate) -> DraftResponse:
        # 1. Load Draft
        query = select(DraftModel).where(DraftModel.id == uuid.UUID(draft_id))
        result = await self.session.exec(query)
        draft = result.one_or_none()

        if not draft:
            raise ResourceNotFoundError(f"Draft {draft_id} not found")

        # 2. Check Project Access
        await self._check_access(draft.project_id)

        # 3. Check Lock (Must be locked by user)
        # We call check_lock from manager
        await self.lock_manager.check_lock(draft_id)

        # 4. Check Status (Only DRAFT or REJECTED)
        if draft.status not in [ApprovalStatus.DRAFT.value, ApprovalStatus.REJECTED.value]:
            raise ComplianceViolationError("Cannot edit draft in current state")

        # 5. Update
        if draft_in.content:
            draft.content = draft_in.content

        draft.updated_at = datetime.utcnow()
        # Increment version? Usually on publish, but maybe minor version here.

        self.session.add(draft)
        await self.session.commit()
        await self.session.refresh(draft)
        return DraftResponse.model_validate(draft)

    @governed_execution(
        asset_id_arg="draft_id", signature_arg="publish_req.signature", user_id_arg="self.user.oid", allow_unsigned=False
    )  # type: ignore
    async def publish_artifact(self, draft_id: str, publish_req: PublishRequest) -> ArtifactResponse:
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
            version=str(draft.version),  # Or generate new
            content_hash=publish_req.content_hash,  # Verify?
            signature=publish_req.signature,
            published_by=self.user.oid,
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
        # TODO: Check if user is manager
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
        return DraftResponse.model_validate(draft)

    async def reject_draft(self, draft_id: str, comment: Optional[str]) -> DraftResponse:
        query = select(DraftModel).where(DraftModel.id == uuid.UUID(draft_id))
        result = await self.session.exec(query)
        draft = result.one_or_none()

        if not draft:
            raise ResourceNotFoundError(f"Draft {draft_id} not found")

        await self._check_access(draft.project_id)

        draft.status = ApprovalStatus.REJECTED.value
        # Save comment?
        self.session.add(draft)
        await self.session.commit()
        await self.session.refresh(draft)
        return DraftResponse.model_validate(draft)
