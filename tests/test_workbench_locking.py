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
from coreason_adlc_api.db_models import AgentDraft


@pytest.mark.asyncio
async def test_acquire_lock_not_found(mock_db_session) -> None:
    # Not found in DB
    mock_db_session.exec.return_value.first.return_value = None

    with patch("coreason_adlc_api.workbench.locking.async_session_factory") as mock_factory:
        mock_factory.return_value.__aenter__.return_value = mock_db_session

        with pytest.raises(HTTPException) as exc:
            await acquire_draft_lock(uuid.uuid4(), uuid.uuid4(), [])
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_acquire_lock_new(mock_db_session) -> None:
    # Setup: Not locked
    draft_id = uuid.uuid4()
    user_id = uuid.uuid4()

    mock_draft = AgentDraft(
        draft_id=draft_id,
        locked_by_user=None,
        lock_expiry=None
    )
    mock_db_session.exec.return_value.first.return_value = mock_draft

    with patch("coreason_adlc_api.workbench.locking.async_session_factory") as mock_factory:
        mock_factory.return_value.__aenter__.return_value = mock_db_session

        mode = await acquire_draft_lock(draft_id, user_id, [])

    assert mode == AccessMode.EDIT
    mock_db_session.add.assert_called_with(mock_draft)
    mock_db_session.commit.assert_called()
    assert mock_draft.locked_by_user == user_id


@pytest.mark.asyncio
async def test_acquire_lock_conflict(mock_db_session) -> None:
    # Setup: Locked by another user
    draft_id = uuid.uuid4()
    user_id = uuid.uuid4()
    other_user = uuid.uuid4()
    future = datetime.datetime.now(timezone.utc) + timedelta(minutes=1)

    mock_draft = AgentDraft(
        draft_id=draft_id,
        locked_by_user=other_user,
        lock_expiry=future
    )
    mock_db_session.exec.return_value.first.return_value = mock_draft

    with patch("coreason_adlc_api.workbench.locking.async_session_factory") as mock_factory:
        mock_factory.return_value.__aenter__.return_value = mock_db_session

        with pytest.raises(HTTPException) as exc:
            await acquire_draft_lock(draft_id, user_id, [])

    assert exc.value.status_code == 423
    mock_db_session.add.assert_not_called()


@pytest.mark.asyncio
async def test_acquire_lock_manager_override(mock_db_session) -> None:
    # Setup: Locked by another user, but requesting user is MANAGER
    draft_id = uuid.uuid4()
    user_id = uuid.uuid4()
    other_user = uuid.uuid4()
    future = datetime.datetime.now(timezone.utc) + timedelta(minutes=1)

    mock_draft = AgentDraft(
        draft_id=draft_id,
        locked_by_user=other_user,
        lock_expiry=future
    )
    mock_db_session.exec.return_value.first.return_value = mock_draft

    with patch("coreason_adlc_api.workbench.locking.async_session_factory") as mock_factory:
        mock_factory.return_value.__aenter__.return_value = mock_db_session

        mode = await acquire_draft_lock(draft_id, user_id, ["MANAGER"])

    assert mode == AccessMode.SAFE_VIEW
    mock_db_session.add.assert_not_called()


@pytest.mark.asyncio
async def test_refresh_lock_success(mock_db_session) -> None:
    draft_id = uuid.uuid4()
    user_id = uuid.uuid4()

    # Found held by user
    mock_draft = AgentDraft(
        draft_id=draft_id,
        locked_by_user=user_id,
        lock_expiry=None
    )
    mock_db_session.exec.return_value.first.return_value = mock_draft

    with patch("coreason_adlc_api.workbench.locking.async_session_factory") as mock_factory:
        mock_factory.return_value.__aenter__.return_value = mock_db_session
        await refresh_lock(draft_id, user_id)

    mock_db_session.add.assert_called_with(mock_draft)
    mock_db_session.commit.assert_called()


