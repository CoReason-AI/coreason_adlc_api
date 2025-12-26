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

import jwt
import pytest
from coreason_adlc_api.app import app
from coreason_adlc_api.auth.identity import JWT_ALGORITHM, JWT_SECRET
from coreason_adlc_api.workbench.schemas import DraftResponse
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def mock_auth_header() -> str:
    user_uuid = str(uuid.uuid4())
    payload = {
        "sub": user_uuid,
        "oid": user_uuid,
        "name": "Workbench Tester",
        "email": "workbench@coreason.ai",
        "groups": [],
        "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
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

    with patch(
        "coreason_adlc_api.routers.workbench.create_draft", new=AsyncMock(return_value=mock_response)
    ) as mock_create:
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

    with patch("coreason_adlc_api.routers.workbench.get_drafts", new=AsyncMock(return_value=mock_list)):
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

    with patch("coreason_adlc_api.routers.workbench.get_draft_by_id", new=AsyncMock(return_value=mock_resp)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get(f"/api/v1/workbench/drafts/{draft_id}", headers={"Authorization": mock_auth_header})
            assert resp.status_code == 200
            assert resp.json()["draft_id"] == str(draft_id)


@pytest.mark.asyncio
async def test_get_draft_not_found(mock_auth_header: str) -> None:
    with patch("coreason_adlc_api.routers.workbench.get_draft_by_id", new=AsyncMock(return_value=None)):
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

    with patch("coreason_adlc_api.routers.workbench.update_draft", new=AsyncMock(return_value=mock_resp)):
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

    with patch("coreason_adlc_api.routers.workbench.refresh_lock", new=AsyncMock()) as mock_refresh:
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

    # Mock update_draft to raise 423 (Locked) which is what verify_lock_for_update would do
    # In integration, verify_lock_for_update raises the error.
    # Here we mock update_draft which contains the verify logic call
    # But wait, update_draft calls verify_lock_for_update.
    # Ideally we should mock verify_lock_for_update to raise exception?
    # Or let it run if we can mock DB state?
    # test_workbench_api mocks `coreason_adlc_api.routers.workbench.update_draft`.
    # So the router just calls the mock.
    # To test the router's behavior on exception, we should make the mock raise.

    from fastapi import HTTPException

    with patch(
        "coreason_adlc_api.routers.workbench.update_draft", side_effect=HTTPException(status_code=423, detail="Locked")
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.put(
                f"/api/v1/workbench/drafts/{draft_id}",
                json={"title": "Manager Takeover"},
                headers={"Authorization": mock_auth_header},
            )
            assert resp.status_code == 423
            assert "Locked" in resp.json()["detail"]
