# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

import datetime
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from coreason_adlc_api.workbench.schemas import (
    AgentArtifact,
    ApprovalStatus,
    DraftCreate,
    DraftResponse,
    DraftUpdate,
)
from coreason_adlc_api.workbench.service_governed import WorkbenchService


@pytest.fixture
def service() -> WorkbenchService:
    return WorkbenchService()


@pytest.fixture
def user_oid() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def group_oid() -> uuid.UUID:
    return uuid.uuid4()


@pytest.mark.asyncio
async def test_verify_project_access_success(
    service: WorkbenchService, user_oid: uuid.UUID, group_oid: uuid.UUID
) -> None:
    with patch(
        "coreason_adlc_api.workbench.service_governed.map_groups_to_projects", new=AsyncMock(return_value=["auc-123"])
    ):
        # Should not raise
        await service._verify_project_access([group_oid], "auc-123")


@pytest.mark.asyncio
async def test_verify_project_access_forbidden(
    service: WorkbenchService, user_oid: uuid.UUID, group_oid: uuid.UUID
) -> None:
    with patch(
        "coreason_adlc_api.workbench.service_governed.map_groups_to_projects", new=AsyncMock(return_value=["auc-other"])
    ):
        with pytest.raises(HTTPException) as exc:
            await service._verify_project_access([group_oid], "auc-123")
        assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_create_draft(service: WorkbenchService, user_oid: uuid.UUID, group_oid: uuid.UUID) -> None:
    draft_input = DraftCreate(auc_id="auc-123", title="Test", oas_content={})
    expected_resp = DraftResponse(
        draft_id=uuid.uuid4(),
        user_uuid=user_oid,
        auc_id="auc-123",
        title="Test",
        oas_content={},
        created_at=datetime.datetime.now(),
        updated_at=datetime.datetime.now(),
    )

    with (
        patch(
            "coreason_adlc_api.workbench.service_governed.map_groups_to_projects",
            new=AsyncMock(return_value=["auc-123"]),
        ),
        patch(
            "coreason_adlc_api.workbench.service_governed.create_draft", new=AsyncMock(return_value=expected_resp)
        ) as mock_create,
    ):
        resp = await service.create_draft(draft=draft_input, user_oid=user_oid, groups=[group_oid])
        assert resp == expected_resp
        mock_create.assert_called_once()


@pytest.mark.asyncio
async def test_approve_draft_manager(service: WorkbenchService, user_oid: uuid.UUID, group_oid: uuid.UUID) -> None:
    draft_id = uuid.uuid4()
    mock_draft = DraftResponse(
        draft_id=draft_id,
        user_uuid=user_oid,
        auc_id="auc-123",
        title="Test",
        oas_content={},
        created_at=datetime.datetime.now(),
        updated_at=datetime.datetime.now(),
    )

    mock_pool = AsyncMock()
    mock_pool.fetch.return_value = [{"role_name": "MANAGER"}]

    with (
        patch("coreason_adlc_api.workbench.service_governed.get_pool", return_value=mock_pool),
        patch("coreason_adlc_api.workbench.service_governed.get_draft_by_id", new=AsyncMock(return_value=mock_draft)),
        patch(
            "coreason_adlc_api.workbench.service_governed.map_groups_to_projects",
            new=AsyncMock(return_value=["auc-123"]),
        ),
        patch(
            "coreason_adlc_api.workbench.service_governed.transition_draft_status",
            new=AsyncMock(return_value=mock_draft),
        ) as mock_trans,
    ):
        await service.approve_draft(draft_id=draft_id, user_oid=user_oid, groups=[group_oid])
        mock_trans.assert_called_once_with(draft_id, user_oid, ApprovalStatus.APPROVED)


@pytest.mark.asyncio
async def test_approve_draft_not_manager(service: WorkbenchService, user_oid: uuid.UUID, group_oid: uuid.UUID) -> None:
    mock_pool = AsyncMock()
    mock_pool.fetch.return_value = [{"role_name": "DEVELOPER"}]

    with patch("coreason_adlc_api.workbench.service_governed.get_pool", return_value=mock_pool):
        with pytest.raises(HTTPException) as exc:
            await service.approve_draft(draft_id=uuid.uuid4(), user_oid=user_oid, groups=[group_oid])
        assert exc.value.status_code == 403
        assert "Only managers" in exc.value.detail


