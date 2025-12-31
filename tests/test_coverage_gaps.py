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
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.engine import Result

from coreason_adlc_api.app import app
from coreason_adlc_api.auth.identity import UserIdentity, parse_and_validate_token
from coreason_adlc_api.dependencies import get_db
from coreason_adlc_api.middleware.circuit_breaker import CircuitBreakerOpenError
from coreason_adlc_api.middleware.proxy import InferenceProxyService
from coreason_adlc_api.routers.interceptor import chat_completions
from coreason_adlc_api.routers.schemas import ChatCompletionRequest, ChatMessage
from coreason_adlc_api.workbench.locking import acquire_draft_lock, refresh_lock, verify_lock_for_update
from coreason_adlc_api.workbench.schemas import ApprovalStatus, DraftResponse, DraftUpdate
from coreason_adlc_api.workbench.service import _check_status_for_update, transition_draft_status, update_draft

# --- Identity Tests ---


@pytest.mark.asyncio
async def test_identity_token_missing_oid_claim(mock_db_session: AsyncMock) -> None:
    with patch("jwt.decode") as mock_decode:
        mock_decode.return_value = {"email": "test@example.com"}  # No sub/oid
        header = "Bearer some.token.here"
        with patch("coreason_adlc_api.auth.identity._JWKS_CLIENT") as mock_jwks:
            mock_jwks.get_signing_key_from_jwt.return_value.key = "fake_key"
            with pytest.raises(HTTPException) as exc:
                await parse_and_validate_token(header, session=mock_db_session)
            assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_identity_expired_token(mock_db_session: AsyncMock) -> None:
    header = "Bearer some.token.here"
    with patch("coreason_adlc_api.auth.identity._JWKS_CLIENT") as mock_jwks:
        mock_jwks.get_signing_key_from_jwt.return_value.key = "fake_key"
        with patch("jwt.decode", side_effect=jwt.ExpiredSignatureError("Expired")):
            with pytest.raises(HTTPException) as exc:
                await parse_and_validate_token(header, session=mock_db_session)
            assert exc.value.status_code == 401


# --- Proxy Tests ---


@pytest.mark.asyncio
async def test_proxy_get_provider_fallback() -> None:
    service = InferenceProxyService()
    with patch("litellm.get_llm_provider", side_effect=Exception("Unknown")):
        assert service.get_provider_for_model("gpt-4") == "openai"


@pytest.mark.asyncio
async def test_proxy_get_api_key_not_found(mock_db_session: AsyncMock) -> None:
    service = InferenceProxyService()
    mock_db_session.execute.return_value.fetchone.return_value = None
    with patch("coreason_adlc_api.middleware.proxy.async_session_factory") as mock_factory:
        mock_factory.return_value.__aenter__.return_value = mock_db_session
        with pytest.raises(HTTPException) as exc:
            await service.get_api_key_for_model("test-auc", "gpt-4")
        assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_proxy_get_api_key_decrypt_error(mock_db_session: AsyncMock) -> None:
    service = InferenceProxyService()
    mock_db_session.execute.return_value.fetchone.return_value = (b"encrypted",)
    with patch("coreason_adlc_api.middleware.proxy.async_session_factory") as mock_factory:
        mock_factory.return_value.__aenter__.return_value = mock_db_session
        with patch("coreason_adlc_api.middleware.proxy.VaultCrypto") as MockCrypto:
            MockCrypto.return_value.decrypt_secret.side_effect = Exception("Decrypt fail")
            with pytest.raises(HTTPException) as exc:
                await service.get_api_key_for_model("test-auc", "gpt-4")
            assert exc.value.status_code == 500


@pytest.mark.asyncio
async def test_proxy_execute_inference_circuit_breaker_open(mock_db_session: AsyncMock) -> None:
    service = InferenceProxyService()
    with patch.object(service, "get_api_key_for_model", return_value="sk-fake"):
        mock_breaker = MagicMock()
        mock_breaker.__aenter__.side_effect = CircuitBreakerOpenError("Open")
        mock_breaker.__aexit__ = AsyncMock()
        with patch.object(service, "get_circuit_breaker", return_value=mock_breaker):
            with pytest.raises(HTTPException) as exc:
                await service.execute_inference([], "gpt-4", "test-auc")
            assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_proxy_execute_inference_generic_error(mock_db_session: AsyncMock) -> None:
    service = InferenceProxyService()
    with patch.object(service, "get_api_key_for_model", return_value="sk-fake"):
        with patch("litellm.acompletion", side_effect=Exception("Random failure")):
            with pytest.raises(HTTPException) as exc:
                await service.execute_inference([], "gpt-4", "test-auc")
            assert exc.value.status_code == 500


