# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from coreason_adlc_api.workbench.schemas import (
    ApprovalStatus,
    DraftCreate,
    DraftResponse,
    DraftUpdate,
    PublishRequest,
)
from coreason_adlc_api.workbench.service_governed import WorkbenchService


@pytest.fixture
def mock_pool() -> AsyncGenerator[AsyncMock, None]:  # type: ignore[misc]
    pool = AsyncMock()
    pool.fetchrow = AsyncMock()
    pool.fetch = AsyncMock()

    # Patch get_pool in all places it might be used/imported
    with (
        patch("coreason_adlc_api.db.get_pool", return_value=pool),
        patch("coreason_adlc_api.auth.identity.get_pool", return_value=pool),
        patch("coreason_adlc_api.workbench.service_governed.get_pool", return_value=pool),
    ):
        yield pool


@pytest.fixture
def service() -> WorkbenchService:
    return WorkbenchService()


@pytest.mark.asyncio
async def test_verify_project_access_allowed(service: WorkbenchService, mock_pool: AsyncMock) -> None:
    groups = [uuid.uuid4()]
    auc_id = "project-alpha"
    # map_groups_to_projects calls pool.fetch
    mock_pool.fetch.return_value = [{"auc_id": auc_id}]

    await service._verify_project_access(groups, auc_id)
    # map_groups_to_projects is called
    mock_pool.fetch.assert_called_once()


@pytest.mark.asyncio
async def test_verify_project_access_denied(service: WorkbenchService, mock_pool: AsyncMock) -> None:
    groups = [uuid.uuid4()]
    auc_id = "project-beta"
    mock_pool.fetch.return_value = [{"auc_id": "project-alpha"}]

    with pytest.raises(HTTPException) as exc:
        await service._verify_project_access(groups, auc_id)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_get_user_roles(service: WorkbenchService, mock_pool: AsyncMock) -> None:
    groups = [uuid.uuid4()]
    mock_pool.fetch.return_value = [{"role_name": "MANAGER"}]

    roles = await service._get_user_roles(groups)
    assert roles == ["MANAGER"]