@pytest.mark.asyncio
async def test_get_draft_not_found(service: WorkbenchService, user_oid: uuid.UUID, group_oid: uuid.UUID) -> None:
    with patch("coreason_adlc_api.workbench.service_governed.get_draft_by_id", new=AsyncMock(return_value=None)):
        # Need to mock _derive_roles as it is called first
        with patch.object(WorkbenchService, "_derive_roles", new=AsyncMock(return_value=[])):
            with pytest.raises(HTTPException) as exc:
                await service.get_draft(draft_id=uuid.uuid4(), user_oid=user_oid, groups=[group_oid])
            assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_publish_artifact_strict(service: WorkbenchService, user_oid: uuid.UUID, group_oid: uuid.UUID) -> None:
    draft_id = uuid.uuid4()
    mock_draft = DraftResponse(
        draft_id=draft_id,
        user_uuid=user_oid,
        auc_id="auc-123",
        title="Test",
        oas_content={},
        created_at=datetime.datetime.now(),
        updated_at=datetime.datetime.now(),
    )

    with (
        patch("coreason_adlc_api.workbench.service_governed.get_draft_by_id", new=AsyncMock(return_value=mock_draft)),
        patch(
            "coreason_adlc_api.workbench.service_governed.map_groups_to_projects",
            new=AsyncMock(return_value=["auc-123"]),
        ),
        patch(
            "coreason_adlc_api.workbench.service_governed.publish_artifact", new=AsyncMock(return_value="http://url")
        ) as mock_pub,
    ):
        url = await service.publish_artifact(draft_id=draft_id, user_oid=user_oid, groups=[group_oid], signature="sig")
        assert url == "http://url"
        mock_pub.assert_called_once_with(draft_id, "sig", user_oid)


# Added tests for coverage


@pytest.mark.asyncio
async def test_list_drafts(service: WorkbenchService, user_oid: uuid.UUID, group_oid: uuid.UUID) -> None:
    with (
        patch(
            "coreason_adlc_api.workbench.service_governed.map_groups_to_projects",
            new=AsyncMock(return_value=["auc-123"]),
        ),
        patch("coreason_adlc_api.workbench.service_governed.get_drafts", new=AsyncMock(return_value=[])) as mock_list,
    ):
        await service.list_drafts(auc_id="auc-123", user_oid=user_oid, groups=[group_oid])
        mock_list.assert_called_once_with("auc-123")


@pytest.mark.asyncio
async def test_update_draft_not_found(service: WorkbenchService, user_oid: uuid.UUID, group_oid: uuid.UUID) -> None:
    with patch("coreason_adlc_api.workbench.service_governed.get_draft_by_id", new=AsyncMock(return_value=None)):
        with pytest.raises(HTTPException) as exc:
            await service.update_draft(
                draft_id=uuid.uuid4(), update=DraftUpdate(), user_oid=user_oid, groups=[group_oid]
            )
        assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_update_draft_success(service: WorkbenchService, user_oid: uuid.UUID, group_oid: uuid.UUID) -> None:
    draft_id = uuid.uuid4()
    mock_draft = DraftResponse(
        draft_id=draft_id,
        user_uuid=user_oid,
        auc_id="auc-123",
        title="Test",
        oas_content={},
        created_at=datetime.datetime.now(),
        updated_at=datetime.datetime.now(),
    )
    with (
        patch("coreason_adlc_api.workbench.service_governed.get_draft_by_id", new=AsyncMock(return_value=mock_draft)),
        patch(
            "coreason_adlc_api.workbench.service_governed.map_groups_to_projects",
            new=AsyncMock(return_value=["auc-123"]),
        ),
        patch(
            "coreason_adlc_api.workbench.service_governed.update_draft", new=AsyncMock(return_value=mock_draft)
        ) as mock_update,
    ):
        await service.update_draft(
            draft_id=draft_id, update=DraftUpdate(), user_oid=user_oid, groups=[group_oid]
        )
        mock_update.assert_called_once()


@pytest.mark.asyncio
async def test_heartbeat_lock(service: WorkbenchService, user_oid: uuid.UUID, group_oid: uuid.UUID) -> None:
    with patch("coreason_adlc_api.workbench.service_governed.refresh_lock", new=AsyncMock()) as mock_refresh:
        await service.heartbeat_lock(draft_id=uuid.uuid4(), user_oid=user_oid, groups=[group_oid])
        mock_refresh.assert_called_once()


