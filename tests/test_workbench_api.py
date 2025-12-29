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
from coreason_adlc_api.app import app
from coreason_adlc_api.workbench.schemas import DraftResponse
from httpx import ASGITransport, AsyncClient


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

    with (
        patch(
            "coreason_adlc_api.workbench.service_governed.create_draft", new=AsyncMock(return_value=mock_response)
        ) as mock_create,
        patch(
            "coreason_adlc_api.workbench.service_governed.map_groups_to_projects",
            new=AsyncMock(return_value=["project-alpha"]),
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            payload = {"auc_id": "project-alpha", "title": "My Agent", "oas_content": {"info": "test"}}
            resp = await ac.post("/api/v1/workbench/drafts", json=payload, headers={"Authorization": mock_auth_header})

            assert resp.status_code == 201
            data = resp.json()
            assert data["auc_id"] == "project-alpha"
            mock_create.assert_called_once()


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

    with (
        patch("coreason_adlc_api.workbench.service_governed.get_drafts", new=AsyncMock(return_value=mock_list)),
        patch(
            "coreason_adlc_api.workbench.service_governed.map_groups_to_projects",
            new=AsyncMock(return_value=["project-alpha"]),
        ),
    ):
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

    with (
        patch("coreason_adlc_api.workbench.service_governed.get_draft_by_id", new=AsyncMock(return_value=mock_resp)),
        patch(
            "coreason_adlc_api.workbench.service_governed.map_groups_to_projects",
            new=AsyncMock(return_value=["project-alpha"]),
        ),
        patch(
            "coreason_adlc_api.workbench.service_governed.WorkbenchService._get_user_roles",
            new=AsyncMock(return_value=[]),
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get(f"/api/v1/workbench/drafts/{draft_id}", headers={"Authorization": mock_auth_header})
            assert resp.status_code == 200
            assert resp.json()["draft_id"] == str(draft_id)


@pytest.mark.asyncio
async def test_get_draft_not_found(mock_auth_header: str) -> None:
    with (
        patch("coreason_adlc_api.workbench.service_governed.get_draft_by_id", new=AsyncMock(return_value=None)),
        patch(
            "coreason_adlc_api.workbench.service_governed.WorkbenchService._get_user_roles",
            new=AsyncMock(return_value=[]),
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get(f"/api/v1/workbench/drafts/{uuid.uuid4()}", headers={"Authorization": mock_auth_header})
            assert resp.status_code == 404


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

    with (
        patch("coreason_adlc_api.workbench.service_governed.update_draft", new=AsyncMock(return_value=mock_resp)),
        patch("coreason_adlc_api.workbench.service_governed.get_draft_by_id", new=AsyncMock(return_value=mock_resp)),
        patch(
            "coreason_adlc_api.workbench.service_governed.map_groups_to_projects",
            new=AsyncMock(return_value=["project-alpha"]),
        ),
    ):
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

    with patch("coreason_adlc_api.workbench.service_governed.refresh_lock", new=AsyncMock()) as mock_refresh:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post(
                f"/api/v1/workbench/drafts/{draft_id}/lock", headers={"Authorization": mock_auth_header}
            )
            assert resp.status_code == 200
            assert resp.json()["success"] is True
            mock_refresh.assert_called_once()


@pytest.mark.asyncio
async def test_manager_cannot_update_locked_draft(mock_auth_header: str) -> None:
    """
    Verify that even if a Manager can view a locked draft (Safe View),
    they cannot perform updates (PUT) because they do not hold the lock.
    """
    draft_id = uuid.uuid4()
    from fastapi import HTTPException

    mock_resp = DraftResponse(
        draft_id=draft_id,
        user_uuid=uuid.uuid4(),
        auc_id="project-alpha",
        title="Manager Takeover",
        oas_content={},
        created_at=datetime.datetime.now(),
        updated_at=datetime.datetime.now(),
    )

    with (
        patch(
            "coreason_adlc_api.workbench.service_governed.update_draft",
            side_effect=HTTPException(status_code=423, detail="Locked"),
        ),
        patch("coreason_adlc_api.workbench.service_governed.get_draft_by_id", new=AsyncMock(return_value=mock_resp)),
        patch(
            "coreason_adlc_api.workbench.service_governed.map_groups_to_projects",
            new=AsyncMock(return_value=["project-alpha"]),
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.put(
                f"/api/v1/workbench/drafts/{draft_id}",
                json={"title": "Manager Takeover"},
                headers={"Authorization": mock_auth_header},
            )
            assert resp.status_code == 423
            assert "Locked" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_update_draft_not_found_router(mock_auth_header: str) -> None:
    with patch("coreason_adlc_api.workbench.service_governed.get_draft_by_id", new=AsyncMock(return_value=None)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.put(
                f"/api/v1/workbench/drafts/{uuid.uuid4()}",
                json={"title": "Updated Title"},
                headers={"Authorization": mock_auth_header},
            )
            assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_drafts_forbidden(mock_auth_header: str) -> None:
    """Test GET /workbench/drafts - Forbidden."""
    with patch(
        "coreason_adlc_api.workbench.service_governed.map_groups_to_projects",
        new=AsyncMock(return_value=["other-project"]),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get(
                "/api/v1/workbench/drafts?auc_id=project-alpha", headers={"Authorization": mock_auth_header}
            )
            assert resp.status_code == 403
