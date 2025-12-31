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
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.engine import Result

from coreason_adlc_api.workbench.locking import AccessMode, acquire_draft_lock
from coreason_adlc_api.workbench.schemas import DraftCreate, DraftUpdate
from coreason_adlc_api.workbench.service import create_draft, update_draft


# --- Complex Tests ---


@pytest.mark.asyncio
async def test_race_condition_lock_acquisition(mock_db_session: AsyncMock) -> None:
    """
    Simulate two users (Alice and Bob) trying to lock the same draft simultaneously.
    Only one should succeed.
    """
    draft_id = uuid.uuid4()
    alice_id = uuid.uuid4()
    bob_id = uuid.uuid4()

    # State tracking to simulate DB race
    lock_state: dict[str, Any] = {"locked_by": None, "expiry": None}

    def create_result(row: Any) -> MagicMock:
        mock_res = MagicMock(spec=Result)
        mock_res.fetchone.return_value = row
        return mock_res

    async def execute_side_effect(stmt: Any, params: Any = None) -> MagicMock:
        query = str(stmt)
        if "SELECT locked_by_user" in query:
             # Return current state.
             # workbench/locking.py expects row[0], row[1]
             return create_result((lock_state["locked_by"], lock_state["expiry"]))

        if "UPDATE workbench.agent_drafts" in query:
            # params: {"user_uuid": ..., "new_expiry": ..., "draft_id": ...}
            if params and "user_uuid" in params:
                lock_state["locked_by"] = params["user_uuid"]
                lock_state["expiry"] = params["new_expiry"]
            return create_result(None) # UPDATE returns nothing relevant usually unless RETURNING

        return create_result(None)

    mock_db_session.execute.side_effect = execute_side_effect

    # Run concurrent tasks
    # Since we are mocking session, we can't easily simulate two different sessions unless we do more complex setup.
    # But `acquire_draft_lock` takes a session. We can pass the same mock session or different ones.
    # Let's assume we pass the same mock session for simplicity of state sharing in test.

    # We launch both.
    results = await asyncio.gather(
        acquire_draft_lock(mock_db_session, draft_id, alice_id, []),
        acquire_draft_lock(mock_db_session, draft_id, bob_id, []),
        return_exceptions=True
    )

    # One should be AccessMode.EDIT, one should be HTTPException(423)
    successes = [r for r in results if r == AccessMode.EDIT]
    failures = [r for r in results if isinstance(r, HTTPException) and r.status_code == 423]

    assert len(successes) == 1
    assert len(failures) == 1

    # Verify final state is locked by winner
    assert lock_state["locked_by"] in (alice_id, bob_id)


@pytest.mark.asyncio
async def test_zombie_lock_takeover(mock_db_session: AsyncMock) -> None:
    """
    Scenario: User A locks draft. Time passes (expiry). User B tries to lock.
    User B should succeed because lock is expired ("Zombie Lock").
    """
    draft_id = uuid.uuid4()
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()

    # Initial state: Locked by A, but expired
    expired_time = datetime.now(timezone.utc) - timedelta(seconds=5)

    # Mock return for SELECT locked_by_user
    mock_res = MagicMock(spec=Result)
    mock_res.fetchone.return_value = (user_a, expired_time)
    mock_db_session.execute.return_value = mock_res

    # User B attempts to acquire
    mode = await acquire_draft_lock(mock_db_session, draft_id, user_b, [])

    # Should succeed
    assert mode == AccessMode.EDIT

    # Verify DB update was called to overwrite User A with User B
    # Check calls to execute.
    # 1. SELECT ...
    # 2. UPDATE ...
    assert mock_db_session.execute.call_count >= 2

    # Check the update call params
    update_call = [
        c for c in mock_db_session.execute.call_args_list if "UPDATE workbench.agent_drafts" in str(c[0][0])
    ][0]
    params = update_call[0][1]  # Second arg is params dict
    assert params["user_uuid"] == user_b


@pytest.mark.asyncio
async def test_update_on_deleted_draft(mock_db_session: AsyncMock) -> None:
    """
    Scenario: User tries to update a draft that was soft-deleted by another process
    concurrently (between lock check and update).
    """
    draft_id = uuid.uuid4()
    user_id = uuid.uuid4()
    future = datetime.now(timezone.utc) + timedelta(minutes=1)

    # Side effect:
    # 1. First call (verify_lock): Returns valid lock row.
    # 2. Second call (check_status): Returns None (or status DRAFT) - let's assume it returns None if deleted.
    #    Actually update_draft calls verify_lock then check_status then update.
    #    If check_status returns row with status DRAFT it passes.
    #    Then UPDATE returns nothing.

    def execute_side_effect(stmt: Any, params: Any = None) -> MagicMock:
        query = str(stmt)
        mock_res = MagicMock(spec=Result)

        if "SELECT locked_by_user" in query: # verify_lock
            mock_res.fetchone.return_value = (user_id, future)
        elif "SELECT status" in query: # check_status
            mock_res.fetchone.return_value = ("DRAFT",)
        elif "UPDATE workbench.agent_drafts" in query:
             # update returning * (not found)
             mock_res.mappings.return_value.fetchone.return_value = None
        else:
             mock_res.fetchone.return_value = None

        return mock_res

    mock_db_session.execute.side_effect = execute_side_effect

    update = DraftUpdate(title="Ghost Draft")

    with pytest.raises(HTTPException) as exc:
        await update_draft(mock_db_session, draft_id, update, user_id)

    assert exc.value.status_code == 404
    assert "Draft not found" in exc.value.detail


@pytest.mark.asyncio
async def test_huge_payload_handling(mock_db_session: AsyncMock) -> None:
    """
    Verify system handles 10MB JSON payload without crashing (memory/serialization check).
    """
    user_id = uuid.uuid4()
    huge_json = {"data": "x" * 10 * 1024 * 1024}  # 10MB string

    draft = DraftCreate(auc_id="big-data-project", title="Heavy Agent", oas_content=huge_json)

    # Mock RETURNING *
    mock_res = MagicMock(spec=Result)
    row = {
        "draft_id": uuid.uuid4(),
        "user_uuid": user_id,
        "auc_id": "big-data-project",
        "title": "Heavy Agent",
        "oas_content": {},  # Mock response doesn't need full echo
        "runtime_env": None,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    # Mock mappings().fetchone() behavior
    # We need to simulate the Result object properly
    mock_res.mappings.return_value.fetchone.return_value = row

    # Also support dict(row) behavior if needed by implementation
    # But since service uses dict(row), and row is the return value of fetchone(),
    # row MUST be something that can be passed to dict().
    # The current mock 'row' is a dict. dict(dict) works.

    mock_db_session.execute.return_value = mock_res

    # Execute
    res = await create_draft(mock_db_session, draft, user_id)

    assert res.title == "Heavy Agent"

    # Check that json.dumps was called on huge payload
    call_args = mock_db_session.execute.call_args
    params = call_args[0][1]
    assert len(params["oas_content"]) >= 10 * 1024 * 1024