# --- Locking Tests ---


@pytest.mark.asyncio
async def test_acquire_lock_not_found(mock_db_session: AsyncMock) -> None:
    mock_db_session.execute.return_value.fetchone.return_value = None
    with pytest.raises(HTTPException) as exc:
        await acquire_draft_lock(mock_db_session, uuid.uuid4(), uuid.uuid4(), [])
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_refresh_lock_not_found_on_check(mock_db_session: AsyncMock) -> None:
    mock_res_update = MagicMock()
    mock_res_update.rowcount = 0
    mock_res_check = MagicMock()
    mock_res_check.fetchone.return_value = None
    mock_db_session.execute.side_effect = [mock_res_update, mock_res_check]
    with pytest.raises(HTTPException) as exc:
        await refresh_lock(mock_db_session, uuid.uuid4(), uuid.uuid4())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_refresh_lock_not_held(mock_db_session: AsyncMock) -> None:
    user_id = uuid.uuid4()
    other_user = uuid.uuid4()
    mock_res_update = MagicMock()
    mock_res_update.rowcount = 0
    mock_res_check = MagicMock()
    mock_res_check.fetchone.return_value = (other_user,)
    mock_db_session.execute.side_effect = [mock_res_update, mock_res_check]
    with pytest.raises(HTTPException) as exc:
        await refresh_lock(mock_db_session, uuid.uuid4(), user_id)
    assert exc.value.status_code == 423


@pytest.mark.asyncio
async def test_verify_lock_not_found(mock_db_session: AsyncMock) -> None:
    mock_db_session.execute.return_value.fetchone.return_value = None
    with pytest.raises(HTTPException) as exc:
        await verify_lock_for_update(mock_db_session, uuid.uuid4(), uuid.uuid4())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_verify_lock_expired(mock_db_session: AsyncMock) -> None:
    user_id = uuid.uuid4()
    expiry_past = datetime.now(timezone.utc) - timedelta(seconds=1)
    mock_db_session.execute.return_value.fetchone.return_value = (user_id, expiry_past)
    with pytest.raises(HTTPException) as exc:
        await verify_lock_for_update(mock_db_session, uuid.uuid4(), user_id)
    assert exc.value.status_code == 423


# --- Workbench Service Tests ---


@pytest.mark.asyncio
async def test_update_draft_full_coverage(mock_db_session: AsyncMock) -> None:
    draft_id = uuid.uuid4()
    user_id = uuid.uuid4()
    update = DraftUpdate(title="New Title", oas_content={"a": 1}, runtime_env="env")

    def side_effect(stmt: Any, params: Any = None) -> MagicMock:
        query = str(stmt)
        res = MagicMock(spec=Result)
        if "SELECT status" in query:
            res.fetchone.return_value = (ApprovalStatus.DRAFT,)
        elif "UPDATE workbench.agent_drafts" in query:
            res.mappings.return_value.fetchone.return_value = {
                "draft_id": draft_id,
                "user_uuid": user_id,
                "auc_id": "auc",
                "title": "New Title",
                "oas_content": {"a": 1},
                "runtime_env": "env",
                "status": ApprovalStatus.PENDING,
                "created_at": datetime.now(),
                "updated_at": datetime.now(),
                "locked_by_user": user_id,
                "lock_expiry": datetime.now() + timedelta(minutes=5),
            }
        else:
            res.fetchone.return_value = None
        return res

    mock_db_session.execute.side_effect = side_effect
    with patch("coreason_adlc_api.workbench.service.verify_lock_for_update"):
        res = await update_draft(mock_db_session, draft_id, update, user_id)
    assert res.title == "New Title"


@pytest.mark.asyncio
async def test_transition_draft_status_coverage(mock_db_session: AsyncMock) -> None:
    draft_id = uuid.uuid4()
    user_id = uuid.uuid4()
    mock_db_session.execute.return_value.fetchone.return_value = None
    with pytest.raises(HTTPException) as exc:
        await transition_draft_status(mock_db_session, draft_id, user_id, ApprovalStatus.PENDING)
    assert exc.value.status_code == 404

    mock_db_session.execute.return_value.fetchone.return_value = (ApprovalStatus.DRAFT,)
    with pytest.raises(HTTPException) as exc:
        await transition_draft_status(mock_db_session, draft_id, user_id, ApprovalStatus.APPROVED)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_transition_draft_pending_to_approved(mock_db_session: AsyncMock) -> None:
    draft_id = uuid.uuid4()
    user_id = uuid.uuid4()
    mock_draft_row = {
        "draft_id": draft_id,
        "user_uuid": user_id,
        "auc_id": "auc",
        "title": "T",
        "oas_content": {},
        "status": ApprovalStatus.APPROVED,
        "created_at": datetime.now(),
        "updated_at": datetime.now(),
        "runtime_env": "r",
        "is_deleted": False,
    }

    def side_effect(stmt: Any, params: Any = None) -> MagicMock:
        query = str(stmt)
        res = MagicMock(spec=Result)
        if "SELECT status" in query:
            res.fetchone.return_value = (ApprovalStatus.PENDING,)
        elif "UPDATE workbench.agent_drafts" in query:
            res.mappings.return_value.fetchone.return_value = mock_draft_row
        return res

    mock_db_session.execute.side_effect = side_effect
    res = await transition_draft_status(mock_db_session, draft_id, user_id, ApprovalStatus.APPROVED)
    assert res.status == ApprovalStatus.APPROVED