@pytest.mark.asyncio
async def test_get_draft_and_verify_access_success(service: WorkbenchService) -> None:
    draft_id = uuid.uuid4()
    user_oid = uuid.uuid4()
    groups = [uuid.uuid4()]
    mock_draft = DraftResponse(
        draft_id=draft_id,
        user_uuid=user_oid,
        auc_id="project-alpha",
        title="Test",
        oas_content={},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    with (
        patch("coreason_adlc_api.workbench.service_governed.get_draft_by_id", new_callable=AsyncMock) as mock_get,
        patch.object(service, "_verify_project_access", new_callable=AsyncMock) as mock_access,
    ):
        mock_get.return_value = mock_draft
        res = await service._get_draft_and_verify_access(draft_id, user_oid, groups)
        assert res == mock_draft
        mock_access.assert_awaited_once_with(groups, "project-alpha")


@pytest.mark.asyncio
async def test_get_draft_and_verify_access_not_found(service: WorkbenchService) -> None:
    with patch("coreason_adlc_api.workbench.service_governed.get_draft_by_id", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = None
        with pytest.raises(HTTPException) as exc:
            await service._get_draft_and_verify_access(uuid.uuid4(), uuid.uuid4(), [])
        assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_list_drafts(service: WorkbenchService) -> None:
    auc_id = "project-alpha"
    user_oid = uuid.uuid4()
    groups = [uuid.uuid4()]

    with (
        patch.object(service, "_verify_project_access", new_callable=AsyncMock) as mock_access,
        patch("coreason_adlc_api.workbench.service_governed.get_drafts", new_callable=AsyncMock) as mock_get_drafts,
    ):
        mock_get_drafts.return_value = []
        result = await service.list_drafts(auc_id=auc_id, user_oid=user_oid, groups=groups)
        assert result == []
        mock_access.assert_awaited_once_with(groups, auc_id)
        mock_get_drafts.assert_awaited_once_with(auc_id)


@pytest.mark.asyncio
async def test_create_new_draft(service: WorkbenchService) -> None:
    user_oid = uuid.uuid4()
    groups = [uuid.uuid4()]
    draft = DraftCreate(auc_id="project-alpha", title="Test", oas_content={})

    with (
        patch.object(service, "_verify_project_access", new_callable=AsyncMock) as mock_access,
        patch("coreason_adlc_api.workbench.service_governed.create_draft", new_callable=AsyncMock) as mock_create,
    ):
        await service.create_new_draft(draft=draft, user_oid=user_oid, groups=groups)
        mock_access.assert_awaited_once_with(groups, draft.auc_id)
        mock_create.assert_awaited_once_with(draft, user_oid)


@pytest.mark.asyncio
async def test_get_draft_success(service: WorkbenchService) -> None:
    draft_id = uuid.uuid4()
    user_oid = uuid.uuid4()
    groups = [uuid.uuid4()]
    mock_draft = DraftResponse(
        draft_id=draft_id,
        user_uuid=user_oid,
        auc_id="project-alpha",
        title="Test",
        oas_content={},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    with (
        patch.object(service, "_get_user_roles", new_callable=AsyncMock) as mock_roles,
        patch("coreason_adlc_api.workbench.service_governed.get_draft_by_id", new_callable=AsyncMock) as mock_get,
        patch.object(service, "_verify_project_access", new_callable=AsyncMock) as mock_access,
    ):
        mock_roles.return_value = ["EDITOR"]
        mock_get.return_value = mock_draft

        res = await service.get_draft(draft_id=draft_id, user_oid=user_oid, groups=groups)
        assert res == mock_draft
        mock_access.assert_awaited_once_with(groups, "project-alpha")


@pytest.mark.asyncio
async def test_get_draft_not_found(service: WorkbenchService) -> None:
    with (
        patch.object(service, "_get_user_roles", new_callable=AsyncMock),
        patch("coreason_adlc_api.workbench.service_governed.get_draft_by_id", new_callable=AsyncMock) as mock_get,
    ):
        mock_get.return_value = None
        with pytest.raises(HTTPException) as exc:
            await service.get_draft(draft_id=uuid.uuid4(), user_oid=uuid.uuid4(), groups=[])
        assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_update_existing_draft(service: WorkbenchService) -> None:
    draft_id = uuid.uuid4()
    user_oid = uuid.uuid4()
    groups = [uuid.uuid4()]
    update = DraftUpdate(title="New")
    mock_draft = DraftResponse(
        draft_id=draft_id,
        user_uuid=user_oid,
        auc_id="project-alpha",
        title="Test",
        oas_content={},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    with (
        patch("coreason_adlc_api.workbench.service_governed.get_draft_by_id", new_callable=AsyncMock) as mock_get,
        patch.object(service, "_verify_project_access", new_callable=AsyncMock) as mock_access,
        patch("coreason_adlc_api.workbench.service_governed.update_draft", new_callable=AsyncMock) as mock_update,
    ):
        mock_get.return_value = mock_draft
        await service.update_existing_draft(draft_id=draft_id, update=update, user_oid=user_oid, groups=groups)
        mock_access.assert_awaited_once_with(groups, "project-alpha")
        mock_update.assert_awaited_once_with(draft_id, update, user_oid)


@pytest.mark.asyncio
async def test_update_existing_draft_not_found(service: WorkbenchService) -> None:
    with patch("coreason_adlc_api.workbench.service_governed.get_draft_by_id", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = None
        with pytest.raises(HTTPException) as exc:
            await service.update_existing_draft(
                draft_id=uuid.uuid4(), update=DraftUpdate(), user_oid=uuid.uuid4(), groups=[]
            )
        assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_heartbeat_lock(service: WorkbenchService) -> None:
    with patch("coreason_adlc_api.workbench.service_governed.refresh_lock", new_callable=AsyncMock) as mock_refresh:
        res = await service.heartbeat_lock(draft_id=uuid.uuid4(), user_oid=uuid.uuid4(), groups=[])
        assert res["success"] is True
        mock_refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_validate_draft(service: WorkbenchService) -> None:
    draft = DraftCreate(auc_id="p1", title="t", oas_content={})
    user_id = uuid.uuid4()

    with (
        patch("coreason_adlc_api.workbench.service_governed.check_budget_status", return_value=True),
        patch("coreason_adlc_api.workbench.service_governed.scrub_pii_recursive", return_value={}),
    ):
        res = await service.validate_draft(draft=draft, user_oid=user_id, groups=[])
        assert res.is_valid is True


@pytest.mark.asyncio
async def test_validate_draft_issues(service: WorkbenchService) -> None:
    draft = DraftCreate(auc_id="p1", title="t", oas_content={"a": 1})
    user_id = uuid.uuid4()

    with (
        patch("coreason_adlc_api.workbench.service_governed.check_budget_status", return_value=False),
        patch("coreason_adlc_api.workbench.service_governed.scrub_pii_recursive", side_effect=Exception("PII")),
    ):
        res = await service.validate_draft(draft=draft, user_oid=user_id, groups=[])
        assert res.is_valid is False
        assert "Budget Limit Reached" in res.issues
        assert "PII Check Failed" in res.issues


@pytest.mark.asyncio
async def test_validate_draft_pii_detected(service: WorkbenchService) -> None:
    draft = DraftCreate(auc_id="p1", title="t", oas_content={"a": "secret"})
    user_id = uuid.uuid4()

    with (
        patch("coreason_adlc_api.workbench.service_governed.check_budget_status", return_value=True),
        patch(
            "coreason_adlc_api.workbench.service_governed.scrub_pii_recursive", return_value={"a": "REDACTED"}
        ),  # Changed content
    ):
        res = await service.validate_draft(draft=draft, user_oid=user_id, groups=[])
        assert res.is_valid is False
        assert "PII Detected" in res.issues


@pytest.mark.asyncio
async def test_submit_draft(service: WorkbenchService) -> None:
    draft_id = uuid.uuid4()
    user_oid = uuid.uuid4()
    groups = [uuid.uuid4()]

    with (
        patch.object(service, "_get_draft_and_verify_access", new_callable=AsyncMock),
        patch(
            "coreason_adlc_api.workbench.service_governed.transition_draft_status", new_callable=AsyncMock
        ) as mock_trans,
    ):
        await service.submit_draft(draft_id=draft_id, user_oid=user_oid, groups=groups)
        mock_trans.assert_awaited_once_with(draft_id, user_oid, ApprovalStatus.PENDING)


@pytest.mark.asyncio
async def test_approve_draft_manager(service: WorkbenchService) -> None:
    draft_id = uuid.uuid4()
    user_oid = uuid.uuid4()
    groups = [uuid.uuid4()]

    with (
        patch.object(service, "_get_user_roles", new_callable=AsyncMock) as mock_roles,
        patch.object(service, "_get_draft_and_verify_access", new_callable=AsyncMock),
        patch(
            "coreason_adlc_api.workbench.service_governed.transition_draft_status", new_callable=AsyncMock
        ) as mock_trans,
    ):
        mock_roles.return_value = ["MANAGER"]
        await service.approve_draft(draft_id=draft_id, user_oid=user_oid, groups=groups)
        mock_trans.assert_awaited_once_with(draft_id, user_oid, ApprovalStatus.APPROVED)


@pytest.mark.asyncio
async def test_approve_draft_not_manager(service: WorkbenchService) -> None:
    with patch.object(service, "_get_user_roles", new_callable=AsyncMock) as mock_roles:
        mock_roles.return_value = ["EDITOR"]
        with pytest.raises(HTTPException) as exc:
            await service.approve_draft(draft_id=uuid.uuid4(), user_oid=uuid.uuid4(), groups=[])
        assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_reject_draft_manager(service: WorkbenchService) -> None:
    draft_id = uuid.uuid4()
    user_oid = uuid.uuid4()
    groups = [uuid.uuid4()]

    with (
        patch.object(service, "_get_user_roles", new_callable=AsyncMock) as mock_roles,
        patch.object(service, "_get_draft_and_verify_access", new_callable=AsyncMock),
        patch(
            "coreason_adlc_api.workbench.service_governed.transition_draft_status", new_callable=AsyncMock
        ) as mock_trans,
    ):
        mock_roles.return_value = ["MANAGER"]
        await service.reject_draft(draft_id=draft_id, user_oid=user_oid, groups=groups)
        mock_trans.assert_awaited_once_with(draft_id, user_oid, ApprovalStatus.REJECTED)


@pytest.mark.asyncio
async def test_reject_draft_not_manager(service: WorkbenchService) -> None:
    with patch.object(service, "_get_user_roles", new_callable=AsyncMock) as mock_roles:
        mock_roles.return_value = ["EDITOR"]
        with pytest.raises(HTTPException) as exc:
            await service.reject_draft(draft_id=uuid.uuid4(), user_oid=uuid.uuid4(), groups=[])
        assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_get_artifact_assembly(service: WorkbenchService) -> None:
    draft_id = uuid.uuid4()
    user_oid = uuid.uuid4()
    groups = [uuid.uuid4()]

    with (
        patch.object(service, "_get_draft_and_verify_access", new_callable=AsyncMock),
        patch(
            "coreason_adlc_api.workbench.service_governed.assemble_artifact", new_callable=AsyncMock
        ) as mock_assemble,
    ):
        await service.get_artifact_assembly(draft_id=draft_id, user_oid=user_oid, groups=groups)
        mock_assemble.assert_awaited_once_with(draft_id, user_oid)


@pytest.mark.asyncio
async def test_get_artifact_assembly_error(service: WorkbenchService) -> None:
    with (
        patch.object(service, "_get_draft_and_verify_access", new_callable=AsyncMock),
        patch("coreason_adlc_api.workbench.service_governed.assemble_artifact", side_effect=ValueError("Bad draft")),
    ):
        with pytest.raises(HTTPException) as exc:
            await service.get_artifact_assembly(draft_id=uuid.uuid4(), user_oid=uuid.uuid4(), groups=[])
        assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_publish_artifact(service: WorkbenchService) -> None:
    draft_id = uuid.uuid4()
    user_oid = uuid.uuid4()
    groups = [uuid.uuid4()]
    req = PublishRequest()
    sig = "valid-sig"

    # Patch SignatureValidator.verify_asset to bypass crypto check
    with (
        patch("coreason_veritas.gatekeeper.SignatureValidator.verify_asset", return_value=True),
        patch.object(service, "_get_draft_and_verify_access", new_callable=AsyncMock),
        patch(
            "coreason_adlc_api.workbench.service_governed.service_publish_artifact", new_callable=AsyncMock
        ) as mock_pub,
    ):
        mock_pub.return_value = "http://url"
        res = await service.publish_artifact(
            draft_id=draft_id, request=req, signature=sig, user_oid=user_oid, groups=groups
        )
        assert res["url"] == "http://url"
        mock_pub.assert_awaited_once_with(draft_id, sig, user_oid)


@pytest.mark.asyncio
async def test_publish_artifact_error(service: WorkbenchService) -> None:
    # Patch verify_asset to pass
    with (
        patch("coreason_veritas.gatekeeper.SignatureValidator.verify_asset", return_value=True),
        patch.object(service, "_get_draft_and_verify_access", new_callable=AsyncMock),
        patch(
            "coreason_adlc_api.workbench.service_governed.service_publish_artifact", side_effect=ValueError("Bad sig")
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            await service.publish_artifact(
                draft_id=uuid.uuid4(), request=PublishRequest(), signature="sig", user_oid=uuid.uuid4(), groups=[]
            )
        assert exc.value.status_code == 400
