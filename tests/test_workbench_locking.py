from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from coreason_adlc_api.auth.identity import UserIdentity
from coreason_adlc_api.db_models import DraftModel
from coreason_adlc_api.exceptions import DraftLockedError
from coreason_adlc_api.workbench.locking import DraftLockManager


@pytest.fixture
def mock_user_identity():
    return UserIdentity(oid=uuid4(), email="test@example.com", groups=[], full_name="Test User")


@pytest.mark.asyncio
async def test_acquire_lock_success(mock_db_session, mock_user_identity):
    manager = DraftLockManager(mock_db_session, mock_user_identity)

    # Mock finding a draft
    # Use oid for user check
    mock_draft = DraftModel(
        id="00000000-0000-0000-0000-000000000001", project_id="p1", created_by=mock_user_identity.oid
    )

    # Mock session.exec().one_or_none()
    mock_result = MagicMock()
    mock_result.one_or_none.return_value = mock_draft
    mock_db_session.exec.return_value = mock_result

    success = await manager.acquire_lock("00000000-0000-0000-0000-000000000001")
    assert success
    assert mock_draft.locked_by == mock_user_identity.oid
    assert mock_db_session.commit.called


@pytest.mark.asyncio
async def test_acquire_lock_fail_locked(mock_db_session, mock_user_identity):
    manager = DraftLockManager(mock_db_session, mock_user_identity)

    # Draft locked by someone else
    import uuid
    from datetime import datetime

    other_user = uuid.uuid4()
    mock_draft = DraftModel(
        id="00000000-0000-0000-0000-000000000001",
        project_id="p1",
        created_by=mock_user_identity.oid,
        locked_by=other_user,
        locked_at=datetime.utcnow(),
    )

    mock_result = MagicMock()
    mock_result.one_or_none.return_value = mock_draft
    mock_db_session.exec.return_value = mock_result

    with pytest.raises(DraftLockedError):
        await manager.acquire_lock("00000000-0000-0000-0000-000000000001")
