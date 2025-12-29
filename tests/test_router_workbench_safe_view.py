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
from coreason_adlc_api.workbench.locking import AccessMode
from coreason_adlc_api.workbench.schemas import DraftResponse


# Helper to generate tokens with specific claims (roles)
def generate_token(mock_oidc_factory: Any, user_uuid: str, roles: list[str]) -> str:
    token = mock_oidc_factory(
        {
            "sub": user_uuid,
            "oid": user_uuid,
            "name": "Test User",
            "email": "test@coreason.ai",
            "groups": [str(uuid.uuid4()) for _ in roles],  # Dummy groups
        }
    )
    return f"Bearer {token}"


@pytest.mark.asyncio
async def test_get_draft_safe_view_integration(mock_oidc_factory: Any) -> None:
    """
    Verifies that the API correctly returns `mode: SAFE_VIEW` when:
    1. The draft is locked by User A.
    2. User B (Manager) requests it.
    """
    draft_id = uuid.uuid4()
    user_a_uuid = str(uuid.uuid4())
    manager_uuid = str(uuid.uuid4())

    # Mock response from Service
    mock_resp_obj = DraftResponse(
        draft_id=draft_id,
        user_uuid=uuid.UUID(user_a_uuid),
        auc_id="project-alpha",
        title="Locked Draft",
        oas_content={},
        created_at=datetime.datetime.now(),
        updated_at=datetime.datetime.now(),
    )
    mock_resp_obj.mode = AccessMode.SAFE_VIEW

    # Patch WorkbenchService in the router module
    with (
        patch("coreason_adlc_api.routers.workbench.WorkbenchService") as MockServiceCls,
        patch("coreason_adlc_api.routers.workbench._verify_project_access", new=AsyncMock()),
    ):
        mock_service_instance = MockServiceCls.return_value
        mock_service_instance.get_draft = AsyncMock(return_value=mock_resp_obj)

        manager_token = generate_token(mock_oidc_factory, manager_uuid, ["MANAGER_GROUP"])

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get(f"/api/v1/workbench/drafts/{draft_id}", headers={"Authorization": manager_token})

            assert resp.status_code == 200
            data = resp.json()

            # Critical Check: Verify the mode is returned in JSON (Enum value is "SAFE_VIEW")
            assert data["mode"] == "SAFE_VIEW"
            assert data["draft_id"] == str(draft_id)

            # Verify service was called correctly
            mock_service_instance.get_draft.assert_awaited_once()
            _, kwargs = mock_service_instance.get_draft.call_args
            assert kwargs["draft_id"] == draft_id
            assert kwargs["user_oid"] == uuid.UUID(manager_uuid)
            # Groups are passed as list of UUIDs, verifying length
            assert len(kwargs["groups"]) == 1


@pytest.mark.asyncio
async def test_get_draft_locked_access_denied(mock_oidc_factory: Any) -> None:
    """
    Verifies that a non-manager gets 423 Locked when the service raises it.
    """
    draft_id = uuid.uuid4()
    developer_uuid = str(uuid.uuid4())

    from fastapi import HTTPException

    # Service raises 423 (mocked)
    with (
        patch("coreason_adlc_api.routers.workbench.WorkbenchService") as MockServiceCls,
        patch("coreason_adlc_api.routers.workbench._verify_project_access", new=AsyncMock()),
    ):
        mock_service_instance = MockServiceCls.return_value
        # If the service (underlying) raises 423, the governed service usually propagates it
        # unless it catches it. Assuming propagation.
        mock_service_instance.get_draft = AsyncMock(
            side_effect=HTTPException(status_code=423, detail="Locked by User A")
        )

        token = generate_token(mock_oidc_factory, developer_uuid, [])

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get(f"/api/v1/workbench/drafts/{draft_id}", headers={"Authorization": token})

            assert resp.status_code == 423
            assert "Locked by User A" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_get_draft_edit_mode(mock_oidc_factory: Any) -> None:
    """
    Verifies normal Edit mode.
    """
    draft_id = uuid.uuid4()
    user_uuid = str(uuid.uuid4())

    mock_resp_obj = DraftResponse(
        draft_id=draft_id,
        user_uuid=uuid.UUID(user_uuid),
        auc_id="project-alpha",
        title="My Draft",
        oas_content={},
        created_at=datetime.datetime.now(),
        updated_at=datetime.datetime.now(),
    )
    # Default is EDIT

    with (
        patch("coreason_adlc_api.routers.workbench.WorkbenchService") as MockServiceCls,
        patch("coreason_adlc_api.routers.workbench._verify_project_access", new=AsyncMock()),
    ):
        mock_service_instance = MockServiceCls.return_value
        mock_service_instance.get_draft = AsyncMock(return_value=mock_resp_obj)

        token = generate_token(mock_oidc_factory, user_uuid, [])

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get(f"/api/v1/workbench/drafts/{draft_id}", headers={"Authorization": token})

            assert resp.status_code == 200
            data = resp.json()
            assert data["mode"] == "EDIT"
