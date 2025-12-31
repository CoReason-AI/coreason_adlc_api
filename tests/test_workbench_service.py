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
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.engine import Result

from coreason_adlc_api.workbench.schemas import ApprovalStatus, DraftCreate, DraftUpdate
from coreason_adlc_api.workbench.service import create_draft, get_draft_by_id, get_drafts, update_draft


@pytest.mark.asyncio
async def test_create_draft_logic(mock_db_session: AsyncMock) -> None:
    user_id = uuid.uuid4()
    draft = DraftCreate(auc_id="test-auc", title="test", oas_content={"a": 1})

    mock_row = {
        "draft_id": uuid.uuid4(),
        "user_uuid": user_id,
        "auc_id": "test-auc",
        "title": "test",
        "oas_content": {"a": 1},
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
    }
    mock_db_session.execute.return_value.mappings.return_value.fetchone.return_value = mock_row

    res = await create_draft(mock_db_session, draft, user_id)
    assert res.title == "test"
    mock_db_session.execute.assert_called_once()
    args, _ = mock_db_session.execute.call_args
    assert "INSERT INTO" in str(args[0])


@pytest.mark.asyncio
async def test_create_draft_failure(mock_db_session: AsyncMock) -> None:
    mock_db_session.execute.return_value.mappings.return_value.fetchone.return_value = None
    draft = DraftCreate(auc_id="test-auc", title="test", oas_content={})

    with pytest.raises(RuntimeError):
        await create_draft(mock_db_session, draft, uuid.uuid4())


