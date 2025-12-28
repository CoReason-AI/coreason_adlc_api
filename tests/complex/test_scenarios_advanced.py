# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Generator
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from coreason_adlc_api.workbench.locking import AccessMode, acquire_draft_lock, verify_lock_for_update
from coreason_adlc_api.workbench.schemas import DraftCreate, DraftResponse
from fastapi import HTTPException


# --- Fixtures ---
@pytest.fixture
def mock_pool() -> Generator[MagicMock, None, None]:
    pool = MagicMock(spec=["acquire", "fetchrow", "execute", "fetch"])

    # Setup connection context manager
    conn = MagicMock()
    conn.fetchrow = AsyncMock()
    conn.execute = AsyncMock()
    conn.fetch = AsyncMock()

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
    pool.execute = AsyncMock()
    pool.fetch = AsyncMock()

    # Patch globally and locally
    with (
        patch("coreason_adlc_api.db.get_pool", return_value=pool),
        patch("coreason_adlc_api.workbench.locking.get_pool", return_value=pool),
        patch("coreason_adlc_api.workbench.service.get_pool", return_value=pool),
        patch("coreason_adlc_api.auth.identity.get_pool", return_value=pool),
    ):
        yield pool


# --- Complex Scenarios ---


@pytest.mark.asyncio
async def test_conflicting_safe_view_vs_edit(mock_pool: MagicMock) -> None:
    """
    Scenario:
    1. User A (Edit) holds lock.
    2. User B (Manager) attempts to acquire -> Should get SAFE_VIEW.
    3. User B attempts to EDIT -> Should fail (verify_lock_for_update).
    4. User A releases (expires). User B acquires -> Should get EDIT.
    """
    draft_id = uuid4()
    user_a = uuid4()
    user_b = uuid4()

    mock_conn = mock_pool.acquire.return_value.__aenter__.return_value

    # State
    lock_state = {"locked_by": user_a, "expiry": datetime.now(timezone.utc) + timedelta(seconds=30)}

    async def fetchrow_side_effect(query: str, *args: object) -> dict[str, object] | None:
        if "SELECT locked_by_user" in query:
            return {"locked_by_user": lock_state["locked_by"], "lock_expiry": lock_state["expiry"]}
        if "SELECT * FROM workbench.agent_drafts" in query:
            # Minimal mock for get_draft_by_id or similar checks
            return {
                "draft_id": draft_id,
                "locked_by_user": lock_state["locked_by"],
                "lock_expiry": lock_state["expiry"],
            }
        return None

    mock_conn.fetchrow.side_effect = fetchrow_side_effect
    mock_pool.fetchrow.side_effect = fetchrow_side_effect

    # 1. User B (Manager) attempts to acquire
    # Should get SAFE_VIEW because it is locked by User A
    mode = await acquire_draft_lock(draft_id, user_b, ["MANAGER"])
    assert mode == AccessMode.SAFE_VIEW

    # 2. User B attempts to EDIT (simulated via verify_lock_for_update)
    with pytest.raises(HTTPException) as exc:
        await verify_lock_for_update(draft_id, user_b)

    assert exc.value.status_code == 423
    assert "You must acquire a lock" in exc.value.detail

    # 3. Lock Expires
    lock_state["expiry"] = datetime.now(timezone.utc) - timedelta(seconds=1)

    # 4. User B attempts to acquire again
    # Should get EDIT now
    # Note: acquire_draft_lock will execute UPDATE to seize lock
    mode = await acquire_draft_lock(draft_id, user_b, ["MANAGER"])
    assert mode == AccessMode.EDIT


