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
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from coreason_adlc_api.app import app
from coreason_adlc_api.auth.identity import parse_and_validate_token
from coreason_adlc_api.workbench.schemas import ApprovalStatus, DraftResponse
from fastapi import HTTPException, Request
from httpx import ASGITransport, AsyncClient


# --- Mocks ---
@pytest.fixture
def mock_auth_headers() -> tuple[dict[str, str], dict[str, str]]:
    """
    Returns (Editor Headers, Manager Headers)
    """
    # Editor
    editor_uuid = str(uuid.uuid4())
    editor_token = "mock_editor_token"

    # Manager
    manager_uuid = str(uuid.uuid4())
    manager_token = "mock_manager_token"

    return (
        {"Authorization": f"Bearer {editor_token}", "X-User-ID": editor_uuid},
        {"Authorization": f"Bearer {manager_token}", "X-User-ID": manager_uuid},
    )


async def mock_parse_token(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")

    mock_id = MagicMock()
    if token == "mock_editor_token":
        mock_id.oid = uuid.UUID(int=1)
        mock_id.groups = [uuid.uuid4()]
    elif token == "mock_manager_token":
        mock_id.oid = uuid.UUID(int=2)
        mock_id.groups = [uuid.uuid4()]
    else:
        # Fallback or error
        raise HTTPException(status_code=401, detail="Invalid token")
    return mock_id


@pytest.fixture(autouse=True)
def override_dependency():
    app.dependency_overrides[parse_and_validate_token] = mock_parse_token
    yield
    app.dependency_overrides = {}


@pytest.mark.asyncio
async def test_workflow_happy_path(mock_auth_headers: tuple[dict[str, str], dict[str, str]]) -> None:
    """
    Scenario:
    1. Editor creates Draft (DRAFT)
    2. Editor Submits (PENDING)
    3. Manager Approves (APPROVED)
    """
    editor_headers, manager_headers = mock_auth_headers
    draft_id = uuid.uuid4()
    editor_uid = uuid.UUID(int=1)
    manager_uid = uuid.UUID(int=2)

    # Mock Objects
    draft_base = DraftResponse(
        draft_id=draft_id,
        user_uuid=editor_uid,
        auc_id="project-alpha",
        title="Workflow Agent",
        oas_content={},
        status=ApprovalStatus.DRAFT,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc)
    )

    with (
        patch("coreason_adlc_api.routers.workbench.get_draft_by_id", new=AsyncMock()) as mock_get,
        patch("coreason_adlc_api.routers.workbench.transition_draft_status", new=AsyncMock()) as mock_trans,
        patch("coreason_adlc_api.routers.workbench.map_groups_to_projects", return_value=["project-alpha"]),
        patch("coreason_adlc_api.routers.workbench._get_user_roles", new=AsyncMock()) as mock_roles
    ):
        # Setup Client
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:

            # --- 1. Create (Already exists in mock, so we skip to Submit) ---
            # Pre-condition: Status is DRAFT
            mock_get.return_value = draft_base

            # --- 2. Submit ---
            # Mock transition to return PENDING
            pending_draft = draft_base.model_copy(update={"status": ApprovalStatus.PENDING})
            mock_trans.return_value = pending_draft

            # Act
            resp = await ac.post(
                f"/api/v1/workbench/drafts/{draft_id}/submit",
                headers=editor_headers
            )

            assert resp.status_code == 200, f"Submit failed: {resp.text}"
            assert resp.json()["status"] == "PENDING"

            # Verify transition called with PENDING
            mock_trans.assert_called_with(draft_id, editor_uid, ApprovalStatus.PENDING)

            # --- 3. Approve ---
            # Mock transition to return APPROVED
            approved_draft = draft_base.model_copy(update={"status": ApprovalStatus.APPROVED})
            mock_trans.return_value = approved_draft

            # Mock Manager Role
            mock_roles.return_value = ["MANAGER"]

            resp = await ac.post(
                f"/api/v1/workbench/drafts/{draft_id}/approve",
                headers=manager_headers
            )

            assert resp.status_code == 200, f"Approve failed: {resp.text}"
            assert resp.json()["status"] == "APPROVED"

            # Verify transition called with APPROVED (no roles arg)
            mock_trans.assert_called_with(draft_id, manager_uid, ApprovalStatus.APPROVED)


