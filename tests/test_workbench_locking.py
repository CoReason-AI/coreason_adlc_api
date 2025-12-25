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
from datetime import timedelta, timezone
from typing import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from coreason_adlc_api.workbench.locking import AccessMode, acquire_draft_lock, refresh_lock, verify_lock_for_update


@pytest.fixture
def mock_pool() -> Generator[MagicMock, None, None]:
    # Use explicit MagicMock, ensure it is not treated as AsyncMock
    pool = MagicMock(spec=["acquire", "fetchrow", "execute"])

    # Setup connection context manager
    conn = MagicMock()  # Connection object itself is not async, methods are
    conn.fetchrow = AsyncMock()
    conn.execute = AsyncMock()

    # pool.acquire() returns an object that can be used in 'async with'
    # We create a MagicMock that implements __aenter__ and __aexit__
    # AsyncMock can be used as context manager, but let's be explicit

    conn_cm = MagicMock()
    conn_cm.__aenter__ = AsyncMock(return_value=conn)
    conn_cm.__aexit__ = AsyncMock(return_value=None)
    pool.acquire.return_value = conn_cm

    # conn.transaction() context manager
    txn_cm = MagicMock()
    txn_cm.__aenter__ = AsyncMock(return_value=None)
    txn_cm.__aexit__ = AsyncMock(return_value=None)
    conn.transaction.return_value = txn_cm

    # Configure pool methods to be awaitable
    pool.fetchrow = AsyncMock()
    pool.execute = AsyncMock()

    # Configure pool methods to be awaitable
    pool.fetchrow = AsyncMock()
    pool.execute = AsyncMock()

    with patch("coreason_adlc_api.workbench.locking.get_pool", return_value=pool):
        yield pool


@pytest.mark.asyncio
async def test_acquire_lock_not_found(mock_pool: MagicMock) -> None:
    mock_conn = mock_pool.acquire.return_value.__aenter__.return_value
    mock_conn.fetchrow.return_value = None

    with pytest.raises(HTTPException) as exc:
        await acquire_draft_lock(uuid.uuid4(), uuid.uuid4(), [])
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_acquire_lock_new(mock_pool: MagicMock) -> None:
    # Setup: Not locked
    draft_id = uuid.uuid4()
    user_id = uuid.uuid4()

    mock_conn = mock_pool.acquire.return_value.__aenter__.return_value

    # fetchrow returns current state (not locked)
    mock_conn.fetchrow.return_value = {"locked_by_user": None, "lock_expiry": None}

    mode = await acquire_draft_lock(draft_id, user_id, [])

    assert mode == AccessMode.EDIT
    mock_conn.execute.assert_awaited()  # Should update lock
    args = mock_conn.execute.call_args[0]
    assert "UPDATE" in args[0]
    assert args[1] == user_id


@pytest.mark.asyncio
async def test_acquire_lock_conflict(mock_pool: MagicMock) -> None:
    # Setup: Locked by another user
    draft_id = uuid.uuid4()
    user_id = uuid.uuid4()
    other_user = uuid.uuid4()
    future = datetime.datetime.now(timezone.utc) + timedelta(minutes=1)

    mock_conn = mock_pool.acquire.return_value.__aenter__.return_value
    mock_conn.fetchrow.return_value = {"locked_by_user": other_user, "lock_expiry": future}

    with pytest.raises(HTTPException) as exc:
        await acquire_draft_lock(draft_id, user_id, [])

    assert exc.value.status_code == 423
    mock_conn.execute.assert_not_called()


@pytest.mark.asyncio
async def test_acquire_lock_manager_override(mock_pool: MagicMock) -> None:
    # Setup: Locked by another user, but requesting user is MANAGER
    draft_id = uuid.uuid4()
    user_id = uuid.uuid4()
    other_user = uuid.uuid4()
    future = datetime.datetime.now(timezone.utc) + timedelta(minutes=1)

    mock_conn = mock_pool.acquire.return_value.__aenter__.return_value
    mock_conn.fetchrow.return_value = {"locked_by_user": other_user, "lock_expiry": future}

    mode = await acquire_draft_lock(draft_id, user_id, ["MANAGER"])

    assert mode == AccessMode.SAFE_VIEW
    mock_conn.execute.assert_not_called()


@pytest.mark.asyncio
async def test_refresh_lock_success(mock_pool: MagicMock) -> None:
    draft_id = uuid.uuid4()
    user_id = uuid.uuid4()

    mock_pool.execute.return_value = "UPDATE 1"

    await refresh_lock(draft_id, user_id)

    mock_pool.execute.assert_called()


@pytest.mark.asyncio
async def test_refresh_lock_not_found(mock_pool: MagicMock) -> None:
    draft_id = uuid.uuid4()
    user_id = uuid.uuid4()
    mock_pool.execute.return_value = "UPDATE 0"
    mock_pool.fetchrow.return_value = None

    with pytest.raises(HTTPException) as exc:
        await refresh_lock(draft_id, user_id)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_refresh_lock_failure(mock_pool: MagicMock) -> None:
    draft_id = uuid.uuid4()
    user_id = uuid.uuid4()

    # First execute returns UPDATE 0 (failed to match user/draft)
    mock_pool.execute.return_value = "UPDATE 0"

    # fetchrow returns lock held by someone else
    mock_pool.fetchrow.return_value = {"locked_by_user": uuid.uuid4()}

    with pytest.raises(HTTPException) as exc:
        await refresh_lock(draft_id, user_id)
    assert exc.value.status_code == 423


@pytest.mark.asyncio
async def test_verify_lock_not_found(mock_pool: MagicMock) -> None:
    mock_pool.fetchrow.return_value = None
    with pytest.raises(HTTPException) as exc:
        await verify_lock_for_update(uuid.uuid4(), uuid.uuid4())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_verify_lock_not_held(mock_pool: MagicMock) -> None:
    # Row exists but no one holds lock
    mock_pool.fetchrow.return_value = {"locked_by_user": None, "lock_expiry": None}
    with pytest.raises(HTTPException) as exc:
        await verify_lock_for_update(uuid.uuid4(), uuid.uuid4())
    assert exc.value.status_code == 423


@pytest.mark.asyncio
async def test_verify_lock_success(mock_pool: MagicMock) -> None:
    draft_id = uuid.uuid4()
    user_id = uuid.uuid4()
    future = datetime.datetime.now(timezone.utc) + timedelta(minutes=1)

    mock_pool.fetchrow.return_value = {"locked_by_user": user_id, "lock_expiry": future}

    await verify_lock_for_update(draft_id, user_id)  # Should not raise


@pytest.mark.asyncio
async def test_verify_lock_expired(mock_pool: MagicMock) -> None:
    draft_id = uuid.uuid4()
    user_id = uuid.uuid4()
    past = datetime.datetime.now(timezone.utc) - timedelta(minutes=1)

    mock_pool.fetchrow.return_value = {"locked_by_user": user_id, "lock_expiry": past}

    with pytest.raises(HTTPException) as exc:
        await verify_lock_for_update(draft_id, user_id)
    assert exc.value.status_code == 423
