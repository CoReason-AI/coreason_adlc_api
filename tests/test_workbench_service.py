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
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from fastapi import HTTPException

from coreason_adlc_api.workbench.schemas import ApprovalStatus, DraftCreate, DraftUpdate
from coreason_adlc_api.workbench.service import create_draft, get_draft_by_id, get_drafts, update_draft
from coreason_adlc_api.db_models import AgentDraft


@pytest.mark.asyncio
async def test_create_draft_logic(mock_db_session) -> None:
    user_id = uuid.uuid4()
    draft = DraftCreate(auc_id="test-auc", title="test", oas_content={"a": 1})

    # The service calls session.add(draft), commit(), refresh().
    # SQLModel objects are mutable. We don't need to return a value for add/refresh usually in mocks
    # unless we want to simulate ID generation.
    # We can inject behavior into refresh to set the ID.

    def simulate_refresh(obj):
        obj.draft_id = uuid.uuid4()
        obj.created_at = "2024-01-01T00:00:00Z"
        obj.updated_at = "2024-01-01T00:00:00Z"

    mock_db_session.refresh.side_effect = simulate_refresh

    with patch("coreason_adlc_api.workbench.service.async_session_factory") as mock_factory:
        mock_factory.return_value.__aenter__.return_value = mock_db_session

        res = await create_draft(draft, user_id)
        assert res.title == "test"
        assert res.draft_id is not None
        mock_db_session.add.assert_called_once()
        mock_db_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_create_draft_failure(mock_db_session) -> None:
    draft = DraftCreate(auc_id="test-auc", title="test", oas_content={})
    mock_db_session.commit.side_effect = Exception("DB Error")

    with patch("coreason_adlc_api.workbench.service.async_session_factory") as mock_factory:
        mock_factory.return_value.__aenter__.return_value = mock_db_session

        with pytest.raises(RuntimeError):
            await create_draft(draft, uuid.uuid4())


@pytest.mark.asyncio
async def test_get_drafts_logic(mock_db_session) -> None:
    # Mock result
    mock_draft = AgentDraft(
        draft_id=uuid.uuid4(),
        user_uuid=uuid.uuid4(),
        auc_id="test-auc",
        title="test",
        oas_content={},
        status="DRAFT"
    )
    mock_db_session.exec.return_value.all.return_value = [mock_draft]

    with patch("coreason_adlc_api.workbench.service.async_session_factory") as mock_factory:
        mock_factory.return_value.__aenter__.return_value = mock_db_session

        res = await get_drafts("test-auc")
        assert len(res) == 1
        assert res[0].title == "test"


