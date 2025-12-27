# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

from typing import Any, Dict, Generator
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from coreason_adlc_api.auth.identity import UserIdentity
from coreason_adlc_api.routers.workbench import (
    create_new_draft,
    get_draft,
    list_drafts,
)
from coreason_adlc_api.workbench.schemas import DraftCreate
from fastapi import HTTPException


@pytest.fixture
def mock_identity() -> UserIdentity:
    return UserIdentity(
        oid=uuid4(),
        email="test@example.com",
        groups=[uuid4()],
        full_name="Test User",
    )


@pytest.fixture
def mock_pool() -> Generator[MagicMock, None, None]:
    pool = MagicMock()

    # Setup connection context manager
    conn = MagicMock()
    conn.fetchrow = AsyncMock()
    conn.fetch = AsyncMock()
    conn.execute = AsyncMock()

    conn_cm = MagicMock()
    conn_cm.__aenter__ = AsyncMock(return_value=conn)
    conn_cm.__aexit__ = AsyncMock(return_value=None)
    pool.acquire.return_value = conn_cm

    txn_cm = MagicMock()
    txn_cm.__aenter__ = AsyncMock(return_value=None)
    txn_cm.__aexit__ = AsyncMock(return_value=None)
    conn.transaction.return_value = txn_cm

    # Configure pool methods
    pool.fetchrow = AsyncMock()
    pool.fetch = AsyncMock()
    pool.execute = AsyncMock()

    yield pool


@pytest.mark.asyncio
async def test_rbac_session_revocation(
    mock_identity: UserIdentity, mock_pool: MagicMock
) -> None:
    """
    Test that a user's access is revoked immediately if their group mapping changes,
    even if they have a valid token (simulated by same identity object).
    """
    auc_id = "proj-sensitive"

    # Mock map_groups_to_projects to verify RBAC
    # We patch it where it is imported in routers.workbench
    with (
        patch(
            "coreason_adlc_api.routers.workbench.map_groups_to_projects",
            new_callable=AsyncMock,
        ) as mock_map,
        patch(
            "coreason_adlc_api.routers.workbench.get_drafts", new_callable=AsyncMock
        ) as mock_get_drafts,
    ):
        # 1. Initial State: Access Allowed
        mock_map.return_value = [auc_id]
        mock_get_drafts.return_value = []

        response = await list_drafts(auc_id, identity=mock_identity)
        assert response == []

        # 2. State Change: Access Revoked (e.g. removed from AD group)
        mock_map.return_value = []  # No projects allowed

        # 3. Verify Access Denied
        with pytest.raises(HTTPException) as exc:
            await list_drafts(auc_id, identity=mock_identity)

        assert exc.value.status_code == 403
        assert "User is not authorized" in exc.value.detail


@pytest.mark.asyncio
async def test_cross_project_creation_denied(
    mock_identity: UserIdentity, mock_pool: MagicMock
) -> None:
    """
    Test that a user cannot create a draft in a project they don't have access to.
    """
    allowed_project = "proj-A"
    target_project = "proj-B"  # No access

    draft_input = DraftCreate(
        auc_id=target_project, title="Malicious Draft", oas_content={}
    )

    with patch(
        "coreason_adlc_api.routers.workbench.map_groups_to_projects",
        new_callable=AsyncMock,
    ) as mock_map:
        # Mock only allowing proj-A
        mock_map.return_value = [allowed_project]

        # Patch create_draft to ensure it's NOT called
        with patch(
            "coreason_adlc_api.routers.workbench.create_draft", new_callable=AsyncMock
        ) as mock_create:
            with pytest.raises(HTTPException) as exc:
                await create_new_draft(draft_input, identity=mock_identity)

            assert exc.value.status_code == 403
            mock_create.assert_not_called()


