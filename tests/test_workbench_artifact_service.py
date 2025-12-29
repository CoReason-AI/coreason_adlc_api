from datetime import datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from coreason_adlc_api.workbench.schemas import ApprovalStatus, DraftResponse
from coreason_adlc_api.workbench.service import assemble_artifact, publish_artifact
from fastapi import HTTPException


# Service Unit Tests (Testing logic directly)


@pytest.mark.asyncio
async def test_assemble_artifact_success() -> None:
    draft_id = uuid4()
    user_id = uuid4()

    mock_draft = DraftResponse(
        draft_id=draft_id,
        user_uuid=user_id,
        auc_id="proj",
        title="Title",
        oas_content={"openapi": "3.0.0"},
        status=ApprovalStatus.APPROVED,
        created_at=datetime(2023, 1, 1),
        updated_at=datetime(2023, 1, 2),
    )

    with patch("coreason_adlc_api.workbench.service.get_draft_by_id", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_draft

        artifact = await assemble_artifact(draft_id, user_id)

        assert artifact.id == draft_id
        assert artifact.version == "1.0.0"
        assert artifact.created_at == mock_draft.updated_at  # Check determinism


@pytest.mark.asyncio
async def test_assemble_artifact_not_found() -> None:
    with patch("coreason_adlc_api.workbench.service.get_draft_by_id", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = None
        with pytest.raises(HTTPException) as e:
            await assemble_artifact(uuid4(), uuid4())
        assert e.value.status_code == 404


@pytest.mark.asyncio
async def test_assemble_artifact_not_approved() -> None:
    mock_draft = DraftResponse(
        draft_id=uuid4(),
        user_uuid=uuid4(),
        auc_id="proj",
        title="Title",
        oas_content={},
        status=ApprovalStatus.DRAFT,  # Not APPROVED
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    with patch("coreason_adlc_api.workbench.service.get_draft_by_id", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_draft
        with pytest.raises(ValueError) as e:
            await assemble_artifact(uuid4(), uuid4())
        assert "must be APPROVED" in str(e.value)


@pytest.mark.asyncio
async def test_publish_artifact_flow() -> None:
    draft_id = uuid4()
    user_id = uuid4()

    # We mock assemble_artifact to avoid re-testing it
    with patch("coreason_adlc_api.workbench.service.assemble_artifact", new_callable=AsyncMock) as mock_assemble:
        mock_artifact = AsyncMock()
        mock_artifact.id = draft_id
        mock_assemble.return_value = mock_artifact

        url = await publish_artifact(draft_id, "signature", user_id)

        assert mock_artifact.author_signature == "signature"
        assert f"/agents/{draft_id}/v1" in url
