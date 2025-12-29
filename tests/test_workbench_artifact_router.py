
from datetime import datetime
from typing import Generator, Tuple
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from coreason_adlc_api.app import app
from coreason_adlc_api.workbench.schemas import AgentArtifact, ApprovalStatus, DraftResponse
from fastapi.testclient import TestClient


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def mock_workbench_service() -> Generator[Tuple[AsyncMock, AsyncMock, AsyncMock], None, None]:
    with (
        patch("coreason_adlc_api.routers.workbench.assemble_artifact") as mock_assemble,
        patch("coreason_adlc_api.routers.workbench.publish_artifact") as mock_publish,
        patch("coreason_adlc_api.routers.workbench.get_draft_by_id") as mock_get_draft,
        patch("coreason_adlc_api.routers.workbench.map_groups_to_projects") as mock_groups,
    ):
        mock_groups.return_value = ["test-project"]
        yield mock_assemble, mock_publish, mock_get_draft


def test_router_assemble_success(
    client: TestClient,
    mock_oidc_factory: object,
    mock_workbench_service: Tuple[AsyncMock, AsyncMock, AsyncMock],
) -> None:
    mock_assemble, _, mock_get_draft = mock_workbench_service
    draft_id = uuid4()
    # Cast factory to correct type if needed, or rely on runtime behavior.
    token = mock_oidc_factory({"groups": ["manager"]})  # type: ignore

    # Mock Service Response
    mock_assemble.return_value = AgentArtifact(
        id=draft_id,
        auc_id="test-project",
        version="1.0.0",
        content={},
        compliance_hash="hash",
        created_at=datetime(2023, 1, 1),
    )
    # Mock Access Check
    mock_get_draft.return_value = DraftResponse(
        draft_id=draft_id,
        user_uuid=uuid4(),
        auc_id="test-project",
        title="T",
        oas_content={},
        created_at=datetime(2023, 1, 1),
        updated_at=datetime(2023, 1, 1),
        status=ApprovalStatus.APPROVED,
    )

    resp = client.get(
        f"/api/v1/workbench/drafts/{draft_id}/assemble",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == str(draft_id)


def test_router_assemble_error(
    client: TestClient,
    mock_oidc_factory: object,
    mock_workbench_service: Tuple[AsyncMock, AsyncMock, AsyncMock],
) -> None:
    mock_assemble, _, mock_get_draft = mock_workbench_service
    draft_id = uuid4()
    token = mock_oidc_factory({"groups": ["manager"]})  # type: ignore

    mock_get_draft.return_value = DraftResponse(
        draft_id=draft_id,
        user_uuid=uuid4(),
        auc_id="test-project",
        title="T",
        oas_content={},
        created_at=datetime(2023, 1, 1),
        updated_at=datetime(2023, 1, 1),
        status=ApprovalStatus.APPROVED,
    )
    mock_assemble.side_effect = ValueError("Not approved")

    resp = client.get(
        f"/api/v1/workbench/drafts/{draft_id}/assemble",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400
    assert "Not approved" in resp.json()["detail"]


def test_router_publish_success(
    client: TestClient,
    mock_oidc_factory: object,
    mock_workbench_service: Tuple[AsyncMock, AsyncMock, AsyncMock],
) -> None:
    _, mock_publish, mock_get_draft = mock_workbench_service
    draft_id = uuid4()
    token = mock_oidc_factory({"groups": ["manager"]})  # type: ignore

    mock_get_draft.return_value = DraftResponse(
        draft_id=draft_id,
        user_uuid=uuid4(),
        auc_id="test-project",
        title="T",
        oas_content={},
        created_at=datetime(2023, 1, 1),
        updated_at=datetime(2023, 1, 1),
        status=ApprovalStatus.APPROVED,
    )
    mock_publish.return_value = "http://gitlab"

    resp = client.post(
        f"/api/v1/workbench/drafts/{draft_id}/publish",
        json={"signature": "sig"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["url"] == "http://gitlab"


def test_router_publish_error(
    client: TestClient,
    mock_oidc_factory: object,
    mock_workbench_service: Tuple[AsyncMock, AsyncMock, AsyncMock],
) -> None:
    _, mock_publish, mock_get_draft = mock_workbench_service
    draft_id = uuid4()
    token = mock_oidc_factory({"groups": ["manager"]})  # type: ignore

    mock_get_draft.return_value = DraftResponse(
        draft_id=draft_id,
        user_uuid=uuid4(),
        auc_id="test-project",
        title="T",
        oas_content={},
        created_at=datetime(2023, 1, 1),
        updated_at=datetime(2023, 1, 1),
        status=ApprovalStatus.APPROVED,
    )
    mock_publish.side_effect = ValueError("Bad sig")

    resp = client.post(
        f"/api/v1/workbench/drafts/{draft_id}/publish",
        json={"signature": "sig"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400
    assert "Bad sig" in resp.json()["detail"]
