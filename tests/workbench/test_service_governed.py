# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

from datetime import datetime, timezone
from typing import AsyncGenerator
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from coreason_adlc_api.workbench.schemas import ApprovalStatus, DraftCreate, DraftResponse
from coreason_adlc_api.workbench.service_governed import WorkbenchService


@pytest.fixture
def service() -> WorkbenchService:
    return WorkbenchService()


@pytest.fixture
def mock_db_pool() -> AsyncGenerator[AsyncMock, None]:
    with patch("coreason_adlc_api.workbench.service_governed.get_pool") as mock_pool:
        mock_conn = AsyncMock()
        mock_pool.return_value = mock_conn
        yield mock_conn


@pytest.mark.asyncio
async def test_derive_roles(service: WorkbenchService, mock_db_pool: AsyncMock) -> None:
    mock_db_pool.fetch.return_value = [{"role_name": "MANAGER"}]
    groups = [uuid4()]
    roles = await service._derive_roles(groups)
    assert roles == ["MANAGER"]
    mock_db_pool.fetch.assert_called_once()


@pytest.mark.asyncio
async def test_verify_project_access_success(service: WorkbenchService) -> None:
    with patch(
        "coreason_adlc_api.workbench.service_governed.map_groups_to_projects",
        new=AsyncMock(return_value=["alpha"]),
    ):
        await service._verify_project_access([uuid4()], "alpha")


@pytest.mark.asyncio
async def test_verify_project_access_fail(service: WorkbenchService) -> None:
    with patch(
        "coreason_adlc_api.workbench.service_governed.map_groups_to_projects",
        new=AsyncMock(return_value=["beta"]),
    ):
        with pytest.raises(HTTPException) as exc:
            await service._verify_project_access([uuid4()], "alpha")
        assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_create_draft(service: WorkbenchService) -> None:
    draft_in = DraftCreate(auc_id="alpha", title="Test", oas_content={})
    user_oid = uuid4()
    groups = [uuid4()]

    mock_resp = DraftResponse(
        draft_id=uuid4(),
        user_uuid=user_oid,
        auc_id="alpha",
        title="Test",
        oas_content={},
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )

    with (
        patch.object(service, "_verify_project_access", new=AsyncMock()) as mock_verify,
        patch("coreason_adlc_api.workbench.service.create_draft", new=AsyncMock(return_value=mock_resp)) as mock_create,
    ):
        resp = await service.create_draft(draft=draft_in, user_oid=user_oid, groups=groups)
        assert resp == mock_resp
        mock_verify.assert_called_once_with(groups, "alpha")
        mock_create.assert_called_once_with(draft_in, user_oid)


@pytest.mark.asyncio
async def test_publish_artifact_strict(service: WorkbenchService) -> None:
    draft_id = uuid4()
    user_oid = uuid4()
    groups = [uuid4()]
    signature = "valid_sig"

    # Patch SignatureValidator to avoid key loading error
    with (
        patch("coreason_veritas.gatekeeper.SignatureValidator.verify_asset"),
        patch.object(service, "_get_draft_and_verify_access", new=AsyncMock()),
        patch(
            "coreason_adlc_api.workbench.service.publish_artifact", new=AsyncMock(return_value="http://url")
        ) as mock_publish,
    ):
        resp = await service.publish_artifact(draft_id=draft_id, signature=signature, user_oid=user_oid, groups=groups)
        assert resp == {"url": "http://url"}
        mock_publish.assert_called_once_with(draft_id, signature, user_oid)


@pytest.mark.asyncio
async def test_approve_draft_manager(service: WorkbenchService) -> None:
    draft_id = uuid4()
    user_oid = uuid4()
    groups = [uuid4()]

    with (
        patch.object(service, "_derive_roles", new=AsyncMock(return_value=["MANAGER"])),
        patch.object(service, "_get_draft_and_verify_access", new=AsyncMock()),
        patch("coreason_adlc_api.workbench.service.transition_draft_status", new=AsyncMock()) as mock_transition,
    ):
        await service.approve_draft(draft_id=draft_id, user_oid=user_oid, groups=groups)
        mock_transition.assert_called_once()
        assert mock_transition.call_args[0][2] == ApprovalStatus.APPROVED


@pytest.mark.asyncio
async def test_approve_draft_not_manager(service: WorkbenchService) -> None:
    draft_id = uuid4()
    user_oid = uuid4()
    groups = [uuid4()]

    with (
        patch.object(service, "_derive_roles", new=AsyncMock(return_value=["USER"])),
    ):
        with pytest.raises(HTTPException) as exc:
            await service.approve_draft(draft_id=draft_id, user_oid=user_oid, groups=groups)
        assert exc.value.status_code == 403