@pytest.mark.asyncio
async def test_get_draft_by_id_logic(mock_db_session) -> None:
    draft_id = uuid.uuid4()
    mock_draft = AgentDraft(
        draft_id=draft_id,
        user_uuid=uuid.uuid4(),
        auc_id="test-auc",
        title="test",
        oas_content={},
        status="DRAFT"
    )
    mock_db_session.exec.return_value.first.return_value = mock_draft

    # Mock acquire_draft_lock to avoid transaction logic complexity in service test
    with patch("coreason_adlc_api.workbench.service.acquire_draft_lock") as mock_lock:
        with patch("coreason_adlc_api.workbench.service.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__.return_value = mock_db_session

            res = await get_draft_by_id(draft_id, uuid.uuid4(), [])
            assert res is not None
            assert res.draft_id == draft_id
            mock_lock.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_draft_by_id_missing(mock_db_session) -> None:
    mock_db_session.exec.return_value.first.return_value = None

    with patch("coreason_adlc_api.workbench.service.acquire_draft_lock"):
        with patch("coreason_adlc_api.workbench.service.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__.return_value = mock_db_session

            res = await get_draft_by_id(uuid.uuid4(), uuid.uuid4(), [])
            assert res is None


@pytest.mark.asyncio
async def test_get_draft_by_id_lock_404(mock_db_session) -> None:
    with patch("coreason_adlc_api.workbench.service.acquire_draft_lock", side_effect=HTTPException(status_code=404)):
        res = await get_draft_by_id(uuid.uuid4(), uuid.uuid4(), [])
        assert res is None


@pytest.mark.asyncio
async def test_get_draft_by_id_lock_other_error(mock_db_session) -> None:
    with patch("coreason_adlc_api.workbench.service.acquire_draft_lock", side_effect=HTTPException(status_code=423)):
        with pytest.raises(HTTPException) as exc:
            await get_draft_by_id(uuid.uuid4(), uuid.uuid4(), [])
        assert exc.value.status_code == 423


@pytest.mark.asyncio
async def test_update_draft_logic(mock_db_session) -> None:
    draft_id = uuid.uuid4()
    user_id = uuid.uuid4()
    update = DraftUpdate(title="New Title", runtime_env="reqs.txt", oas_content={"b": 2})

    from datetime import datetime, timedelta, timezone

    # Mocks for:
    # 1. _check_status_for_update (select status)
    # 2. update_draft (select full object)

    mock_status_draft = AgentDraft(status=ApprovalStatus.DRAFT.value)

    mock_full_draft = AgentDraft(
        draft_id=draft_id,
        user_uuid=user_id,
        auc_id="test-auc",
        title="Old Title",
        oas_content={"a": 1},
        status=ApprovalStatus.DRAFT.value
    )

    # We can use side_effect on 'first()' if they are distinct calls.
    # However, 'first()' is called on result object.
    # Since we use `mock_db_session` which is reused, we can set side_effect on the `exec` return value's `first` method?
    # Or just `exec` returns different mock results.

    mock_res1 = MagicMock()
    mock_res1.first.return_value = mock_status_draft

    mock_res2 = MagicMock()
    mock_res2.first.return_value = mock_full_draft

    mock_db_session.exec.side_effect = [mock_res1, mock_res2]

    with patch("coreason_adlc_api.workbench.service.verify_lock_for_update"):
        with patch("coreason_adlc_api.workbench.service.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__.return_value = mock_db_session

            res = await update_draft(draft_id, update, user_id)

    assert res.title == "New Title"
    assert res.runtime_env == "reqs.txt"
    assert mock_db_session.add.called
    assert mock_db_session.commit.called


@pytest.mark.asyncio
async def test_update_draft_no_fields(mock_db_session) -> None:
    draft_id = uuid.uuid4()
    user_id = uuid.uuid4()

    mock_status_draft = AgentDraft(status=ApprovalStatus.DRAFT.value)
    mock_full_draft = AgentDraft(
        draft_id=draft_id,
        user_uuid=user_id,
        title="Old Title",
        auc_id="test-auc"
    )

    mock_res1 = MagicMock()
    mock_res1.first.return_value = mock_status_draft

    mock_res2 = MagicMock()
    mock_res2.first.return_value = mock_full_draft

    mock_db_session.exec.side_effect = [mock_res1, mock_res2]

    # Mock acquire_draft_lock because get_draft_by_id might call it if no update?
    # In logic: if not fields: return await get_draft_by_id(...)
    # get_draft_by_id calls acquire_draft_lock.

    with (
        patch("coreason_adlc_api.workbench.service.acquire_draft_lock"),
        patch("coreason_adlc_api.workbench.service.verify_lock_for_update"),
        patch("coreason_adlc_api.workbench.service.async_session_factory") as mock_factory
    ):
        mock_factory.return_value.__aenter__.return_value = mock_db_session
        res = await update_draft(draft_id, DraftUpdate(), user_id)

        assert res.title == "Old Title"
        # If no fields, we didn't call add/commit
        # But we did call get_draft_by_id which queries DB
        assert mock_db_session.exec.call_count >= 1 # check status + get


@pytest.mark.asyncio
async def test_update_draft_not_found(mock_db_session) -> None:
    mock_res1 = MagicMock()
    mock_res1.first.return_value = AgentDraft(status=ApprovalStatus.DRAFT.value)

    mock_res2 = MagicMock()
    mock_res2.first.return_value = None # Not found on 2nd query

    mock_db_session.exec.side_effect = [mock_res1, mock_res2]

    with pytest.raises(HTTPException) as exc:
        with patch("coreason_adlc_api.workbench.service.verify_lock_for_update"):
            with patch("coreason_adlc_api.workbench.service.async_session_factory") as mock_factory:
                mock_factory.return_value.__aenter__.return_value = mock_db_session
                await update_draft(uuid.uuid4(), DraftUpdate(title="X"), uuid.uuid4())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_update_draft_no_fields_not_found(mock_db_session) -> None:
    # Logic: _check_status_for_update -> OK.
    # No fields -> get_draft_by_id
    # get_draft_by_id -> DB query -> None.

    # We patch get_draft_by_id to return None directly to simplify
    with patch("coreason_adlc_api.workbench.service._check_status_for_update"), \
         patch("coreason_adlc_api.workbench.service.verify_lock_for_update"), \
         patch("coreason_adlc_api.workbench.service.get_draft_by_id", return_value=None):

        with pytest.raises(HTTPException) as exc:
             # We don't need mock_db_session here if we patch internal calls
             await update_draft(uuid.uuid4(), DraftUpdate(), uuid.uuid4())
    assert exc.value.status_code == 404