@pytest.mark.asyncio
async def test_workflow_rejection_loop(mock_auth_headers: tuple[dict[str, str], dict[str, str]]) -> None:
    """
    Scenario:
    1. Editor Submits (PENDING)
    2. Manager Rejects (REJECTED)
    3. Editor Updates (DRAFT/REJECTED -> OK)
    4. Editor Submits Again (PENDING)
    """
    editor_headers, manager_headers = mock_auth_headers
    draft_id = uuid.uuid4()
    editor_uid = uuid.UUID(int=1)

    draft_base = DraftResponse(
        draft_id=draft_id,
        user_uuid=editor_uid,
        auc_id="project-alpha",
        title="Workflow Agent",
        oas_content={},
        status=ApprovalStatus.PENDING, # Starting at PENDING for this test
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc)
    )

    with (
        patch("coreason_adlc_api.routers.workbench.get_draft_by_id", new=AsyncMock()) as mock_get,
        patch("coreason_adlc_api.routers.workbench.transition_draft_status", new=AsyncMock()) as mock_trans,
        patch("coreason_adlc_api.routers.workbench.update_draft", new=AsyncMock()) as mock_update,
        patch("coreason_adlc_api.routers.workbench.map_groups_to_projects", return_value=["project-alpha"]),
        patch("coreason_adlc_api.routers.workbench._get_user_roles", new=AsyncMock()) as mock_roles
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:

            # --- 1. Manager Rejects ---
            mock_get.return_value = draft_base
            mock_roles.return_value = ["MANAGER"]
            rejected_draft = draft_base.model_copy(update={"status": ApprovalStatus.REJECTED})
            mock_trans.return_value = rejected_draft

            resp = await ac.post(
                f"/api/v1/workbench/drafts/{draft_id}/reject",
                headers=manager_headers
            )
            assert resp.status_code == 200, f"Reject failed: {resp.text}"
            assert resp.json()["status"] == "REJECTED"

            # --- 2. Editor Updates ---
            # Editor roles (not manager)
            mock_roles.return_value = []

            # Update requires the service to check status.
            # Since we are mocking `update_draft` (service), we assume the service layer test covers the blocking logic.
            # Here we just verify the call is made.

            # But wait, `update_existing_draft` router endpoint calls `update_draft`
            # The rejection put it in REJECTED state.
            mock_get.return_value = rejected_draft # Current state in DB is REJECTED

            mock_update.return_value = rejected_draft.model_copy(update={"title": "Fixed Title"})

            resp = await ac.put(
                f"/api/v1/workbench/drafts/{draft_id}",
                json={"title": "Fixed Title"},
                headers=editor_headers
            )
            assert resp.status_code == 200, f"Update failed: {resp.text}"

            # --- 3. Submit Again ---
            pending_draft = rejected_draft.model_copy(update={"status": ApprovalStatus.PENDING})
            mock_trans.return_value = pending_draft

            resp = await ac.post(
                f"/api/v1/workbench/drafts/{draft_id}/submit",
                headers=editor_headers
            )
            assert resp.status_code == 200, f"Resubmit failed: {resp.text}"
            assert resp.json()["status"] == "PENDING"


@pytest.mark.asyncio
async def test_state_locking_on_update() -> None:
    """
    Verify that `update_draft` throws 409 if status is PENDING or APPROVED.
    We need to test the *service* logic here, or ensure the router integration hits that logic.
    Since we mocked `update_draft` in previous tests, we should check `test_workbench_service` or
    add a specific integration test here where we mock the DB state but execute the service function.
    """
    # We will import the actual service function to test the logic
    from coreason_adlc_api.workbench.service import update_draft

    draft_id = uuid.uuid4()
    user_id = uuid.uuid4()

    # Mock Pool
    pool = MagicMock()

    # 1. Mock 'check_status_for_update' query result -> PENDING
    # The service calls:
    #   verify_lock_for_update (mocked)
    #   _check_status_for_update (DB call)

    row_pending = {"status": ApprovalStatus.PENDING}

    mock_conn = MagicMock()
    mock_conn.fetchrow = AsyncMock(return_value=row_pending)

    # Setup context manager for acquire
    pool.acquire.return_value.__aenter__.return_value = mock_conn
    pool.fetchrow = AsyncMock(return_value=row_pending)

    with (
        patch("coreason_adlc_api.workbench.service.get_pool", return_value=pool),
        patch("coreason_adlc_api.workbench.service.verify_lock_for_update", new=AsyncMock()),
        # We need to catch the exception
        pytest.raises(HTTPException) as exc
    ):
        await update_draft(draft_id, MagicMock(title="No Edit"), user_id)

    assert exc.value.status_code == 409
    # Adjusted assertion to match format: "Cannot edit draft in 'PENDING' status..."
    assert "Cannot edit draft in" in exc.value.detail
    assert "PENDING" in exc.value.detail


@pytest.mark.asyncio
async def test_invalid_transitions() -> None:
    """
    Verify `transition_draft_status` logic forbids DRAFT -> APPROVED directly.
    """
    from coreason_adlc_api.workbench.service import transition_draft_status

    draft_id = uuid.uuid4()
    user_id = uuid.uuid4()

    pool = MagicMock()
    # Current status: DRAFT
    # Fix: Make fetchrow an AsyncMock to be awaitable
    pool.fetchrow = AsyncMock(return_value={"status": ApprovalStatus.DRAFT})

    with (
        patch("coreason_adlc_api.workbench.service.get_pool", return_value=pool),
        pytest.raises(HTTPException) as exc
    ):
        await transition_draft_status(draft_id, user_id, ApprovalStatus.APPROVED)

    assert exc.value.status_code == 409
    assert "Invalid transition" in exc.value.detail
