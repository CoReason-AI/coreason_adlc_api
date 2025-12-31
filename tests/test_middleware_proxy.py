from typing import Any

# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api
from unittest import mock

import pytest
from fastapi import HTTPException
from aiobreaker import CircuitBreakerError

from coreason_adlc_api.middleware.proxy import InferenceProxyService
from coreason_adlc_api.db_models import Secret


@pytest.fixture
def mock_db_session() -> Any:
    # Use generic AsyncMock for session
    session = mock.AsyncMock()
    # SQLModel exec return
    result_mock = mock.MagicMock()
    result_mock.first.return_value = None
    session.exec.return_value = result_mock

    # Factory mock
    factory_mock = mock.MagicMock()
    factory_mock.__aenter__.return_value = session
    factory_mock.__aexit__.return_value = None

    with mock.patch("coreason_adlc_api.middleware.proxy.async_session_factory", return_value=factory_mock):
        yield session


@pytest.fixture
def mock_vault_crypto() -> Any:
    with mock.patch("coreason_adlc_api.middleware.proxy.VaultCrypto") as mock_crypto:
        instance = mock.MagicMock()
        instance.decrypt_secret.return_value = "raw-api-key"
        mock_crypto.return_value = instance
        yield instance


@pytest.fixture
def mock_litellm() -> Any:
    with mock.patch("coreason_adlc_api.middleware.proxy.litellm") as mock_llm:
        mock_llm.get_llm_provider.return_value = ("openai", "key", "conf")
        mock_llm.acompletion = mock.AsyncMock()
        mock_llm.acompletion.return_value = {"choices": [{"message": {"content": "response"}}]}
        yield mock_llm


@pytest.fixture
def proxy_service() -> InferenceProxyService:
    return InferenceProxyService()


@pytest.mark.asyncio
async def test_proxy_success(
    proxy_service: InferenceProxyService, mock_db_session: Any, mock_vault_crypto: Any, mock_litellm: Any
) -> None:
    """Test successful proxy execution."""
    # Setup DB
    mock_secret = mock.MagicMock(spec=Secret)
    mock_secret.encrypted_value = "enc-key"
    mock_db_session.exec.return_value.first.return_value = mock_secret

    messages = [{"role": "user", "content": "hello"}]
    model = "gpt-4"
    auc_id = "proj-1"

    response = await proxy_service.execute_inference(messages, model, auc_id)

    assert response["choices"][0]["message"]["content"] == "response"

    # Verify Vault call
    mock_vault_crypto.decrypt_secret.assert_called_with("enc-key")

    # Verify LiteLLM call
    mock_litellm.acompletion.assert_called_once()
    kwargs = mock_litellm.acompletion.call_args[1]
    assert kwargs["temperature"] == 0.0
    assert kwargs["seed"] == 42
    assert kwargs["api_key"] == "raw-api-key"


@pytest.mark.asyncio
async def test_proxy_missing_key(proxy_service: InferenceProxyService, mock_db_session: Any, mock_litellm: Any) -> None:
    """Test 404 when key not found."""
    mock_db_session.exec.return_value.first.return_value = None

    with pytest.raises(HTTPException) as exc:
        await proxy_service.execute_inference([], "gpt-4", "proj-1")

    assert exc.value.status_code == 404
    assert "API Key not configured" in exc.value.detail


@pytest.mark.asyncio
async def test_proxy_circuit_breaker(
    proxy_service: InferenceProxyService, mock_db_session: Any, mock_vault_crypto: Any, mock_litellm: Any
) -> None:
    """Test that circuit breaker opens after failures."""
    mock_secret = mock.MagicMock(spec=Secret)
    mock_secret.encrypted_value = "enc-key"
    mock_db_session.exec.return_value.first.return_value = mock_secret

    # Get the specific breaker for 'openai' (default mock provider)
    breaker = proxy_service.get_circuit_breaker("openai")

    # Manually trip by mocking state or using open() method if available
    # aiobreaker CircuitBreaker has .open() method
    breaker.open() # type: ignore[attr-defined]

    # Verify it is open

    # Next call should raise ServiceUnavailable (Circuit Open) immediately

    with pytest.raises(HTTPException) as exc:
        await proxy_service.execute_inference([], "gpt-4", "proj-1")

    assert exc.value.status_code == 503
    assert "Upstream model service is currently unstable" in exc.value.detail

    # Cleanup
    breaker.close() # type: ignore[attr-defined]
