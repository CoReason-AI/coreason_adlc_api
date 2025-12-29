from typing import List, Optional
from uuid import UUID

from coreason_veritas import governed_execution  # type: ignore[misc]

from coreason_adlc_api.workbench import service
from coreason_adlc_api.workbench.schemas import (
    AgentArtifact,
    ApprovalStatus,
    DraftCreate,
    DraftResponse,
    DraftUpdate,
    PublishRequest,
    ValidationResponse,
)


class WorkbenchService:
    @governed_execution(  # type: ignore[misc]
        asset_id_arg="draft",
        signature_arg="signature",
        user_id_arg="user_oid",
        allow_unsigned=True,
    )
    async def create_draft(
        self, draft: DraftCreate, user_oid: UUID, signature: str | None = None
    ) -> DraftResponse:
        """
        Creates a new agent draft.
        Draft creation allows unsigned requests (Draft Mode).
        """
        return await service.create_draft(draft=draft, user_uuid=user_oid)

    @governed_execution(  # type: ignore[misc]
        asset_id_arg="draft_id",
        signature_arg="signature",
        user_id_arg="user_oid",
        allow_unsigned=False,
    )
    async def publish_artifact(
        self,
        draft_id: UUID,
        request: PublishRequest,
        user_oid: UUID,
        signature: str,
    ) -> dict[str, str]:
        """
        Publishes the signed artifact.
        Strict Mode: Requires a valid signature.
        """
        url = await service.publish_artifact(
            draft_id=draft_id, signature=signature, user_oid=user_oid
        )
        return {"url": url}

    # --- New Methods ---

    @governed_execution(  # type: ignore[misc]
        asset_id_arg="auc_id",
        signature_arg="signature",
        user_id_arg="user_oid",
        allow_unsigned=True,
    )
    async def list_drafts(
        self, auc_id: str, user_oid: UUID, signature: str | None = None
    ) -> List[DraftResponse]:
        """
        Lists drafts for a project.
        Read-only, allows unsigned.
        """
        return await service.get_drafts(auc_id=auc_id)

    @governed_execution(  # type: ignore[misc]
        asset_id_arg="draft_id",
        signature_arg="signature",
        user_id_arg="user_oid",
        allow_unsigned=True,
    )
    async def get_draft(
        self, draft_id: UUID, user_oid: UUID, groups: List[UUID], signature: str | None = None
    ) -> Optional[DraftResponse]:
        """
        Gets a single draft.
        Read-only, allows unsigned.
        Delegates role fetching to the identity module via the service or handled here?
        The original service.get_draft_by_id needed 'roles' list.
        The caller (Router) currently fetches roles.
        Wait, the instruction says:
        "Service layer methods require explicit `user_oid` (for audit) and `groups` (for RBAC) arguments..."
        So we should pass groups here, and map to roles, OR pass roles if the router does it.
        However, adhering to "Humble Router", the service should probably handle role mapping if possible,
        BUT `service.get_draft_by_id` takes `roles: List[str]`.

        Refactoring decision: To minimize changes to `service.py` (Constraint: Do not modify `service.py`),
        we must map groups to roles here or pass roles in.
        Given strict "Humble Router", the router just extracts `groups` from identity.
        So this Service (Governed) should map groups to roles.

        But `_get_user_roles` was in the router. I should move that logic here or helper.
        The instruction said: "Refactor the API... shifting from Router-Centric to Service-Centric".
        So I will implement role mapping in this service or a helper used by this service.
        """
        # Logic to map groups to roles is needed.
        # I will use a helper for this.
        # But wait, `service.py` functions are simple CRUD.
        # `get_draft_by_id` needs roles for locking logic.

        roles = await self._get_user_roles(groups)
        return await service.get_draft_by_id(draft_id=draft_id, user_uuid=user_oid, roles=roles)

    @governed_execution(  # type: ignore[misc]
        asset_id_arg="draft_id",
        signature_arg="signature",
        user_id_arg="user_oid",
        allow_unsigned=True,
    )
    async def update_draft(
        self, draft_id: UUID, update: DraftUpdate, user_oid: UUID, signature: str | None = None
    ) -> DraftResponse:
        """
        Updates a draft.
        """
        return await service.update_draft(draft_id=draft_id, update=update, user_uuid=user_oid)

    @governed_execution(  # type: ignore[misc]
        asset_id_arg="draft",
        signature_arg="signature",
        user_id_arg="user_oid",
        allow_unsigned=True,
    )
    async def validate_draft(
        self, draft: DraftCreate, user_oid: UUID, signature: str | None = None
    ) -> ValidationResponse:
        """
        Validates a draft (Budget + PII).
        """
        # Original router logic moved here:
        from coreason_adlc_api.middleware.budget import check_budget_status
        from coreason_adlc_api.middleware.pii import scrub_pii_recursive

        issues = []
        # 1. Budget Check
        if not check_budget_status(user_oid):
            issues.append("Budget Limit Reached")

        # 2. PII Check
        try:
            scrubbed_content = scrub_pii_recursive(draft.oas_content)
            if scrubbed_content != draft.oas_content:
                issues.append("PII Detected")
        except Exception:
             issues.append("PII Check Failed")

        return ValidationResponse(is_valid=(len(issues) == 0), issues=issues)

    @governed_execution(  # type: ignore[misc]
        asset_id_arg="draft_id",
        signature_arg="signature",
        user_id_arg="user_oid",
        allow_unsigned=True,
    )
    async def transition_status(
        self,
        draft_id: UUID,
        user_oid: UUID,
        groups: List[UUID],
        new_status: ApprovalStatus,
        signature: str | None = None
    ) -> DraftResponse:
        """
        Transitions draft status (Submit, Approve, Reject).
        Checks permissions (MANAGER role for Approve/Reject).
        """
        # Permission Check
        if new_status in (ApprovalStatus.APPROVED, ApprovalStatus.REJECTED):
             roles = await self._get_user_roles(groups)
             if "MANAGER" not in roles:
                 # We need to raise the same exception or similar
                 from fastapi import HTTPException, status
                 raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only managers can approve/reject drafts")

        return await service.transition_draft_status(draft_id=draft_id, user_uuid=user_oid, new_status=new_status)

    @governed_execution(  # type: ignore[misc]
        asset_id_arg="draft_id",
        signature_arg="signature",
        user_id_arg="user_oid",
        allow_unsigned=True,  # Assembly might be allowed unsigned if it's just generating the artifact?
                              # Spec says Publish is strict. Assemble is read-ish. Let's keep strictness low for now unless specified.
    )
    async def assemble_artifact(
        self, draft_id: UUID, user_oid: UUID, signature: str | None = None
    ) -> AgentArtifact:
        return await service.assemble_artifact(draft_id=draft_id, user_oid=user_oid)

    async def _get_user_roles(self, group_oids: List[UUID]) -> List[str]:
        """
        Helper to fetch roles. Duplicated from Router logic but placed here for Service-Centricity.
        """
        from coreason_adlc_api.db import get_pool
        pool = get_pool()
        query = "SELECT role_name FROM identity.group_mappings WHERE sso_group_oid = ANY($1::uuid[])"
        rows = await pool.fetch(query, group_oids)
        return [r["role_name"] for r in rows]
