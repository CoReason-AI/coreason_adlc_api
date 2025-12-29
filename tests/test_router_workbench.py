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
from typing import AsyncGenerator, Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from coreason_adlc_api.app import app
from coreason_adlc_api.auth.identity import parse_and_validate_token
from coreason_adlc_api.workbench.schemas import AgentArtifact, DraftResponse, ValidationResponse
from fastapi import Request
from httpx import ASGITransport, AsyncClient


# --- Mocks ---
async def mock_parse_token(request: Request) -> MagicMock:
    mock_id = MagicMock()
    mock_id.oid = uuid.UUID(int=1)
    mock_id.groups = [uuid.uuid4()]
    return mock_id


@pytest.fixture
def override_dependency() -> Generator[None, None, None]:
    app.dependency_overrides[parse_and_validate_token] = mock_parse_token
    yield
    app.dependency_overrides = {}


@pytest.fixture
def mock_service() -> Generator[AsyncMock, None, None]:
    # Mock the WorkbenchService class so that instantiating it returns a mock object
    with patch("coreason_adlc_api.routers.workbench.WorkbenchService") as MockService:
        instance = MockService.return_value
        yield instance


# --- Tests ---


@pytest.mark.asyncio
async def test_list_drafts(override_dependency: None, mock_service: AsyncMock) -> None:
    mock_service.list_drafts = AsyncMock(return_value=[])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/v1/workbench/drafts?auc_id=p1")
        assert resp.status_code == 200
        mock_service.list_drafts.assert_awaited_once()
        # Verify signature is passed (None by default)
        kwargs = mock_service.list_drafts.call_args.kwargs
        assert kwargs["signature"] is None


@pytest.mark.asyncio
async def test_create_new_draft(override_dependency: None, mock_service: AsyncMock) -> None:
    draft_id = uuid.uuid4()
    mock_service.create_new_draft = AsyncMock(
        return_value=DraftResponse(
            draft_id=draft_id,
            user_uuid=uuid.uuid4(),
            auc_id="p1",
            title="t",
            oas_content={},
            created_at="2024-01-01T00:00:00Z",
            updated_at="2024-01-01T00:00:00Z",
        )
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            "/api/v1/workbench/drafts",
            json={"auc_id": "p1", "title": "t", "oas_content": {}},
            headers={"x-coreason-sig": "s1"},
        )
        assert resp.status_code == 201
        kwargs = mock_service.create_new_draft.call_args.kwargs
        assert kwargs["signature"] == "s1"


@pytest.mark.asyncio
async def test_get_draft(override_dependency: None, mock_service: AsyncMock) -> None:
    draft_id = uuid.uuid4()
    mock_service.get_draft = AsyncMock(
        return_value=DraftResponse(
            draft_id=draft_id,
            user_uuid=uuid.uuid4(),
            auc_id="p1",
            title="t",
            oas_content={},
            created_at="2024-01-01T00:00:00Z",
            updated_at="2024-01-01T00:00:00Z",
        )
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get(f"/api/v1/workbench/drafts/{draft_id}")
        assert resp.status_code == 200
        mock_service.get_draft.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_existing_draft(override_dependency: None, mock_service: AsyncMock) -> None:
    draft_id = uuid.uuid4()
    mock_service.update_existing_draft = AsyncMock(
        return_value=DraftResponse(
            draft_id=draft_id,
            user_uuid=uuid.uuid4(),
            auc_id="p1",
            title="new",
            oas_content={},
            created_at="2024-01-01T00:00:00Z",
            updated_at="2024-01-01T00:00:00Z",
        )
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.put(f"/api/v1/workbench/drafts/{draft_id}", json={"title": "new"})
        assert resp.status_code == 200
        mock_service.update_existing_draft.assert_awaited_once()


@pytest.mark.asyncio
async def test_heartbeat_lock(override_dependency: None, mock_service: AsyncMock) -> None:
    mock_service.heartbeat_lock = AsyncMock(return_value={"success": True})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(f"/api/v1/workbench/drafts/{uuid.uuid4()}/lock")
        assert resp.status_code == 200
        mock_service.heartbeat_lock.assert_awaited_once()


@pytest.mark.asyncio
async def test_validate_draft(override_dependency: None, mock_service: AsyncMock) -> None:
    mock_service.validate_draft = AsyncMock(return_value=ValidationResponse(is_valid=True, issues=[]))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/v1/workbench/validate", json={"auc_id": "p1", "title": "t", "oas_content": {}})
        assert resp.status_code == 200
        mock_service.validate_draft.assert_awaited_once()


@pytest.mark.asyncio
async def test_submit_draft(override_dependency: None, mock_service: AsyncMock) -> None:
    draft_id = uuid.uuid4()
    mock_service.submit_draft = AsyncMock(
        return_value=DraftResponse(
            draft_id=draft_id,
            user_uuid=uuid.uuid4(),
            auc_id="p1",
            title="t",
            oas_content={},
            created_at="2024-01-01T00:00:00Z",
            updated_at="2024-01-01T00:00:00Z",
        )
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(f"/api/v1/workbench/drafts/{draft_id}/submit")
        assert resp.status_code == 200
        mock_service.submit_draft.assert_awaited_once()


@pytest.mark.asyncio
async def test_approve_draft(override_dependency: None, mock_service: AsyncMock) -> None:
    draft_id = uuid.uuid4()
    mock_service.approve_draft = AsyncMock(
        return_value=DraftResponse(
            draft_id=draft_id,
            user_uuid=uuid.uuid4(),
            auc_id="p1",
            title="t",
            oas_content={},
            created_at="2024-01-01T00:00:00Z",
            updated_at="2024-01-01T00:00:00Z",
        )
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(f"/api/v1/workbench/drafts/{draft_id}/approve")
        assert resp.status_code == 200
        mock_service.approve_draft.assert_awaited_once()


@pytest.mark.asyncio
async def test_reject_draft(override_dependency: None, mock_service: AsyncMock) -> None:
    draft_id = uuid.uuid4()
    mock_service.reject_draft = AsyncMock(
        return_value=DraftResponse(
            draft_id=draft_id,
            user_uuid=uuid.uuid4(),
            auc_id="p1",
            title="t",
            oas_content={},
            created_at="2024-01-01T00:00:00Z",
            updated_at="2024-01-01T00:00:00Z",
        )
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(f"/api/v1/workbench/drafts/{draft_id}/reject")
        assert resp.status_code == 200
        mock_service.reject_draft.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_artifact_assembly(override_dependency: None, mock_service: AsyncMock) -> None:
    draft_id = uuid.uuid4()
    mock_service.get_artifact_assembly = AsyncMock(
        return_value=AgentArtifact(
            id=draft_id,
            auc_id="p1",
            version="1.0",
            content={},
            compliance_hash="h",
            created_at="2024-01-01T00:00:00Z",
        )
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get(f"/api/v1/workbench/drafts/{draft_id}/assemble")
        assert resp.status_code == 200
        mock_service.get_artifact_assembly.assert_awaited_once()


@pytest.mark.asyncio
async def test_publish_agent_artifact(override_dependency: None, mock_service: AsyncMock) -> None:
    draft_id = uuid.uuid4()
    mock_service.publish_artifact = AsyncMock(return_value={"url": "http://git"})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            f"/api/v1/workbench/drafts/{draft_id}/publish", json={}, headers={"x-coreason-sig": "sig"}
        )
        assert resp.status_code == 200
        assert resp.json()["url"] == "http://git"
        kwargs = mock_service.publish_artifact.call_args.kwargs
        assert kwargs["signature"] == "sig"