@pytest.mark.asyncio
async def test_check_status_for_update_coverage(mock_db_session: AsyncMock) -> None:
    mock_db_session.execute.return_value.fetchone.return_value = None
    with pytest.raises(HTTPException) as exc:
        await _check_status_for_update(mock_db_session, uuid.uuid4())
    assert exc.value.status_code == 404
    mock_db_session.execute.return_value.fetchone.return_value = (ApprovalStatus.PENDING,)
    with pytest.raises(HTTPException) as exc:
        await _check_status_for_update(mock_db_session, uuid.uuid4())
    assert exc.value.status_code == 409


# --- Router Tests (TestClient) ---


def test_router_approve_draft_no_manager(mock_db_session: AsyncMock) -> None:
    draft_id = uuid.uuid4()
    app.dependency_overrides[get_db] = lambda: mock_db_session

    async def mock_get_identity() -> UserIdentity:
        return UserIdentity(oid=uuid.uuid4(), email="u@e.com", groups=[uuid.uuid4()], full_name="U")

    app.dependency_overrides[parse_and_validate_token] = mock_get_identity
    with patch("coreason_adlc_api.routers.workbench._get_user_roles", return_value=["USER"]):
        client = TestClient(app)
        resp = client.post(f"/api/v1/workbench/drafts/{draft_id}/approve")
        assert resp.status_code == 403


def test_router_reject_draft_no_manager(mock_db_session: AsyncMock) -> None:
    draft_id = uuid.uuid4()
    app.dependency_overrides[get_db] = lambda: mock_db_session

    async def mock_get_identity() -> UserIdentity:
        return UserIdentity(oid=uuid.uuid4(), email="u@e.com", groups=[uuid.uuid4()], full_name="U")

    app.dependency_overrides[parse_and_validate_token] = mock_get_identity
    with patch("coreason_adlc_api.routers.workbench._get_user_roles", return_value=["USER"]):
        client = TestClient(app)
        resp = client.post(f"/api/v1/workbench/drafts/{draft_id}/reject")
        assert resp.status_code == 403


def test_router_submit_draft_not_found(mock_db_session: AsyncMock) -> None:
    draft_id = uuid.uuid4()
    app.dependency_overrides[get_db] = lambda: mock_db_session

    async def mock_get_identity() -> UserIdentity:
        return UserIdentity(oid=uuid.uuid4(), email="u@e.com", groups=[uuid.uuid4()], full_name="U")

    app.dependency_overrides[parse_and_validate_token] = mock_get_identity
    with patch("coreason_adlc_api.routers.workbench.get_draft_by_id", return_value=None):
        client = TestClient(app)
        resp = client.post(f"/api/v1/workbench/drafts/{draft_id}/submit")
        assert resp.status_code == 404


# NEW: Happy Path Tests for Routers to cover remaining lines


def test_router_submit_draft_success(mock_db_session: AsyncMock) -> None:
    draft_id = uuid.uuid4()
    app.dependency_overrides[get_db] = lambda: mock_db_session

    async def mock_get_identity() -> UserIdentity:
        return UserIdentity(oid=uuid.uuid4(), email="u@e.com", groups=[uuid.uuid4()], full_name="U")

    app.dependency_overrides[parse_and_validate_token] = mock_get_identity

    mock_draft = DraftResponse(
        draft_id=draft_id,
        user_uuid=uuid.uuid4(),
        auc_id="p1",
        title="t",
        oas_content={},
        created_at=datetime.now(),
        updated_at=datetime.now(),
        status=ApprovalStatus.DRAFT,
    )
    mock_draft_pending = mock_draft.model_copy(update={"status": ApprovalStatus.PENDING})

    # We break up the patch lines to keep them under 120 chars
    p1 = patch("coreason_adlc_api.routers.workbench.get_draft_by_id", return_value=mock_draft)
    p2 = patch("coreason_adlc_api.routers.workbench._verify_project_access")
    p3 = patch("coreason_adlc_api.routers.workbench.transition_draft_status", return_value=mock_draft_pending)

    with p1, p2, p3:
        client = TestClient(app)
        resp = client.post(f"/api/v1/workbench/drafts/{draft_id}/submit")
        assert resp.status_code == 200
        assert resp.json()["status"] == ApprovalStatus.PENDING.value


