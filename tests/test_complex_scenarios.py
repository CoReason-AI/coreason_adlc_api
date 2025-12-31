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
import uuid
from datetime import datetime, timedelta, timezone
from typing import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from coreason_adlc_api.workbench.schemas import AccessMode, DraftCreate, DraftUpdate, acquire_draft_lock
from coreason_adlc_api.workbench.service import create_draft, update_draft


# --- Fixtures ---
@pytest.fixture
def mock_pool() -> Generator[MagicMock, None, None]:
    pool = MagicMock(spec=["acquire", "fetchrow", "execute"])

    # Setup connection context manager
    conn = MagicMock()
    conn.fetchrow = AsyncMock()
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
    pool.execute = AsyncMock()

    # Patch globally and locally
    with (
        patch("coreason_adlc_api.db.get_pool", return_value=pool),
        patch("coreason_adlc_api.workbench.locking.get_pool", return_value=pool),
        patch("coreason_adlc_api.workbench.service.get_pool", return_value=pool),
    ):
        yield pool


# --- Complex Tests ---


@pytest.mark.asyncio
async def test_race_condition_lock_acquisition(mock_pool: MagicMock) -> None:
    """
    Simulate two users (Alice and Bob) trying to lock the same draft simultaneously.
    Only one should succeed.
    """
    draft_id = uuid.uuid4()
    alice_id = uuid.uuid4()
    bob_id = uuid.uuid4()

    mock_conn = mock_pool.acquire.return_value.__aenter__.return_value

    # State tracking to simulate DB race
    # We use a side_effect to return "Not Locked" first, then "Locked by Alice" for the second call?
    # Or purely rely on the fact that `SELECT FOR UPDATE` (mocked transaction) serializes them in real DB.
    # In Mock world, we simulate serial execution order.

    # Scenario: Alice calls acquire -> Mock returns unlocked -> Alice updates to Locked.
    # Bob calls acquire -> Mock returns Locked -> Bob gets 423.

    # We define a stateful side effect for fetchrow
    lock_state = {"locked_by": None, "expiry": None}

    async def fetchrow_side_effect(query: str, *args: object) -> dict[str, object] | None:
        if "SELECT locked_by_user" in query:
            # Return current state
            return {"locked_by_user": lock_state["locked_by"], "lock_expiry": lock_state["expiry"]}
        return None

    async def execute_side_effect(query: str, *args: object) -> None:
        if "UPDATE workbench.agent_drafts SET locked_by_user" in query:
            # args: (user_uuid, new_expiry, draft_id)
            lock_state["locked_by"] = args[0]  # type: ignore
            lock_state["expiry"] = args[1]  # type: ignore

    mock_conn.fetchrow.side_effect = fetchrow_side_effect
    mock_conn.execute.side_effect = execute_side_effect

    # Run concurrent tasks
    # In a real asyncio loop, one will run to await point, then other might run.
    # `acquire_draft_lock` awaits `pool.acquire`, then `conn.transaction`, then `fetchrow`.

    # We launch both. One will "win" (process first in our mocked serial logic)
    results = await asyncio.gather(
        acquire_draft_lock(draft_id, alice_id, []), acquire_draft_lock(draft_id, bob_id, []), return_exceptions=True
    )

    # One should be AccessMode.EDIT, one should be HTTPException(423)
    successes = [r for r in results if r == AccessMode.EDIT]
    failures = [r for r in results if isinstance(r, HTTPException) and r.status_code == 423]

    assert len(successes) == 1
    assert len(failures) == 1

    # Verify final state is locked by winner
    assert lock_state["locked_by"] in (alice_id, bob_id)


@pytest.mark.asyncio
async def test_zombie_lock_takeover(mock_pool: MagicMock) -> None:
    """
    Scenario: User A locks draft. Time passes (expiry). User B tries to lock.
    User B should succeed because lock is expired ("Zombie Lock").
    """
    draft_id = uuid.uuid4()
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()

    mock_conn = mock_pool.acquire.return_value.__aenter__.return_value

    # Initial state: Locked by A, but expired
    expired_time = datetime.now(timezone.utc) - timedelta(seconds=5)
    mock_conn.fetchrow.return_value = {"locked_by_user": user_a, "lock_expiry": expired_time}

    # User B attempts to acquire
    mode = await acquire_draft_lock(draft_id, user_b, [])

    # Should succeed
    assert mode == AccessMode.EDIT

    # Verify DB update was called to overwrite User A with User B
    mock_conn.execute.assert_called_once()
    args = mock_conn.execute.call_args[0]
    assert args[1] == user_b  # New owner (arg1)


@pytest.mark.asyncio
async def test_update_on_deleted_draft(mock_pool: MagicMock) -> None:
    """
    Scenario: User tries to update a draft that was soft-deleted by another process
    concurrently (between lock check and update).
    """
    draft_id = uuid.uuid4()
    user_id = uuid.uuid4()

    # Setup: verify_lock succeeds
    future = datetime.now(timezone.utc) + timedelta(minutes=1)

    # We mocked `get_pool` so `verify_lock_for_update` uses `mock_pool.fetchrow`.
    # `update_draft` also uses `mock_pool.fetchrow`.

    # Side effect:
    # 1. First call (verify_lock): Returns valid lock row.
    # 2. Second call (update): Returns None (simulating row deleted or not found by UPDATE WHERE clause).

    mock_pool.fetchrow.side_effect = [
        {"locked_by_user": user_id, "lock_expiry": future},  # verify_lock
        None,  # update returning * (not found)
    ]

    update = DraftUpdate(title="Ghost Draft")

    with pytest.raises(HTTPException) as exc:
        await update_draft(draft_id, update, user_id)

    assert exc.value.status_code == 404
    assert "Draft not found" in exc.value.detail


@pytest.mark.asyncio
async def test_huge_payload_handling(mock_pool: MagicMock) -> None:
    """
    Verify system handles 10MB JSON payload without crashing (memory/serialization check).
    """
    user_id = uuid.uuid4()
    huge_json = {"data": "x" * 10 * 1024 * 1024}  # 10MB string

    draft = DraftCreate(auc_id="big-data-project", title="Heavy Agent", oas_content=huge_json)

    mock_pool.fetchrow.return_value = {
        "draft_id": uuid.uuid4(),
        "user_uuid": user_id,
        "auc_id": "big-data-project",
        "title": "Heavy Agent",
        "oas_content": {},  # Mock response doesn't need full echo
        "runtime_env": None,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }

    # Execute
    res = await create_draft(draft, user_id)

    assert res.title == "Heavy Agent"
    # Ensure it was passed to DB
    args = mock_pool.fetchrow.call_args[0]
    # Check that json.dumps was called on huge payload (args[3] or similar)
    # query is 1st arg. user_uuid 2nd. auc_id 3rd. title 4th. content 5th.
    assert len(args[4]) >= 10 * 1024 * 1024  # Serialized string length
