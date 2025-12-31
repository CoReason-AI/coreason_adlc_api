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
from sqlalchemy.engine import Result

from coreason_adlc_api.auth.identity import parse_and_validate_token
from coreason_adlc_api.middleware.circuit_breaker import CircuitBreakerOpenError
from coreason_adlc_api.middleware.proxy import InferenceProxyService
from coreason_adlc_api.routers.interceptor import chat_completions
from coreason_adlc_api.routers.schemas import ChatCompletionRequest, ChatMessage
from coreason_adlc_api.routers.workbench import _get_user_roles, approve_draft, reject_draft, submit_draft
from coreason_adlc_api.workbench.locking import acquire_draft_lock, refresh_lock, verify_lock_for_update
from coreason_adlc_api.workbench.schemas import ApprovalStatus, DraftUpdate
from coreason_adlc_api.workbench.service import _check_status_for_update, transition_draft_status, update_draft

# --- Identity Tests ---


@pytest.mark.asyncio
async def test_identity_token_missing_oid_claim(mock_db_session: AsyncMock, mock_oidc_factory: Any) -> None:
    """
    Test that if 'oid' and 'sub' are missing, ValueError -> HTTPException is raised.
    """
    with patch("jwt.decode") as mock_decode:
        mock_decode.return_value = {"email": "test@example.com"}  # No sub/oid
        header = "Bearer some.token.here"

        with patch("coreason_adlc_api.auth.identity._JWKS_CLIENT") as mock_jwks:
            mock_jwks.get_signing_key_from_jwt.return_value.key = "fake_key"

            with pytest.raises(HTTPException) as exc:
                await parse_and_validate_token(header, session=mock_db_session)

            assert exc.value.status_code == 401
            assert "Malformed token claims" in exc.value.detail


@pytest.mark.asyncio
async def test_identity_expired_token(mock_db_session: AsyncMock) -> None:
    """
    Explicitly test ExpiredSignatureError handling.
    """
    header = "Bearer some.token.here"
    with patch("coreason_adlc_api.auth.identity._JWKS_CLIENT") as mock_jwks:
        mock_jwks.get_signing_key_from_jwt.return_value.key = "fake_key"

        with patch("jwt.decode", side_effect=jwt.ExpiredSignatureError("Expired")):
            with pytest.raises(HTTPException) as exc:
                await parse_and_validate_token(header, session=mock_db_session)

            assert exc.value.status_code == 401
            assert "Token has expired" in exc.value.detail


# --- Proxy Tests ---


@pytest.mark.asyncio
async def test_proxy_get_provider_fallback() -> None:
    """Test get_provider_for_model fallback when litellm fails."""
    service = InferenceProxyService()

    with patch("litellm.get_llm_provider", side_effect=Exception("Unknown")):
        assert service.get_provider_for_model("gpt-4") == "openai"
        assert service.get_provider_for_model("anthropic/claude") == "anthropic"


@pytest.mark.asyncio
async def test_proxy_get_api_key_not_found(mock_db_session: AsyncMock) -> None:
    """Test get_api_key_for_model when row is missing (404)."""
    service = InferenceProxyService()
    mock_db_session.execute.return_value.fetchone.return_value = None

    with patch("coreason_adlc_api.middleware.proxy.async_session_factory") as mock_factory:
        mock_factory.return_value.__aenter__.return_value = mock_db_session

        with pytest.raises(HTTPException) as exc:
            await service.get_api_key_for_model("test-auc", "gpt-4")

        assert exc.value.status_code == 404
        assert "not configured" in exc.value.detail


@pytest.mark.asyncio
async def test_proxy_get_api_key_decrypt_error(mock_db_session: AsyncMock) -> None:
    """Test get_api_key_for_model when decryption fails (500)."""
    service = InferenceProxyService()
    mock_db_session.execute.return_value.fetchone.return_value = (b"encrypted",)

    with patch("coreason_adlc_api.middleware.proxy.async_session_factory") as mock_factory:
        mock_factory.return_value.__aenter__.return_value = mock_db_session

        with patch("coreason_adlc_api.middleware.proxy.VaultCrypto") as MockCrypto:
            MockCrypto.return_value.decrypt_secret.side_effect = Exception("Decrypt fail")

            with pytest.raises(HTTPException) as exc:
                await service.get_api_key_for_model("test-auc", "gpt-4")

            assert exc.value.status_code == 500
            assert "Secure Vault access failed" in exc.value.detail


@pytest.mark.asyncio
async def test_proxy_execute_inference_circuit_breaker_open(mock_db_session: AsyncMock) -> None:
    """Test execute_inference when circuit breaker is open (503)."""
    service = InferenceProxyService()

    with patch.object(service, "get_api_key_for_model", return_value="sk-fake"):
        mock_breaker = MagicMock()
        mock_breaker.__aenter__.side_effect = CircuitBreakerOpenError("Open")
        mock_breaker.__aexit__ = AsyncMock()

        with patch.object(service, "get_circuit_breaker", return_value=mock_breaker):
            with pytest.raises(HTTPException) as exc:
                await service.execute_inference([], "gpt-4", "test-auc")

            assert exc.value.status_code == 503
            assert "unstable" in exc.value.detail