@pytest.mark.asyncio
async def test_cross_project_lock_acquisition_denied(
    mock_identity: UserIdentity, mock_pool: MagicMock
) -> None:
    """
    Test scenario where a user tries to access (and lock) a draft from a project they don't have access to.
    This verifies that we don't accidentally lock the resource before checking permission.
    """
    draft_id = uuid4()
    target_project = "proj-secret"

    # We need to mock acquire_draft_lock to track if it was called
    # and get_draft_by_id to return the draft structure

    # Logic in router.get_draft:
    # 1. roles = await _get_user_roles(...)
    # 2. draft = await get_draft_by_id(...)  <-- This internally calls acquire_draft_lock!
    # 3. _verify_project_access(...)

    # If get_draft_by_id locks it, we have a problem (DoS potential).
    # Ideally, get_draft_by_id should check permissions or we should check permissions before calling it.
    # But get_draft_by_id needs the draft ID to find the AUC_ID to check permissions!
    # Catch-22 unless we do a "peek" first.

    with patch("coreason_adlc_api.routers.workbench.get_pool", return_value=mock_pool):
        with (
            patch(
                "coreason_adlc_api.routers.workbench.map_groups_to_projects",
                new_callable=AsyncMock,
            ) as mock_map,
            patch(
                "coreason_adlc_api.routers.workbench._get_user_roles",
                new_callable=AsyncMock,
            ) as mock_roles,
        ):
            # User has NO access to 'proj-secret'
            mock_map.return_value = ["proj-public"]
            mock_roles.return_value = []

            # Mock the service calls
            # We want to see if acquire_draft_lock is called.
            # Since get_draft_by_id calls it, we should mock get_draft_by_id to simulating "Success finding draft"
            # BUT we also want to know if it LOCKED it.

            # Let's inspect the real flow by NOT mocking get_draft_by_id, but mocking the DB calls it makes.
            # router -> get_draft_by_id -> acquire_draft_lock -> DB Update

            # Patching internal service functions to spy on them
            with patch(
                "coreason_adlc_api.routers.workbench.get_draft_by_id"
            ) as mock_get_draft_service:
                # Setup service return value (simulating it found and locked the draft)
                mock_response = MagicMock()
                mock_response.auc_id = target_project
                mock_get_draft_service.return_value = mock_response

                # Executing the request
                with pytest.raises(HTTPException) as exc:
                    await get_draft(draft_id, identity=mock_identity)

                # Assert 403 Forbidden
                assert exc.value.status_code == 403

                # NOW: Did we lock it?
                # The router called `get_draft_by_id` BEFORE `_verify_project_access`.
                # So `mock_get_draft_service` WAS called.
                mock_get_draft_service.assert_called_once()

                # In a real scenario, this means the lock was acquired (DB updated).
                # This test documents the behavior.
                # Ideally, we should ASSERT that the lock is released or not taken.
                # But since `get_draft_by_id` is a black box here returning a mocked object,
                # we confirm that the Router logic *attempts* to process the draft (and thus locks it)
                # before checking permission.

                # NOTE: This confirms the potential vulnerability (DoS).
                # A user can lock a draft they cannot see.


@pytest.mark.asyncio
async def test_malformed_json_injection(
    mock_identity: UserIdentity, mock_pool: MagicMock
) -> None:
    """
    Test handling of potentially malicious JSON payloads (depth, size).
    """
    deeply_nested: Dict[str, Any] = {}
    current = deeply_nested
    for _ in range(100):
        current["next"] = {}
        current = current["next"]

    draft_input = DraftCreate(auc_id="proj-A", title="Deep Draft", oas_content=deeply_nested)

    with patch(
        "coreason_adlc_api.routers.workbench.map_groups_to_projects",
        new_callable=AsyncMock,
    ) as mock_map:
        mock_map.return_value = ["proj-A"]

        with patch(
            "coreason_adlc_api.routers.workbench.create_draft", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = MagicMock(title="Deep Draft")

            response = await create_new_draft(draft_input, identity=mock_identity)

            assert response.title == "Deep Draft"
            # Verify it didn't crash