def test_router_approve_draft_success(mock_db_session: AsyncMock) -> None:
    draft_id = uuid.uuid4()
    app.dependency_overrides[get_db] = lambda: mock_db_session

    async def mock_get_identity() -> UserIdentity:
        return UserIdentity(oid=uuid.uuid4(), email="u@e.com", groups=[uuid.uuid4()], full_name="U")

    app.dependency_overrides[parse_and_validate_token] = mock_get_identity

    mock_draft = DraftResponse(
        draft_id=draft_id,
        user_uuid=uuid.uuid4(),
        auc_id="p1",
        title="t",
        oas_content={},
        created_at=datetime.now(),
        updated_at=datetime.now(),
        status=ApprovalStatus.PENDING,
    )
    mock_draft_approved = mock_draft.model_copy(update={"status": ApprovalStatus.APPROVED})

    p1 = patch("coreason_adlc_api.routers.workbench._get_user_roles", return_value=["MANAGER"])
    p2 = patch("coreason_adlc_api.routers.workbench.get_draft_by_id", return_value=mock_draft)
    p3 = patch("coreason_adlc_api.routers.workbench._verify_project_access")
    p4 = patch("coreason_adlc_api.routers.workbench.transition_draft_status", return_value=mock_draft_approved)

    with p1, p2, p3, p4:
        client = TestClient(app)
        resp = client.post(f"/api/v1/workbench/drafts/{draft_id}/approve")
        assert resp.status_code == 200
        assert resp.json()["status"] == ApprovalStatus.APPROVED.value


def test_router_reject_draft_success(mock_db_session: AsyncMock) -> None:
    draft_id = uuid.uuid4()
    app.dependency_overrides[get_db] = lambda: mock_db_session

    async def mock_get_identity() -> UserIdentity:
        return UserIdentity(oid=uuid.uuid4(), email="u@e.com", groups=[uuid.uuid4()], full_name="U")

    app.dependency_overrides[parse_and_validate_token] = mock_get_identity

    mock_draft = DraftResponse(
        draft_id=draft_id,
        user_uuid=uuid.uuid4(),
        auc_id="p1",
        title="t",
        oas_content={},
        created_at=datetime.now(),
        updated_at=datetime.now(),
        status=ApprovalStatus.PENDING,
    )
    mock_draft_rejected = mock_draft.model_copy(update={"status": ApprovalStatus.REJECTED})

    p1 = patch("coreason_adlc_api.routers.workbench._get_user_roles", return_value=["MANAGER"])
    p2 = patch("coreason_adlc_api.routers.workbench.get_draft_by_id", return_value=mock_draft)
    p3 = patch("coreason_adlc_api.routers.workbench._verify_project_access")
    p4 = patch("coreason_adlc_api.routers.workbench.transition_draft_status", return_value=mock_draft_rejected)

    with p1, p2, p3, p4:
        client = TestClient(app)
        resp = client.post(f"/api/v1/workbench/drafts/{draft_id}/reject")
        assert resp.status_code == 200
        assert resp.json()["status"] == ApprovalStatus.REJECTED.value


# --- Interceptor Tests ---


@pytest.mark.asyncio
async def test_chat_completions_cost_calculation_failure(mock_db_session: AsyncMock) -> None:
    req = ChatCompletionRequest(
        messages=[ChatMessage(role="user", content="hello")], model="gpt-4", auc_id="test-auc", user_context={}
    )
    mock_bg = MagicMock()
    mock_user = MagicMock(oid=uuid.uuid4())
    mock_budget = AsyncMock()
    mock_proxy = AsyncMock()
    mock_telemetry = AsyncMock()
    mock_proxy.estimate_request_cost.return_value = 0.01
    mock_response = {
        "id": "chatcmpl-123",
        "object": "chat.completion",
        "created": 1677652288,
        "model": "gpt-4",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "world"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
    }
    mock_proxy.execute_inference.return_value = mock_response
    with patch("litellm.completion_cost", side_effect=Exception("Cost Error")):
        res = await chat_completions(req, mock_bg, mock_user, mock_budget, mock_proxy, mock_telemetry)
    assert res.choices[0]["message"]["content"] == "world"
    mock_bg.add_task.assert_called_once()