@pytest.mark.asyncio
async def test_proxy_execute_inference_generic_error(mock_db_session: AsyncMock) -> None:
    """Test execute_inference generic error (500)."""
    service = InferenceProxyService()

    with patch.object(service, "get_api_key_for_model", return_value="sk-fake"):
        with patch("litellm.acompletion", side_effect=Exception("Random failure")):
            with pytest.raises(HTTPException) as exc:
                await service.execute_inference([], "gpt-4", "test-auc")

            assert exc.value.status_code == 500
            assert "Random failure" in exc.value.detail


# --- Locking Tests ---


@pytest.mark.asyncio
async def test_acquire_lock_not_found(mock_db_session: AsyncMock) -> None:
    """Test acquire_draft_lock when draft does not exist (404)."""
    mock_db_session.execute.return_value.fetchone.return_value = None
    with pytest.raises(HTTPException) as exc:
        await acquire_draft_lock(mock_db_session, uuid.uuid4(), uuid.uuid4(), [])
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_refresh_lock_not_found_on_check(mock_db_session: AsyncMock) -> None:
    """Test refresh_lock: Update affects 0 rows, then check reveals draft missing (404)."""
    # 1. Update returns rowcount 0
    mock_res_update = MagicMock()
    mock_res_update.rowcount = 0

    # 2. Check select returns None
    mock_res_check = MagicMock()
    mock_res_check.fetchone.return_value = None

    mock_db_session.execute.side_effect = [mock_res_update, mock_res_check]

    with pytest.raises(HTTPException) as exc:
        await refresh_lock(mock_db_session, uuid.uuid4(), uuid.uuid4())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_refresh_lock_not_held(mock_db_session: AsyncMock) -> None:
    """Test refresh_lock: Update affects 0 rows, check reveals locked by other (423)."""
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
    assert "You do not hold the lock" in exc.value.detail


@pytest.mark.asyncio
async def test_verify_lock_not_found(mock_db_session: AsyncMock) -> None:
    """Test verify_lock_for_update when draft missing (404)."""
    mock_db_session.execute.return_value.fetchone.return_value = None
    with pytest.raises(HTTPException) as exc:
        await verify_lock_for_update(mock_db_session, uuid.uuid4(), uuid.uuid4())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_verify_lock_expired(mock_db_session: AsyncMock) -> None:
    """Test verify_lock_for_update when lock expired (423)."""
    user_id = uuid.uuid4()
    expiry_past = datetime.now(timezone.utc) - timedelta(seconds=1)

    mock_db_session.execute.return_value.fetchone.return_value = (user_id, expiry_past)

    with pytest.raises(HTTPException) as exc:
        await verify_lock_for_update(mock_db_session, uuid.uuid4(), user_id)
    assert exc.value.status_code == 423
    assert "Lock expired" in exc.value.detail


# --- Workbench Service Tests ---


@pytest.mark.asyncio
async def test_update_draft_full_coverage(mock_db_session: AsyncMock) -> None:
    """
    Cover update_draft logic fully (happy path with fields).
    """
    draft_id = uuid.uuid4()
    user_id = uuid.uuid4()

    update = DraftUpdate(
        title="New Title",
        oas_content={"a": 1},
        runtime_env="env",
        # status Removed
    )

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
    assert res.status == ApprovalStatus.PENDING


@pytest.mark.asyncio
async def test_transition_draft_status_coverage(mock_db_session: AsyncMock) -> None:
    """
    Cover transition_draft_status: Not Found, Invalid Transition, Success.
    """
    draft_id = uuid.uuid4()
    user_id = uuid.uuid4()
    auc_id = "test-auc"

    # 1. Not Found
    mock_db_session.execute.return_value.fetchone.return_value = None
    with pytest.raises(HTTPException) as exc:
        await transition_draft_status(mock_db_session, draft_id, user_id, ApprovalStatus.PENDING)
    assert exc.value.status_code == 404

    # 2. Invalid Transition (DRAFT -> APPROVED)
    mock_db_session.execute.return_value.fetchone.return_value = (ApprovalStatus.DRAFT,)
    with pytest.raises(HTTPException) as exc:
        await transition_draft_status(mock_db_session, draft_id, user_id, ApprovalStatus.APPROVED)
    assert exc.value.status_code == 409

    # 3. Success (DRAFT -> PENDING)
    # Reset mock
    mock_db_session.execute.return_value.fetchone.return_value = (ApprovalStatus.DRAFT,)

    # Return full DraftResponse dict for mappings().fetchone()
    # We must provide all fields required by DraftResponse schema
    mock_draft_row = {
        "draft_id": draft_id,
        "user_uuid": user_id,
        "auc_id": auc_id,
        "title": "Test",
        "oas_content": {},
        "status": ApprovalStatus.PENDING,
        "created_at": datetime.now(),
        "updated_at": datetime.now(),
        "runtime_env": "reqs.txt",
        "is_deleted": False,
    }

    # We need to simulate TWO executes: Select Status, Update
    def side_effect(stmt: Any, params: Any = None) -> MagicMock:
        query = str(stmt)
        res = MagicMock(spec=Result)
        if "SELECT status" in query:
            res.fetchone.return_value = (ApprovalStatus.DRAFT,)
        elif "UPDATE workbench.agent_drafts" in query:
            res.mappings.return_value.fetchone.return_value = mock_draft_row
        return res

    mock_db_session.execute.side_effect = side_effect

    res = await transition_draft_status(mock_db_session, draft_id, user_id, ApprovalStatus.PENDING)
    assert res.status == ApprovalStatus.PENDING


