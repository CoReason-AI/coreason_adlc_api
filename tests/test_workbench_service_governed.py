import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from coreason_adlc_api.workbench.schemas import (
    AccessMode,
    ApprovalStatus,
    DraftCreate,
    DraftResponse,
    DraftUpdate,
    PublishRequest,
)
from coreason_adlc_api.workbench.service_governed import WorkbenchService


@pytest.fixture
def mock_service() -> Any:
    # Patch the 'service' module imported in service_governed.py
    with patch("coreason_adlc_api.workbench.service_governed.service") as mock:
        mock.create_draft = AsyncMock()
        mock.publish_artifact = AsyncMock()
        mock.get_drafts = AsyncMock()
        mock.get_draft_by_id = AsyncMock()
        mock.update_draft = AsyncMock()
        mock.transition_draft_status = AsyncMock()
        mock.assemble_artifact = AsyncMock()
        yield mock


@pytest.fixture
def mock_db_pool() -> Any:
    # Mock database pool for role fetching
    pool = AsyncMock()
    pool.fetch = AsyncMock(return_value=[])
    with patch("coreason_adlc_api.db.get_pool", return_value=pool):
        yield pool


@pytest.fixture
def mock_validation_logic() -> Any:
    # Mock budget and pii checks
    with (
        patch("coreason_adlc_api.middleware.budget.check_budget_status", return_value=True) as mock_budget,
        patch("coreason_adlc_api.middleware.pii.scrub_pii_recursive") as mock_pii,
    ):
        mock_pii.side_effect = lambda x: x  # Identity function by default
        yield mock_budget, mock_pii


@pytest.fixture(autouse=True)
def mock_validator() -> Any:
    try:
        target = "coreason_veritas.wrapper.SignatureValidator"
        with patch(target) as mock_cls:
            instance = mock_cls.return_value
            instance.verify_asset.return_value = True
            yield instance
    except (ImportError, AttributeError):
        target = "coreason_veritas.gatekeeper.SignatureValidator"
        with patch(target) as mock_cls:
            instance = mock_cls.return_value
            instance.verify_asset.return_value = True
            yield instance


@pytest.fixture
def workbench_service() -> WorkbenchService:
    return WorkbenchService()