@pytest.mark.asyncio
async def test_validate_draft_pii(service: WorkbenchService, user_oid: uuid.UUID, group_oid: uuid.UUID) -> None:
    # Mock budget and pii
    with (
        patch("coreason_adlc_api.workbench.service_governed.check_budget_status", return_value=True),
        patch(
            "coreason_adlc_api.workbench.service_governed.scrub_pii_recursive", return_value={"scrubbed": True}
        ),
    ):
        draft = DraftCreate(auc_id="auc-123", title="T", oas_content={"pii": "secret"})
        resp = await service.validate_draft(draft=draft, user_oid=user_oid, groups=[group_oid])
        # scrubbed != content, so issue expected
        assert resp.is_valid is False
        assert "PII Detected" in resp.issues


@pytest.mark.asyncio
async def test_validate_draft_budget(service: WorkbenchService, user_oid: uuid.UUID, group_oid: uuid.UUID) -> None:
    with (
        patch("coreason_adlc_api.workbench.service_governed.check_budget_status", return_value=False),
        patch(
            "coreason_adlc_api.workbench.service_governed.scrub_pii_recursive", return_value={}
        ),
    ):
        draft = DraftCreate(auc_id="auc-123", title="T", oas_content={})
        resp = await service.validate_draft(draft=draft, user_oid=user_oid, groups=[group_oid])
        assert resp.is_valid is False
        assert "Budget Limit Reached" in resp.issues


@pytest.mark.asyncio
async def test_submit_draft_not_found(service: WorkbenchService, user_oid: uuid.UUID, group_oid: uuid.UUID) -> None:
    with patch("coreason_adlc_api.workbench.service_governed.get_draft_by_id", new=AsyncMock(return_value=None)):
        with pytest.raises(HTTPException) as exc:
            await service.submit_draft(draft_id=uuid.uuid4(), user_oid=user_oid, groups=[group_oid])
        assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_submit_draft_success(service: WorkbenchService, user_oid: uuid.UUID, group_oid: uuid.UUID) -> None:
    draft_id = uuid.uuid4()
    mock_draft = DraftResponse(
        draft_id=draft_id,
        user_uuid=user_oid,
        auc_id="auc-123",
        title="Test",
        oas_content={},
        created_at=datetime.datetime.now(),
        updated_at=datetime.datetime.now(),
    )
    with (
        patch("coreason_adlc_api.workbench.service_governed.get_draft_by_id", new=AsyncMock(return_value=mock_draft)),
        patch(
            "coreason_adlc_api.workbench.service_governed.map_groups_to_projects",
            new=AsyncMock(return_value=["auc-123"]),
        ),
        patch(
            "coreason_adlc_api.workbench.service_governed.transition_draft_status",
            new=AsyncMock(return_value=mock_draft),
        ) as mock_trans,
    ):
        await service.submit_draft(draft_id=draft_id, user_oid=user_oid, groups=[group_oid])
        mock_trans.assert_called_once_with(draft_id, user_oid, ApprovalStatus.PENDING)


@pytest.mark.asyncio
async def test_reject_draft_not_manager(service: WorkbenchService, user_oid: uuid.UUID, group_oid: uuid.UUID) -> None:
    mock_pool = AsyncMock()
    mock_pool.fetch.return_value = [{"role_name": "DEVELOPER"}]
    with patch("coreason_adlc_api.workbench.service_governed.get_pool", return_value=mock_pool):
        with pytest.raises(HTTPException) as exc:
            await service.reject_draft(draft_id=uuid.uuid4(), user_oid=user_oid, groups=[group_oid])
        assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_reject_draft_success(service: WorkbenchService, user_oid: uuid.UUID, group_oid: uuid.UUID) -> None:
    draft_id = uuid.uuid4()
    mock_draft = DraftResponse(
        draft_id=draft_id,
        user_uuid=user_oid,
        auc_id="auc-123",
        title="Test",
        oas_content={},
        created_at=datetime.datetime.now(),
        updated_at=datetime.datetime.now(),
    )

    mock_pool = AsyncMock()
    mock_pool.fetch.return_value = [{"role_name": "MANAGER"}]

    with (
        patch("coreason_adlc_api.workbench.service_governed.get_pool", return_value=mock_pool),
        patch("coreason_adlc_api.workbench.service_governed.get_draft_by_id", new=AsyncMock(return_value=mock_draft)),
        patch(
            "coreason_adlc_api.workbench.service_governed.map_groups_to_projects",
            new=AsyncMock(return_value=["auc-123"]),
        ),
        patch(
            "coreason_adlc_api.workbench.service_governed.transition_draft_status",
            new=AsyncMock(return_value=mock_draft),
        ) as mock_trans,
    ):
        await service.reject_draft(draft_id=draft_id, user_oid=user_oid, groups=[group_oid])
        mock_trans.assert_called_once_with(draft_id, user_oid, ApprovalStatus.REJECTED)


