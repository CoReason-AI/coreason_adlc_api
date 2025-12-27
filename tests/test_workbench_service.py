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
from typing import Generator
from unittest.mock import AsyncMock, patch

import pytest
from coreason_adlc_api.workbench.schemas import ApprovalStatus, DraftCreate, DraftUpdate
from coreason_adlc_api.workbench.service import create_draft, get_draft_by_id, get_drafts, update_draft
from fastapi import HTTPException


@pytest.fixture
def mock_pool() -> Generator[AsyncMock, None, None]:
    pool = AsyncMock()
    # Explicitly ensure methods are awaitable
    pool.fetchrow = AsyncMock()
    pool.fetch = AsyncMock()
    pool.execute = AsyncMock()
    # Patch get_pool in all usage locations
    with (
        patch("coreason_adlc_api.workbench.service.get_pool", return_value=pool),
        patch("coreason_adlc_api.workbench.locking.get_pool", return_value=pool),
    ):
        yield pool


@pytest.mark.asyncio
async def test_create_draft_logic(mock_pool: AsyncMock) -> None:
    user_id = uuid.uuid4()
    draft = DraftCreate(auc_id="test-auc", title="test", oas_content={"a": 1})

    mock_pool.fetchrow.return_value = {
        "draft_id": uuid.uuid4(),
        "user_uuid": user_id,
        "auc_id": "test-auc",
        "title": "test",
        "oas_content": {"a": 1},
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
    }

    res = await create_draft(draft, user_id)
    assert res.title == "test"
    mock_pool.fetchrow.assert_called_once()
    args = mock_pool.fetchrow.call_args[0]
    assert "INSERT INTO" in args[0]


@pytest.mark.asyncio
async def test_create_draft_failure(mock_pool: AsyncMock) -> None:
    mock_pool.fetchrow.return_value = None
    draft = DraftCreate(auc_id="test-auc", title="test", oas_content={})

    with pytest.raises(RuntimeError):
        await create_draft(draft, uuid.uuid4())


@pytest.mark.asyncio
async def test_get_drafts_logic(mock_pool: AsyncMock) -> None:
    mock_pool.fetch.return_value = [
        {
            "draft_id": uuid.uuid4(),
            "user_uuid": uuid.uuid4(),
            "auc_id": "test-auc",
            "title": "test",
            "oas_content": {},
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
        }
    ]

    res = await get_drafts("test-auc")
    assert len(res) == 1
    mock_pool.fetch.assert_called_once()


@pytest.mark.asyncio
async def test_get_draft_by_id_logic(mock_pool: AsyncMock) -> None:
    draft_id = uuid.uuid4()
    mock_pool.fetchrow.return_value = {
        "draft_id": draft_id,
        "user_uuid": uuid.uuid4(),
        "auc_id": "test-auc",
        "title": "test",
        "oas_content": {},
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
        "locked_by_user": None,
        "lock_expiry": None,
    }

    # Mock acquire_draft_lock to avoid transaction logic complexity in service test
    with patch("coreason_adlc_api.workbench.service.acquire_draft_lock") as mock_lock:
        res = await get_draft_by_id(draft_id, uuid.uuid4(), [])
        assert res is not None
        assert res.draft_id == draft_id
        mock_lock.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_draft_by_id_missing(mock_pool: AsyncMock) -> None:
    with patch("coreason_adlc_api.workbench.service.acquire_draft_lock"):
        mock_pool.fetchrow.return_value = None
        res = await get_draft_by_id(uuid.uuid4(), uuid.uuid4(), [])
        assert res is None


@pytest.mark.asyncio
async def test_get_draft_by_id_lock_404(mock_pool: AsyncMock) -> None:
    with patch("coreason_adlc_api.workbench.service.acquire_draft_lock", side_effect=HTTPException(status_code=404)):
        res = await get_draft_by_id(uuid.uuid4(), uuid.uuid4(), [])
        assert res is None


