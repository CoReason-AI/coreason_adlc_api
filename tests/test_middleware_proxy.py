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
from coreason_adlc_api.middleware.proxy import execute_inference_proxy, proxy_breaker
from fastapi import HTTPException


@pytest.fixture
def mock_db_pool() -> Any:
    with mock.patch("coreason_adlc_api.middleware.proxy.get_pool") as mock_pool:
        pool_instance = mock.AsyncMock()
        mock_pool.return_value = pool_instance
        yield pool_instance


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


@pytest.mark.asyncio
async def test_proxy_success(mock_db_pool: Any, mock_vault_crypto: Any, mock_litellm: Any) -> None:
    """Test successful proxy execution."""
    # Setup DB
    mock_db_pool.fetchrow.return_value = {"encrypted_value": "enc-key"}

    messages = [{"role": "user", "content": "hello"}]
    model = "gpt-4"
    auc_id = "proj-1"

    response = await execute_inference_proxy(messages, model, auc_id)

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
async def test_proxy_missing_key(mock_db_pool: Any, mock_litellm: Any) -> None:
    """Test 404 when key not found."""
    mock_db_pool.fetchrow.return_value = None

    with pytest.raises(HTTPException) as exc:
        await execute_inference_proxy([], "gpt-4", "proj-1")

    assert exc.value.status_code == 404
    assert "API Key not configured" in exc.value.detail


@pytest.mark.asyncio
async def test_proxy_circuit_breaker(mock_db_pool: Any, mock_vault_crypto: Any, mock_litellm: Any) -> None:
    """Test that circuit breaker opens after failures."""
    mock_db_pool.fetchrow.return_value = {"encrypted_value": "enc-key"}

    # Reset breaker (manual reset for custom class)
    proxy_breaker.state = "closed"
    proxy_breaker.failure_history.clear()

    # Manually trip
    proxy_breaker.state = "open"
    proxy_breaker.last_failure_time = 1234567890  # Long ago? No, wait.
    # If last_failure_time is old, it might try half-open.
    # We want it to be RECENT to ensure it stays open.
    import time

    proxy_breaker.last_failure_time = time.time()

    # Next call should raise ServiceUnavailable (Circuit Open) immediately
    mock_litellm.acompletion.side_effect = None

    with pytest.raises(HTTPException) as exc:
        await execute_inference_proxy([], "gpt-4", "proj-1")

    assert exc.value.status_code == 503
    assert "Upstream model service is currently unstable" in exc.value.detail

    # Cleanup
    proxy_breaker.state = "closed"
