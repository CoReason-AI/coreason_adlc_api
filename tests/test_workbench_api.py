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
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from coreason_adlc_api.app import app
from coreason_adlc_api.workbench.schemas import DraftResponse


@pytest.fixture
def mock_auth_header(mock_oidc_factory: Any) -> str:
    user_uuid = str(uuid.uuid4())
    token = mock_oidc_factory(
        {
            "sub": user_uuid,
            "oid": user_uuid,
            "name": "Workbench Tester",
            "email": "workbench@coreason.ai",
        }
    )
    return f"Bearer {token}"


@pytest.mark.asyncio
async def test_create_draft(mock_auth_header: str) -> None:
    mock_response = DraftResponse(
        draft_id=uuid.uuid4(),
        user_uuid=uuid.uuid4(),
        auc_id="project-alpha",
        title="My Agent",
        oas_content={"info": "test"},
        created_at=datetime.datetime.now(),
        updated_at=datetime.datetime.now(),
    )

    # Mock the Governed Service method, not the underlying service function or the router logic
    with patch("coreason_adlc_api.routers.workbench.WorkbenchService") as MockService:
        instance = MockService.return_value
        instance.create_draft = AsyncMock(return_value=mock_response)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            payload = {"auc_id": "project-alpha", "title": "My Agent", "oas_content": {"info": "test"}}
            resp = await ac.post("/api/v1/workbench/drafts", json=payload, headers={"Authorization": mock_auth_header})

            assert resp.status_code == 201
            data = resp.json()
            assert data["auc_id"] == "project-alpha"
            instance.create_draft.assert_called_once()


@pytest.mark.asyncio
async def test_list_drafts(mock_auth_header: str) -> None:
    mock_list = [
        DraftResponse(
            draft_id=uuid.uuid4(),
            user_uuid=uuid.uuid4(),
            auc_id="project-alpha",
            title="Agent 1",
            oas_content={},
            created_at=datetime.datetime.now(),
            updated_at=datetime.datetime.now(),
        )
    ]

    with patch("coreason_adlc_api.routers.workbench.WorkbenchService") as MockService:
        instance = MockService.return_value
        instance.list_drafts = AsyncMock(return_value=mock_list)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get(
                "/api/v1/workbench/drafts?auc_id=project-alpha", headers={"Authorization": mock_auth_header}
            )
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 1
            assert data[0]["title"] == "Agent 1"


@pytest.mark.asyncio
async def test_get_draft_by_id(mock_auth_header: str) -> None:
    draft_id = uuid.uuid4()
    mock_resp = DraftResponse(
        draft_id=draft_id,
        user_uuid=uuid.uuid4(),
        auc_id="project-alpha",
        title="Agent 1",
        oas_content={},
        created_at=datetime.datetime.now(),
        updated_at=datetime.datetime.now(),
    )

    with patch("coreason_adlc_api.routers.workbench.WorkbenchService") as MockService:
        instance = MockService.return_value
        instance.get_draft = AsyncMock(return_value=mock_resp)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get(f"/api/v1/workbench/drafts/{draft_id}", headers={"Authorization": mock_auth_header})
            assert resp.status_code == 200
            assert resp.json()["draft_id"] == str(draft_id)


@pytest.mark.asyncio
async def test_update_draft(mock_auth_header: str) -> None:
    draft_id = uuid.uuid4()
    mock_resp = DraftResponse(
        draft_id=draft_id,
        user_uuid=uuid.uuid4(),
        auc_id="project-alpha",
        title="Updated Title",
        oas_content={},
        created_at=datetime.datetime.now(),
        updated_at=datetime.datetime.now(),
    )

    with patch("coreason_adlc_api.routers.workbench.WorkbenchService") as MockService:
        instance = MockService.return_value
        instance.update_draft = AsyncMock(return_value=mock_resp)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.put(
                f"/api/v1/workbench/drafts/{draft_id}",
                json={"title": "Updated Title"},
                headers={"Authorization": mock_auth_header},
            )
            assert resp.status_code == 200
            assert resp.json()["title"] == "Updated Title"


@pytest.mark.asyncio
async def test_heartbeat_lock_api(mock_auth_header: str) -> None:
    draft_id = uuid.uuid4()

    with patch("coreason_adlc_api.routers.workbench.WorkbenchService") as MockService:
        instance = MockService.return_value
        instance.heartbeat_lock = AsyncMock(return_value={"success": True})

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post(
                f"/api/v1/workbench/drafts/{draft_id}/lock", headers={"Authorization": mock_auth_header}
            )
            assert resp.status_code == 200
            assert resp.json()["success"] is True


@pytest.mark.asyncio
async def test_publish_artifact_missing_header(mock_auth_header: str) -> None:
    """Test that missing x-coreason-sig header raises 400 or fails."""
    draft_id = uuid.uuid4()
    # No header provided
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            f"/api/v1/workbench/drafts/{draft_id}/publish",
            headers={"Authorization": mock_auth_header},
            # Removed json body as schema changed
        )
        assert resp.status_code == 400
        assert "Missing x-coreason-sig" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_publish_artifact_success(mock_auth_header: str) -> None:
    draft_id = uuid.uuid4()
    with patch("coreason_adlc_api.routers.workbench.WorkbenchService") as MockService:
        instance = MockService.return_value
        instance.publish_artifact = AsyncMock(return_value="https://gitlab.example.com/agents/1/v1")

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post(
                f"/api/v1/workbench/drafts/{draft_id}/publish",
                headers={
                    "Authorization": mock_auth_header,
                    "x-coreason-sig": "valid-sig",
                },
            )
            assert resp.status_code == 200
            assert resp.json()["url"] == "https://gitlab.example.com/agents/1/v1"
            instance.publish_artifact.assert_called_once()
            # Check arguments
            args, kwargs = instance.publish_artifact.call_args
            assert kwargs["signature"] == "valid-sig"