@pytest.mark.asyncio
async def test_create_draft_governed(workbench_service: WorkbenchService, mock_service: Any) -> None:
    user_oid = uuid.uuid4()
    draft_input = DraftCreate(auc_id="test-auc", title="Test Draft", oas_content={"key": "val"})
    mock_response = DraftResponse(
        draft_id=uuid.uuid4(),
        user_uuid=user_oid,
        auc_id="test-auc",
        title="Test Draft",
        oas_content={"key": "val"},
        status=ApprovalStatus.DRAFT,
        mode=AccessMode.EDIT,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    mock_service.create_draft.return_value = mock_response

    result = await workbench_service.create_draft(draft=draft_input, user_oid=user_oid, signature="mock-sig")
    assert result == mock_response
    mock_service.create_draft.assert_awaited_once_with(draft=draft_input, user_uuid=user_oid)


@pytest.mark.asyncio
async def test_publish_artifact_governed(workbench_service: WorkbenchService, mock_service: Any) -> None:
    draft_id = uuid.uuid4()
    user_oid = uuid.uuid4()
    signature = "valid-sig"
    request = PublishRequest(signature="body-sig")
    mock_url = "https://gitlab.example.com/artifact"
    mock_service.publish_artifact.return_value = mock_url

    result = await workbench_service.publish_artifact(
        draft_id=draft_id, request=request, user_oid=user_oid, signature=signature
    )
    assert result == {"url": mock_url}


@pytest.mark.asyncio
async def test_list_drafts(workbench_service: WorkbenchService, mock_service: Any) -> None:
    mock_service.get_drafts.return_value = []
    # Must use kwargs for governed methods
    await workbench_service.list_drafts(auc_id="auc-1", user_oid=uuid.uuid4())
    mock_service.get_drafts.assert_awaited_once_with(auc_id="auc-1")


@pytest.mark.asyncio
async def test_get_draft(workbench_service: WorkbenchService, mock_service: Any, mock_db_pool: Any) -> None:
    draft_id = uuid.uuid4()
    user_oid = uuid.uuid4()
    mock_db_pool.fetch.return_value = [{"role_name": "DEVELOPER"}]
    mock_response = DraftResponse(
        draft_id=draft_id,
        user_uuid=user_oid,
        auc_id="test-auc",
        title="Test Draft",
        oas_content={},
        status=ApprovalStatus.DRAFT,
        mode=AccessMode.EDIT,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    mock_service.get_draft_by_id.return_value = mock_response

    # Must use kwargs
    result = await workbench_service.get_draft(draft_id=draft_id, user_oid=user_oid, groups=[uuid.uuid4()])
    assert result == mock_response
    mock_service.get_draft_by_id.assert_awaited_once_with(draft_id=draft_id, user_uuid=user_oid, roles=["DEVELOPER"])


@pytest.mark.asyncio
async def test_update_draft(workbench_service: WorkbenchService, mock_service: Any) -> None:
    draft_id = uuid.uuid4()
    user_oid = uuid.uuid4()
    update = DraftUpdate(title="New")

    # Must use kwargs
    await workbench_service.update_draft(draft_id=draft_id, update=update, user_oid=user_oid)
    mock_service.update_draft.assert_awaited_once_with(draft_id=draft_id, update=update, user_uuid=user_oid)


@pytest.mark.asyncio
async def test_validate_draft(workbench_service: WorkbenchService, mock_validation_logic: Any) -> None:
    draft = DraftCreate(auc_id="a", title="t", oas_content={})
    user_oid = uuid.uuid4()

    # Must use kwargs
    res = await workbench_service.validate_draft(draft=draft, user_oid=user_oid)
    assert res.is_valid is True


@pytest.mark.asyncio
async def test_validate_draft_pii_failure(workbench_service: WorkbenchService, mock_validation_logic: Any) -> None:
    draft = DraftCreate(auc_id="a", title="t", oas_content={"pii": "value"})
    user_oid = uuid.uuid4()

    mock_budget, mock_pii = mock_validation_logic
    # Clear side_effect so return_value is used
    mock_pii.side_effect = None
    mock_pii.return_value = {"pii": "REDACTED"}

    # Must use kwargs
    res = await workbench_service.validate_draft(draft=draft, user_oid=user_oid)
    assert res.is_valid is False
    assert "PII Detected" in res.issues


@pytest.mark.asyncio
async def test_transition_status(workbench_service: WorkbenchService, mock_service: Any, mock_db_pool: Any) -> None:
    draft_id = uuid.uuid4()
    user_oid = uuid.uuid4()
    # Mock MANAGER role
    mock_db_pool.fetch.return_value = [{"role_name": "MANAGER"}]

    # Must use kwargs
    await workbench_service.transition_status(
        draft_id=draft_id, user_oid=user_oid, groups=[], new_status=ApprovalStatus.APPROVED
    )

    mock_service.transition_draft_status.assert_awaited_once_with(
        draft_id=draft_id, user_uuid=user_oid, new_status=ApprovalStatus.APPROVED
    )


@pytest.mark.asyncio
async def test_transition_status_forbidden(
    workbench_service: WorkbenchService, mock_service: Any, mock_db_pool: Any
) -> None:
    draft_id = uuid.uuid4()
    user_oid = uuid.uuid4()
    # Mock NO MANAGER role
    mock_db_pool.fetch.return_value = [{"role_name": "DEVELOPER"}]

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        # Must use kwargs
        await workbench_service.transition_status(
            draft_id=draft_id, user_oid=user_oid, groups=[], new_status=ApprovalStatus.APPROVED
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_assemble_artifact(workbench_service: WorkbenchService, mock_service: Any) -> None:
    draft_id = uuid.uuid4()
    user_oid = uuid.uuid4()
    # Must use kwargs
    await workbench_service.assemble_artifact(draft_id=draft_id, user_oid=user_oid)
    mock_service.assemble_artifact.assert_awaited_once_with(draft_id=draft_id, user_oid=user_oid)
