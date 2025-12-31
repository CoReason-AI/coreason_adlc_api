import pytest

from coreason_adlc_api.workbench.schemas import DraftCreate
from coreason_adlc_api.workbench.service import WorkbenchService


@pytest.mark.asyncio
async def test_create_draft_governance(mock_db_session, mock_user_identity):
    """
    Tests that create_draft is governed and persists data.
    """
    service = WorkbenchService(mock_db_session, mock_user_identity)

    # Mock governance map_groups_to_projects
    with pytest.patch("coreason_adlc_api.workbench.service.map_groups_to_projects") as mock_map:
        mock_map.return_value = ["test-project"]

        draft_in = DraftCreate(project_id="test-project", content={"foo": "bar"})

        # We need to mock session.add/commit/refresh
        mock_db_session.refresh.side_effect = lambda x: None

        response = await service.create_draft(draft_in)

        assert response.project_id == "test-project"
        assert response.content == {"foo": "bar"}
        assert mock_db_session.add.called
        assert mock_db_session.commit.called
