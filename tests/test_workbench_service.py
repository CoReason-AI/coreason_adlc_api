from unittest.mock import patch
from uuid import uuid4

import pytest

from coreason_adlc_api.auth.identity import UserIdentity
from coreason_adlc_api.workbench.schemas import DraftCreate
from coreason_adlc_api.workbench.service import WorkbenchService


@pytest.fixture
def mock_user_identity():
    return UserIdentity(oid=uuid4(), email="test@example.com", groups=[], full_name="Test User")


@pytest.mark.asyncio
async def test_create_draft_governance(mock_db_session, mock_user_identity):
    """
    Tests that create_draft is governed and persists data.
    """
    service = WorkbenchService(mock_db_session, mock_user_identity)

    # Mock governance map_groups_to_projects
    with patch("coreason_adlc_api.workbench.service.map_groups_to_projects") as mock_map:
        mock_map.return_value = ["test-project"]

        draft_in = DraftCreate(auc_id="test-project", title="My Draft", oas_content={"foo": "bar"})

        # We need to mock session.add/commit/refresh
        mock_db_session.refresh.side_effect = lambda x: None

        response = await service.create_draft(draft_in, "test-project", str(mock_user_identity.oid))

        assert response.auc_id == "test-project"
        assert response.oas_content == {"foo": "bar"}
        assert mock_db_session.add.called
        assert mock_db_session.commit.called