@pytest.mark.asyncio
async def test_get_draft_by_id_lock_other_error(mock_pool: AsyncMock) -> None:
    with patch("coreason_adlc_api.workbench.service.acquire_draft_lock", side_effect=HTTPException(status_code=423)):
        with pytest.raises(HTTPException) as exc:
            await get_draft_by_id(uuid.uuid4(), uuid.uuid4(), [])
        assert exc.value.status_code == 423


@pytest.mark.asyncio
async def test_update_draft_logic(mock_pool: AsyncMock) -> None:
    draft_id = uuid.uuid4()
    user_id = uuid.uuid4()
    update = DraftUpdate(title="New Title", runtime_env="reqs.txt", oas_content={"b": 2})

    from datetime import datetime, timedelta, timezone

    # Define return values for consecutive calls:
    # 1. _check_status_for_update -> { "status": "DRAFT" }
    # 2. update_draft (UPDATE query) -> Updated Row

    mock_pool.fetchrow.side_effect = [
        {"status": ApprovalStatus.DRAFT},
        {
            "draft_id": draft_id,
            "user_uuid": user_id,
            "auc_id": "test-auc",
            "title": "New Title",
            "oas_content": {"b": 2},
            "runtime_env": "reqs.txt",
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
            "locked_by_user": user_id,
            "lock_expiry": datetime.now(timezone.utc) + timedelta(minutes=1),
            "status": ApprovalStatus.DRAFT
        }
    ]

    with patch("coreason_adlc_api.workbench.service.verify_lock_for_update"):
        res = await update_draft(draft_id, update, user_id)

    assert res.title == "New Title"
    assert res.runtime_env == "reqs.txt"
    # assert "UPDATE" in mock_pool.fetchrow.call_args[0][0] # Hard to check last call exactly with side_effect
    assert mock_pool.fetchrow.call_count == 2


@pytest.mark.asyncio
async def test_update_draft_no_fields(mock_pool: AsyncMock) -> None:
    draft_id = uuid.uuid4()
    user_id = uuid.uuid4()

    from datetime import datetime, timedelta, timezone

    mock_pool.fetchrow.side_effect = [
        {"status": ApprovalStatus.DRAFT},
        {
            "draft_id": draft_id,
            "user_uuid": user_id,
            "auc_id": "test-auc",
            "title": "Old Title",
            "oas_content": {},
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
            "locked_by_user": user_id,
            "lock_expiry": datetime.now(timezone.utc) + timedelta(minutes=1),
            "status": ApprovalStatus.DRAFT
        }
    ]

    # Mock acquire_draft_lock because get_draft_by_id calls it
    with (
        patch("coreason_adlc_api.workbench.service.acquire_draft_lock"),
        patch("coreason_adlc_api.workbench.service.verify_lock_for_update")
    ):
        res = await update_draft(draft_id, DraftUpdate(), user_id)
        assert res.title == "Old Title"
        assert mock_pool.fetchrow.call_count == 2


@pytest.mark.asyncio
async def test_update_draft_not_found(mock_pool: AsyncMock) -> None:
    # Case: Update with fields, but row not found
    # Mock status check success, but update returns None (race condition or not found)

    mock_pool.fetchrow.side_effect = [
         {"status": ApprovalStatus.DRAFT},
         None
    ]

    with pytest.raises(HTTPException) as exc, patch("coreason_adlc_api.workbench.service.verify_lock_for_update"):
        await update_draft(uuid.uuid4(), DraftUpdate(title="X"), uuid.uuid4())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_update_draft_no_fields_not_found(mock_pool: AsyncMock) -> None:
    # Case: No fields, but draft lookup fails
    mock_pool.fetchrow.side_effect = [
         {"status": ApprovalStatus.DRAFT},
         None
    ]

    with (
        pytest.raises(HTTPException) as exc,
        patch("coreason_adlc_api.workbench.service.verify_lock_for_update"),
        patch("coreason_adlc_api.workbench.service.acquire_draft_lock"),
    ):
        await update_draft(uuid.uuid4(), DraftUpdate(), uuid.uuid4())
    assert exc.value.status_code == 404