@pytest.mark.asyncio
async def test_get_drafts_logic(mock_db_session: AsyncMock) -> None:
    mock_db_session.execute.return_value.mappings.return_value.all.return_value = [
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

    res = await get_drafts(mock_db_session, "test-auc")
    assert len(res) == 1
    mock_db_session.execute.assert_called_once()


@pytest.mark.asyncio
async def test_get_draft_by_id_logic(mock_db_session: AsyncMock) -> None:
    draft_id = uuid.uuid4()
    mock_db_session.execute.return_value.mappings.return_value.fetchone.return_value = {
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
        res = await get_draft_by_id(mock_db_session, draft_id, uuid.uuid4(), [])
        assert res is not None
        assert res.draft_id == draft_id
        mock_lock.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_draft_by_id_missing(mock_db_session: AsyncMock) -> None:
    with patch("coreason_adlc_api.workbench.service.acquire_draft_lock"):
        mock_db_session.execute.return_value.mappings.return_value.fetchone.return_value = None
        res = await get_draft_by_id(mock_db_session, uuid.uuid4(), uuid.uuid4(), [])
        assert res is None


@pytest.mark.asyncio
async def test_get_draft_by_id_lock_404(mock_db_session: AsyncMock) -> None:
    with patch("coreason_adlc_api.workbench.service.acquire_draft_lock", side_effect=HTTPException(status_code=404)):
        res = await get_draft_by_id(mock_db_session, uuid.uuid4(), uuid.uuid4(), [])
        assert res is None


@pytest.mark.asyncio
async def test_get_draft_by_id_lock_other_error(mock_db_session: AsyncMock) -> None:
    with patch("coreason_adlc_api.workbench.service.acquire_draft_lock", side_effect=HTTPException(status_code=423)):
        with pytest.raises(HTTPException) as exc:
            await get_draft_by_id(mock_db_session, uuid.uuid4(), uuid.uuid4(), [])
        assert exc.value.status_code == 423


@pytest.mark.asyncio
async def test_update_draft_logic(mock_db_session: AsyncMock) -> None:
    draft_id = uuid.uuid4()
    user_id = uuid.uuid4()
    update = DraftUpdate(title="New Title", runtime_env="reqs.txt", oas_content={"b": 2})

    from datetime import datetime, timedelta, timezone

    # Define return values for consecutive calls:
    # 1. _check_status_for_update (SELECT status)
    # 2. update_draft (UPDATE query) -> Updated Row

    def execute_side_effect(stmt: Any, params: Any = None) -> MagicMock:
        query = str(stmt)
        mock_res = MagicMock(spec=Result)

        if "SELECT status" in query:
            mock_res.fetchone.return_value = (ApprovalStatus.DRAFT,)
        elif "UPDATE workbench.agent_drafts" in query:
            mock_res.mappings.return_value.fetchone.return_value = {
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
                "status": ApprovalStatus.DRAFT,
            }
        else:
            mock_res.fetchone.return_value = None

        return mock_res

    mock_db_session.execute.side_effect = execute_side_effect

    with patch("coreason_adlc_api.workbench.service.verify_lock_for_update"):
        res = await update_draft(mock_db_session, draft_id, update, user_id)

    assert res.title == "New Title"
    assert res.runtime_env == "reqs.txt"
    assert mock_db_session.execute.call_count == 2


@pytest.mark.asyncio
async def test_update_draft_no_fields(mock_db_session: AsyncMock) -> None:
    draft_id = uuid.uuid4()
    user_id = uuid.uuid4()

    from datetime import datetime, timedelta, timezone

    # Calls:
    # 1. verify_lock (patched)
    # 2. check_status
    # 3. get_draft_by_id (if no fields)

    def execute_side_effect(stmt: Any, params: Any = None) -> MagicMock:
        query = str(stmt)
        mock_res = MagicMock(spec=Result)

        if "SELECT status" in query:
            mock_res.fetchone.return_value = (ApprovalStatus.DRAFT,)
        elif "SELECT * FROM workbench.agent_drafts" in query:
            mock_res.mappings.return_value.fetchone.return_value = {
                "draft_id": draft_id,
                "user_uuid": user_id,
                "auc_id": "test-auc",
                "title": "Old Title",
                "oas_content": {},
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
                "locked_by_user": user_id,
                "lock_expiry": datetime.now(timezone.utc) + timedelta(minutes=1),
                "status": ApprovalStatus.DRAFT,
            }
        else:
            mock_res.fetchone.return_value = None

        return mock_res

    mock_db_session.execute.side_effect = execute_side_effect

    # Mock acquire_draft_lock because get_draft_by_id calls it
    with (
        patch("coreason_adlc_api.workbench.service.acquire_draft_lock"),
        patch("coreason_adlc_api.workbench.service.verify_lock_for_update"),
    ):
        res = await update_draft(mock_db_session, draft_id, DraftUpdate(), user_id)
        assert res.title == "Old Title"
        # check_status + get_draft_by_id
        assert mock_db_session.execute.call_count == 2


@pytest.mark.asyncio
async def test_update_draft_not_found(mock_db_session: AsyncMock) -> None:
    # Case: Update with fields, but row not found

    def execute_side_effect(stmt: Any, params: Any = None) -> MagicMock:
        query = str(stmt)
        mock_res = MagicMock(spec=Result)

        if "SELECT status" in query:
            mock_res.fetchone.return_value = (ApprovalStatus.DRAFT,)
        elif "UPDATE workbench.agent_drafts" in query:
            mock_res.mappings.return_value.fetchone.return_value = None
        else:
            mock_res.fetchone.return_value = None

        return mock_res

    mock_db_session.execute.side_effect = execute_side_effect

    with pytest.raises(HTTPException) as exc, patch("coreason_adlc_api.workbench.service.verify_lock_for_update"):
        await update_draft(mock_db_session, uuid.uuid4(), DraftUpdate(title="X"), uuid.uuid4())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_update_draft_no_fields_not_found(mock_db_session: AsyncMock) -> None:
    # Case: No fields, but draft lookup fails

    def execute_side_effect(stmt: Any, params: Any = None) -> MagicMock:
        query = str(stmt)
        mock_res = MagicMock(spec=Result)

        if "SELECT status" in query:
            mock_res.fetchone.return_value = (ApprovalStatus.DRAFT,)
        elif "SELECT * FROM workbench.agent_drafts" in query:
            mock_res.mappings.return_value.fetchone.return_value = None
        else:
            mock_res.fetchone.return_value = None

        return mock_res

    mock_db_session.execute.side_effect = execute_side_effect

    with (
        pytest.raises(HTTPException) as exc,
        patch("coreason_adlc_api.workbench.service.verify_lock_for_update"),
        patch("coreason_adlc_api.workbench.service.acquire_draft_lock"),
    ):
        await update_draft(mock_db_session, uuid.uuid4(), DraftUpdate(), uuid.uuid4())
    assert exc.value.status_code == 404
