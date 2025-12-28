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
            "name": "Edge Case Tester",
            "email": "edge@coreason.ai",
        }
    )
    return f"Bearer {token}"


@pytest.mark.asyncio
async def test_create_draft_unauthorized_project(mock_auth_header: str) -> None:
    """
    User tries to create a draft for a project they do not have access to.
    Expects 403 Forbidden.
    """
    with patch(
        "coreason_adlc_api.routers.workbench.map_groups_to_projects",
        new=AsyncMock(return_value=["project-beta"]),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            payload = {"auc_id": "project-alpha", "title": "Unauthorized Agent", "oas_content": {"info": "test"}}
            resp = await ac.post("/api/v1/workbench/drafts", json=payload, headers={"Authorization": mock_auth_header})

            assert resp.status_code == 403
            assert "User is not authorized" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_get_draft_unauthorized_project(mock_auth_header: str) -> None:
    """
    User tries to retrieve a draft belonging to a project they don't have access to.
    Expects 403 Forbidden.
    """
    draft_id = uuid.uuid4()
    mock_resp = DraftResponse(
        draft_id=draft_id,
        user_uuid=uuid.uuid4(),
        auc_id="project-alpha",
        title="Secret Agent",
        oas_content={},
        created_at=datetime.datetime.now(),
        updated_at=datetime.datetime.now(),
    )

    with (
        patch("coreason_adlc_api.routers.workbench.get_draft_by_id", new=AsyncMock(return_value=mock_resp)),
        patch(
            "coreason_adlc_api.routers.workbench.map_groups_to_projects",
            new=AsyncMock(return_value=["project-beta"]),  # User only has access to project-beta
        ),
        patch("coreason_adlc_api.routers.workbench._get_user_roles", new=AsyncMock(return_value=[])),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get(f"/api/v1/workbench/drafts/{draft_id}", headers={"Authorization": mock_auth_header})
            assert resp.status_code == 403
            assert "User is not authorized" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_update_draft_unauthorized_project(mock_auth_header: str) -> None:
    """
    User tries to update a draft belonging to a project they don't have access to.
    Expects 403 Forbidden.
    """
    draft_id = uuid.uuid4()
    mock_resp = DraftResponse(
        draft_id=draft_id,
        user_uuid=uuid.uuid4(),
        auc_id="project-alpha",
        title="Secret Agent",
        oas_content={},
        created_at=datetime.datetime.now(),
        updated_at=datetime.datetime.now(),
    )

    with (
        patch("coreason_adlc_api.routers.workbench.get_draft_by_id", new=AsyncMock(return_value=mock_resp)),
        patch(
            "coreason_adlc_api.routers.workbench.map_groups_to_projects",
            new=AsyncMock(return_value=["project-beta"]),
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.put(
                f"/api/v1/workbench/drafts/{draft_id}",
                json={"title": "Hacked Title"},
                headers={"Authorization": mock_auth_header},
            )
            assert resp.status_code == 403
            assert "User is not authorized" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_create_draft_invalid_input(mock_auth_header: str) -> None:
    """
    User sends invalid payloads.
    Expects 422 Unprocessable Entity.
    """
    with patch(
        "coreason_adlc_api.routers.workbench.map_groups_to_projects",
        new=AsyncMock(return_value=["project-alpha"]),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            # Missing required fields
            resp = await ac.post(
                "/api/v1/workbench/drafts",
                json={"auc_id": "project-alpha"},
                headers={"Authorization": mock_auth_header},
            )
            assert resp.status_code == 422

            # Empty title (if constrained by schema, check response)
            # Assuming title min_length is not 0, or checking behavior.
            # If schema doesn't restrict empty title, this might pass (201).
            # Let's check schema via response or assume 422 if restricted.
            # Actually, let's assume Pydantic validation handles bad types.

            resp = await ac.post(
                "/api/v1/workbench/drafts",
                json={
                    "auc_id": "project-alpha",
                    "title": "Valid",
                    "oas_content": "NOT A DICT",  # Invalid type
                },
                headers={"Authorization": mock_auth_header},
            )
            assert resp.status_code == 422


@pytest.mark.asyncio
async def test_vault_unauthorized_project(mock_auth_header: str) -> None:
    """
    User tries to store a secret for a project they don't own.
    Expects 403.
    """
    with patch(
        "coreason_adlc_api.routers.vault.map_groups_to_projects",
        new=AsyncMock(return_value=["project-beta"]),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            payload = {"auc_id": "project-alpha", "service_name": "openai", "raw_api_key": "sk-..."}
            resp = await ac.post("/api/v1/vault/secrets", json=payload, headers={"Authorization": mock_auth_header})
            assert resp.status_code == 403


@pytest.mark.asyncio
async def test_system_compliance_missing() -> None:
    """
    System cannot find compliance.yaml.
    Expects 500.
    """
    with patch("os.path.exists", return_value=False):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/v1/system/compliance")
            assert resp.status_code == 500
            assert "Compliance definition file missing" in resp.json()["detail"]