@pytest.mark.asyncio
async def test_check_status_for_update_coverage(mock_db_session: AsyncMock) -> None:
    """
    Cover _check_status_for_update: Not found, Invalid status.
    """
    # 1. Not found (404)
    mock_db_session.execute.return_value.fetchone.return_value = None
    with pytest.raises(HTTPException) as exc:
        await _check_status_for_update(mock_db_session, uuid.uuid4())
    assert exc.value.status_code == 404

    # 2. Invalid Status (PENDING -> 409)
    mock_db_session.execute.return_value.fetchone.return_value = (ApprovalStatus.PENDING,)
    with pytest.raises(HTTPException) as exc:
        await _check_status_for_update(mock_db_session, uuid.uuid4())
    assert exc.value.status_code == 409


# --- Router Tests ---


@pytest.mark.asyncio
async def test_router_get_user_roles_empty(mock_db_session: AsyncMock) -> None:
    """Test _get_user_roles with empty groups list (returns [])."""
    res = await _get_user_roles(mock_db_session, [])
    assert res == []


@pytest.mark.asyncio
async def test_router_approve_draft_no_manager(mock_db_session: AsyncMock) -> None:
    """Test approve_draft without MANAGER role (403)."""
    identity = MagicMock(groups=[uuid.uuid4()], oid=uuid.uuid4())

    # Mock _get_user_roles to return non-manager
    with patch("coreason_adlc_api.routers.workbench._get_user_roles", return_value=["USER"]):
        with pytest.raises(HTTPException) as exc:
            await approve_draft(uuid.uuid4(), identity, mock_db_session)
        assert exc.value.status_code == 403
        assert "Only managers" in exc.value.detail


@pytest.mark.asyncio
async def test_router_reject_draft_no_manager(mock_db_session: AsyncMock) -> None:
    """Test reject_draft without MANAGER role (403)."""
    identity = MagicMock(groups=[uuid.uuid4()], oid=uuid.uuid4())

    with patch("coreason_adlc_api.routers.workbench._get_user_roles", return_value=["USER"]):
        with pytest.raises(HTTPException) as exc:
            await reject_draft(uuid.uuid4(), identity, mock_db_session)
        assert exc.value.status_code == 403
        assert "Only managers" in exc.value.detail


@pytest.mark.asyncio
async def test_router_submit_draft_not_found(mock_db_session: AsyncMock) -> None:
    """Test submit_draft when draft not found (404)."""
    identity = MagicMock(groups=[uuid.uuid4()], oid=uuid.uuid4())

    # Mock get_draft_by_id return None
    with patch("coreason_adlc_api.routers.workbench.get_draft_by_id", return_value=None):
        with pytest.raises(HTTPException) as exc:
            await submit_draft(uuid.uuid4(), identity, mock_db_session)
        assert exc.value.status_code == 404


# --- Interceptor Tests ---


@pytest.mark.asyncio
async def test_chat_completions_cost_calculation_failure(mock_db_session: AsyncMock) -> None:
    """
    Test chat_completions where litellm.completion_cost raises Exception.
    It should be caught and ignored (pass).
    """
    req = ChatCompletionRequest(
        messages=[ChatMessage(role="user", content="hello")], model="gpt-4", auc_id="test-auc", user_context={}
    )

    # Mocks
    mock_bg = MagicMock()
    mock_user = MagicMock(oid=uuid.uuid4())
    mock_budget = AsyncMock()
    mock_proxy = AsyncMock()
    mock_telemetry = AsyncMock()

    # Proxy estimate cost return
    mock_proxy.estimate_request_cost.return_value = 0.01

    # Proxy execute return
    # MUST contain all fields for ChatCompletionResponse
    mock_response = {
        "id": "chatcmpl-123",
        "object": "chat.completion",
        "created": 1677652288,
        "model": "gpt-4",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "world"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
    }
    mock_proxy.execute_inference.return_value = mock_response

    # Patch litellm.completion_cost to raise
    with patch("litellm.completion_cost", side_effect=Exception("Cost Error")):
        res = await chat_completions(req, mock_bg, mock_user, mock_budget, mock_proxy, mock_telemetry)

    assert res.choices[0]["message"]["content"] == "world"
    # Ensure telemetry was called (even if cost calc failed)
    mock_bg.add_task.assert_called_once()