@pytest.mark.asyncio
async def test_project_switching_race_condition(mock_pool: MagicMock) -> None:
    """
    Scenario:
    User initiates a request. Auth middleware checks permissions (Project X allowed).
    While request is processing (simulated delay), Admin removes user from Project X.
    The request should complete successfully because permissions were validated at entry.
    """
    # We will simulate the Router logic here since we can't easily spawn a full HTTP server race
    # without significant boilerplate. We invoke the handler + dependency chain manually or conceptually.

    # 1. Setup Data
    user_oid = uuid4()
    group_oid = uuid4()
    auc_id = "project-alpha"
    identity = MagicMock(oid=user_oid, groups=[group_oid])

    # 2. Mock Dependency: map_groups_to_projects
    # Initial state: User HAS access
    with patch("coreason_adlc_api.routers.workbench.map_groups_to_projects", new_callable=AsyncMock) as mock_map:
        mock_map.return_value = [auc_id]

        # 3. Call Router Handler (simulating Entry)
        # Import inside test to patch locally
        from coreason_adlc_api.routers.workbench import create_new_draft

        draft_req = DraftCreate(auc_id=auc_id, title="Race Test", oas_content={})

        # We need to simulate "processing time" where the permission changes in the DB
        # But `create_new_draft` calls `_verify_project_access` (awaited) THEN `create_draft`.
        # Once `_verify` passes, it proceeds.

        # We'll use a side_effect on `create_draft` to verify that even if we change the mapping
        # externally, it doesn't matter because verify happened before.

        async def slow_create(*args: Any, **kwargs: Any) -> DraftResponse:
            # Simulate external change: The DB now says NO access
            # But since verify was already called, this shouldn't stop execution
            mock_map.return_value = []
            await asyncio.sleep(0.1)
            # Return fake response
            return DraftResponse(
                draft_id=uuid4(),
                user_uuid=user_oid,
                auc_id=auc_id,
                title="Race Test",
                oas_content={},
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )

        with patch("coreason_adlc_api.routers.workbench.create_draft", side_effect=slow_create):
            # ACT
            response = await create_new_draft(draft_req, identity)

            # ASSERT
            assert response.title == "Race Test"
            # Verify valid was checked
            mock_map.assert_called_once()


@pytest.mark.asyncio
async def test_expired_jwt_during_long_operation(mock_oidc_factory: Any) -> None:
    """
    Scenario:
    JWT is valid at T=0.
    Operation takes 6 seconds.
    JWT expires at T=5.
    Result should be success (Validation at entry only).
    """
    # 1. Generate a token that expires in 5 seconds
    exp = datetime.now(timezone.utc) + timedelta(seconds=5)
    # Using the factory helper to sign with RS256
    token = mock_oidc_factory(
        {"oid": str(uuid4()), "email": "test@example.com", "groups": [], "name": "Test User", "exp": exp}
    )
    header = f"Bearer {token}"

    # 2. Validate Token (Entry)
    from coreason_adlc_api.auth.identity import parse_and_validate_token

    identity = await parse_and_validate_token(header)
    assert identity.email == "test@example.com"

    # 3. Simulate Long Op (sleep past expiration)
    await asyncio.sleep(6)

    # Now token is technically expired.
    # But we already have the `identity` object.
    # The system does not re-validate.

    # Prove that if we tried to validate NOW, it would fail
    with pytest.raises(HTTPException) as exc:
        await parse_and_validate_token(header)
    assert exc.value.status_code == 401
    assert "Token has expired" in exc.value.detail

    # But the operation logic (represented by having `identity`) continues fine.
    assert identity.email == "test@example.com"


@pytest.mark.asyncio
async def test_safe_view_upgrade_attempt(mock_pool: MagicMock) -> None:
    """
    Scenario: User holds SAFE_VIEW (via Manager override).
    Attempts to 'upgrade' to EDIT while original owner still holds it.
    Should fail to acquire EDIT lock.
    """
    draft_id = uuid4()
    manager_uuid = uuid4()
    owner_uuid = uuid4()  # Someone else

    # Mock DB state: Locked by owner
    future = datetime.now(timezone.utc) + timedelta(seconds=30)

    async def fetchrow_side_effect(query: str, *args: object) -> dict[str, object] | None:
        if "SELECT locked_by_user" in query:
            return {"locked_by_user": owner_uuid, "lock_expiry": future}
        return None

    mock_pool.acquire.return_value.__aenter__.return_value.fetchrow.side_effect = fetchrow_side_effect

    # Manager calls acquire again (hoping to edit)
    mode = await acquire_draft_lock(draft_id, manager_uuid, ["MANAGER"])

    # Should still be SAFE_VIEW, NOT EDIT
    assert mode == AccessMode.SAFE_VIEW