@pytest.mark.asyncio
async def test_get_artifact_assembly_not_found(
    service: WorkbenchService, user_oid: uuid.UUID, group_oid: uuid.UUID
) -> None:
    with patch("coreason_adlc_api.workbench.service_governed.get_draft_by_id", new=AsyncMock(return_value=None)):
        with pytest.raises(HTTPException) as exc:
            await service.get_artifact_assembly(draft_id=uuid.uuid4(), user_oid=user_oid, groups=[group_oid])
        assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_artifact_assembly_success(
    service: WorkbenchService, user_oid: uuid.UUID, group_oid: uuid.UUID
) -> None:
    draft_id = uuid.uuid4()
    mock_draft = DraftResponse(
        draft_id=draft_id,
        user_uuid=user_oid,
        auc_id="auc-123",
        title="Test",
        oas_content={},
        created_at=datetime.datetime.now(),
        updated_at=datetime.datetime.now(),
    )
    mock_artifact = AgentArtifact(
        id=draft_id,
        auc_id="auc-123",
        version="1.0.0",
        content={},
        compliance_hash="hash",
        created_at=datetime.datetime.now(),
    )

    with (
        patch("coreason_adlc_api.workbench.service_governed.get_draft_by_id", new=AsyncMock(return_value=mock_draft)),
        patch(
            "coreason_adlc_api.workbench.service_governed.map_groups_to_projects",
            new=AsyncMock(return_value=["auc-123"]),
        ),
        patch(
            "coreason_adlc_api.workbench.service_governed.assemble_artifact",
            new=AsyncMock(return_value=mock_artifact),
        ) as mock_assemble,
    ):
        result = await service.get_artifact_assembly(draft_id=draft_id, user_oid=user_oid, groups=[group_oid])
        assert result == mock_artifact
        mock_assemble.assert_called_once()


@pytest.mark.asyncio
async def test_get_artifact_assembly_value_error(
    service: WorkbenchService, user_oid: uuid.UUID, group_oid: uuid.UUID
) -> None:
    draft_id = uuid.uuid4()
    mock_draft = DraftResponse(
        draft_id=draft_id,
        user_uuid=user_oid,
        auc_id="auc-123",
        title="Test",
        oas_content={},
        created_at=datetime.datetime.now(),
        updated_at=datetime.datetime.now(),
    )

    with (
        patch("coreason_adlc_api.workbench.service_governed.get_draft_by_id", new=AsyncMock(return_value=mock_draft)),
        patch(
            "coreason_adlc_api.workbench.service_governed.map_groups_to_projects",
            new=AsyncMock(return_value=["auc-123"]),
        ),
        patch(
            "coreason_adlc_api.workbench.service_governed.assemble_artifact", side_effect=ValueError("Not approved")
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            await service.get_artifact_assembly(draft_id=draft_id, user_oid=user_oid, groups=[group_oid])
        assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_publish_artifact_not_found(service: WorkbenchService, user_oid: uuid.UUID, group_oid: uuid.UUID) -> None:
    with patch("coreason_adlc_api.workbench.service_governed.get_draft_by_id", new=AsyncMock(return_value=None)):
        with pytest.raises(HTTPException) as exc:
            await service.publish_artifact(
                draft_id=uuid.uuid4(), user_oid=user_oid, groups=[group_oid], signature="s"
            )
        assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_publish_artifact_value_error(
    service: WorkbenchService, user_oid: uuid.UUID, group_oid: uuid.UUID
) -> None:
    draft_id = uuid.uuid4()
    mock_draft = DraftResponse(
        draft_id=draft_id,
        user_uuid=user_oid,
        auc_id="auc-123",
        title="Test",
        oas_content={},
        created_at=datetime.datetime.now(),
        updated_at=datetime.datetime.now(),
    )

    with (
        patch("coreason_adlc_api.workbench.service_governed.get_draft_by_id", new=AsyncMock(return_value=mock_draft)),
        patch(
            "coreason_adlc_api.workbench.service_governed.map_groups_to_projects",
            new=AsyncMock(return_value=["auc-123"]),
        ),
        patch(
            "coreason_adlc_api.workbench.service_governed.publish_artifact", side_effect=ValueError("Failed")
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            await service.publish_artifact(
                draft_id=draft_id, user_oid=user_oid, groups=[group_oid], signature="s"
            )
        assert exc.value.status_code == 400