@pytest.mark.asyncio
async def test_refresh_lock_not_found(mock_db_session) -> None:
    # Logic: First query (where locked_by=me) -> returns None
    # Second query (exists check) -> returns None

    mock_db_session.exec.return_value.first.return_value = None

    with patch("coreason_adlc_api.workbench.locking.async_session_factory") as mock_factory:
        mock_factory.return_value.__aenter__.return_value = mock_db_session

        with pytest.raises(HTTPException) as exc:
            await refresh_lock(uuid.uuid4(), uuid.uuid4())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_refresh_lock_failure(mock_db_session) -> None:
    draft_id = uuid.uuid4()
    user_id = uuid.uuid4()
    other_user = uuid.uuid4()

    # First query (where locked_by=me) -> returns None
    # Second query (exists check) -> returns object (locked by other)

    # We set side_effect for .first()
    # BUT .exec() creates a Result object. mock_db_session.exec calls.
    # We can set side_effect on mock_db_session.exec to return distinct Result objects

    res1 = MagicMock()
    res1.first.return_value = None

    res2 = MagicMock()
    res2.first.return_value = AgentDraft(locked_by_user=other_user) # Locked by other

    mock_db_session.exec.side_effect = [res1, res2]

    with patch("coreason_adlc_api.workbench.locking.async_session_factory") as mock_factory:
        mock_factory.return_value.__aenter__.return_value = mock_db_session

        with pytest.raises(HTTPException) as exc:
            await refresh_lock(draft_id, user_id)
    assert exc.value.status_code == 423


@pytest.mark.asyncio
async def test_verify_lock_not_found(mock_db_session) -> None:
    mock_db_session.exec.return_value.first.return_value = None

    with patch("coreason_adlc_api.workbench.locking.async_session_factory") as mock_factory:
        mock_factory.return_value.__aenter__.return_value = mock_db_session
        with pytest.raises(HTTPException) as exc:
            await verify_lock_for_update(uuid.uuid4(), uuid.uuid4())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_verify_lock_not_held(mock_db_session) -> None:
    # Row exists but no one holds lock
    mock_draft = AgentDraft(locked_by_user=None, lock_expiry=None)
    mock_db_session.exec.return_value.first.return_value = mock_draft

    with patch("coreason_adlc_api.workbench.locking.async_session_factory") as mock_factory:
        mock_factory.return_value.__aenter__.return_value = mock_db_session
        with pytest.raises(HTTPException) as exc:
            await verify_lock_for_update(uuid.uuid4(), uuid.uuid4())
    assert exc.value.status_code == 423


@pytest.mark.asyncio
async def test_verify_lock_success(mock_db_session) -> None:
    draft_id = uuid.uuid4()
    user_id = uuid.uuid4()
    future = datetime.datetime.now(timezone.utc) + timedelta(minutes=1)

    mock_draft = AgentDraft(locked_by_user=user_id, lock_expiry=future)
    mock_db_session.exec.return_value.first.return_value = mock_draft

    with patch("coreason_adlc_api.workbench.locking.async_session_factory") as mock_factory:
        mock_factory.return_value.__aenter__.return_value = mock_db_session
        await verify_lock_for_update(draft_id, user_id)  # Should not raise


@pytest.mark.asyncio
async def test_verify_lock_expired(mock_db_session) -> None:
    draft_id = uuid.uuid4()
    user_id = uuid.uuid4()
    past = datetime.datetime.now(timezone.utc) - timedelta(minutes=1)

    mock_draft = AgentDraft(locked_by_user=user_id, lock_expiry=past)
    mock_db_session.exec.return_value.first.return_value = mock_draft

    with patch("coreason_adlc_api.workbench.locking.async_session_factory") as mock_factory:
        mock_factory.return_value.__aenter__.return_value = mock_db_session
        with pytest.raises(HTTPException) as exc:
            await verify_lock_for_update(draft_id, user_id)
    assert exc.value.status_code == 423
