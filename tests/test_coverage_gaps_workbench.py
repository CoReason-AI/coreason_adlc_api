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
from typing import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from coreason_adlc_api.app import app
from coreason_adlc_api.auth.identity import parse_and_validate_token
from coreason_adlc_api.workbench.schemas import ApprovalStatus, DraftResponse
from coreason_adlc_api.workbench.service import transition_draft_status
from fastapi import HTTPException, Request
from httpx import ASGITransport, AsyncClient


# --- Mocks for Router Tests ---
async def mock_parse_token_gaps(request: Request) -> MagicMock:
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    mock_id = MagicMock()
    if token == "mock_editor":
        mock_id.oid = uuid.UUID(int=1)
        mock_id.groups = [uuid.uuid4()]
    elif token == "mock_manager":
        mock_id.oid = uuid.UUID(int=2)
        mock_id.groups = [uuid.uuid4()]
    else:
        raise HTTPException(status_code=401, detail="Invalid token")
    return mock_id


@pytest.fixture
def override_dependency_gaps() -> Generator[None, None, None]:
    app.dependency_overrides[parse_and_validate_token] = mock_parse_token_gaps
    yield
    app.dependency_overrides = {}


@pytest.fixture
def mock_auth_headers_gaps() -> tuple[dict[str, str], dict[str, str]]:
    return (
        {"Authorization": "Bearer mock_editor"},
        {"Authorization": "Bearer mock_manager"},
    )


# --- Router Coverage Tests ---


@pytest.mark.asyncio
async def test_submit_draft_not_found(
    override_dependency_gaps: None, mock_auth_headers_gaps: tuple[dict[str, str], dict[str, str]]
) -> None:
    editor_headers, _ = mock_auth_headers_gaps
    draft_id = uuid.uuid4()

    with patch("coreason_adlc_api.routers.workbench.get_draft_by_id", new=AsyncMock(return_value=None)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post(f"/api/v1/workbench/drafts/{draft_id}/submit", headers=editor_headers)
            assert resp.status_code == 404
            assert "Draft not found" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_approve_draft_not_manager(
    override_dependency_gaps: None, mock_auth_headers_gaps: tuple[dict[str, str], dict[str, str]]
) -> None:
    # Use editor token (who is not manager)
    editor_headers, _ = mock_auth_headers_gaps
    draft_id = uuid.uuid4()

    # Mock roles to NOT include MANAGER
    with patch("coreason_adlc_api.routers.workbench._get_user_roles", new=AsyncMock(return_value=["EDITOR"])):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post(f"/api/v1/workbench/drafts/{draft_id}/approve", headers=editor_headers)
            assert resp.status_code == 403
            assert "Only managers can approve drafts" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_reject_draft_not_manager(
    override_dependency_gaps: None, mock_auth_headers_gaps: tuple[dict[str, str], dict[str, str]]
) -> None:
    # Use editor token (who is not manager)
    editor_headers, _ = mock_auth_headers_gaps
    draft_id = uuid.uuid4()

    # Mock roles to NOT include MANAGER
    with patch("coreason_adlc_api.routers.workbench._get_user_roles", new=AsyncMock(return_value=["EDITOR"])):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post(f"/api/v1/workbench/drafts/{draft_id}/reject", headers=editor_headers)
            assert resp.status_code == 403
            assert "Only managers can reject drafts" in resp.json()["detail"]


# --- Service Coverage Tests ---


@pytest.fixture
def mock_pool() -> Generator[AsyncMock, None, None]:
    pool = AsyncMock()
    pool.fetchrow = AsyncMock()
    with patch("coreason_adlc_api.workbench.service.get_pool", return_value=pool):
        yield pool


@pytest.mark.asyncio
async def test_transition_draft_not_found(mock_pool: AsyncMock) -> None:
    mock_pool.fetchrow.return_value = None
    with pytest.raises(HTTPException) as exc:
        await transition_draft_status(uuid.uuid4(), uuid.uuid4(), ApprovalStatus.PENDING)
    assert exc.value.status_code == 404
    assert "Draft not found" in exc.value.detail


@pytest.mark.asyncio
async def test_transition_invalid(mock_pool: AsyncMock) -> None:
    # Scenario: Trying to go DRAFT -> APPROVED (Invalid)
    mock_pool.fetchrow.return_value = {"status": ApprovalStatus.DRAFT}

    with pytest.raises(HTTPException) as exc:
        await transition_draft_status(uuid.uuid4(), uuid.uuid4(), ApprovalStatus.APPROVED)

    assert exc.value.status_code == 409
    assert "Invalid transition" in exc.value.detail


@pytest.mark.asyncio
async def test_transition_invalid_from_pending(mock_pool: AsyncMock) -> None:
    # Scenario: PENDING -> DRAFT (Invalid - must be rejected first)
    mock_pool.fetchrow.return_value = {"status": ApprovalStatus.PENDING}

    with pytest.raises(HTTPException) as exc:
        await transition_draft_status(uuid.uuid4(), uuid.uuid4(), ApprovalStatus.DRAFT)

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_transition_success(mock_pool: AsyncMock) -> None:
    # Scenario: DRAFT -> PENDING (Valid)
    draft_id = uuid.uuid4()
    user_id = uuid.uuid4()

    # 1st call: Fetch status (DRAFT)
    # 2nd call: Update status (PENDING)

    updated_row = {
        "draft_id": draft_id,
        "user_uuid": user_id,
        "auc_id": "test-auc",
        "title": "Success",
        "oas_content": {},
        "status": ApprovalStatus.PENDING,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc)
    }

    mock_pool.fetchrow.side_effect = [
        {"status": ApprovalStatus.DRAFT},
        updated_row
    ]

    resp = await transition_draft_status(draft_id, user_id, ApprovalStatus.PENDING)

    assert resp.status == ApprovalStatus.PENDING
    assert mock_pool.fetchrow.call_count == 2
