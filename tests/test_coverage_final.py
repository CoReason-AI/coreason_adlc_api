# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

import time
from unittest import mock

import pytest
from fastapi import HTTPException

from coreason_adlc_api.middleware.circuit_breaker import AsyncCircuitBreaker, CircuitBreakerOpenError
from coreason_adlc_api.middleware.proxy import (
    _breakers,
    execute_inference_proxy,
    get_api_key_for_model,
    get_circuit_breaker,
)


@pytest.mark.asyncio
async def test_circuit_breaker_call_method() -> None:
    """Test the 'call' method of AsyncCircuitBreaker which was missing coverage."""
    # Use small window/timeout for testing
    cb = AsyncCircuitBreaker(fail_max=2, reset_timeout=0.1, time_window=1.0)

    # 1. Success case
    async def success_func() -> str:
        return "ok"

    res = await cb.call(success_func)
    assert res == "ok"
    assert cb.state == "closed"
    assert len(cb.failure_history) == 0

    # 2. Failure case
    async def fail_func() -> None:
        raise ValueError("fail")

    with pytest.raises(ValueError):
        await cb.call(fail_func)
    assert len(cb.failure_history) == 1

    with pytest.raises(ValueError):
        await cb.call(fail_func)
    assert len(cb.failure_history) == 2
    assert cb.state == "open"

    # 3. Call while open -> CircuitBreakerOpenError
    with pytest.raises(CircuitBreakerOpenError):
        await cb.call(success_func)

    # 4. Wait for reset
    import asyncio

    await asyncio.sleep(0.2)

    # 5. Half-open success
    res = await cb.call(success_func)
    assert res == "ok"
    assert cb.state == "closed"
    # Success clears history in Half-Open transition
    assert len(cb.failure_history) == 0


@pytest.mark.asyncio
async def test_get_api_key_decryption_failure() -> None:
    """Test get_api_key_for_model when decryption fails."""
    with (
        mock.patch("coreason_adlc_api.middleware.proxy.get_pool") as mock_pool,
        mock.patch("coreason_adlc_api.middleware.proxy.VaultCrypto") as mock_crypto_cls,
    ):
        # Correctly mock async fetchrow
        mock_pool.return_value.fetchrow = mock.AsyncMock(return_value={"encrypted_value": "bad-key"})

        # Mock instance raising error on decrypt
        mock_instance = mock.MagicMock()
        mock_instance.decrypt_secret.side_effect = Exception("Decryption Error")
        mock_crypto_cls.return_value = mock_instance

        with pytest.raises(HTTPException) as exc:
            await get_api_key_for_model("proj-1", "gpt-4")

        assert exc.value.status_code == 500
        assert "Secure Vault access failed" in exc.value.detail


@pytest.mark.asyncio
async def test_proxy_generic_exception() -> None:
    """Test execute_inference_proxy handling generic exception from inside block."""
    with (
        mock.patch("coreason_adlc_api.middleware.proxy.get_api_key_for_model") as mock_get_key,
        mock.patch("coreason_adlc_api.middleware.proxy.litellm.acompletion") as mock_completion,
        mock.patch("coreason_adlc_api.middleware.proxy.litellm.get_llm_provider") as mock_get_provider,
    ):
        mock_get_key.return_value = "key"
        mock_completion.side_effect = Exception("Unexpected Error")
        mock_get_provider.return_value = ("openai", "model", "k", "b")

        # Reset breaker state
        _breakers.clear()

        with pytest.raises(HTTPException) as exc:
            await execute_inference_proxy([], "gpt-4", "proj-1")

        assert exc.value.status_code == 500
        assert "Unexpected Error" in exc.value.detail


@pytest.mark.asyncio
async def test_proxy_breaker_open_exception() -> None:
    """Explicitly test the CircuitBreakerOpenError catch block in proxy."""
    # We can mock the breaker instance on the proxy module to force it to raise

    # We assume provider is openai
    breaker = get_circuit_breaker("openai")
    breaker.state = "open"
    breaker.last_failure_time = time.time()

    # Need to mock get_api_key otherwise it might fail first (if we didn't mock DB)

    with (
        mock.patch("coreason_adlc_api.middleware.proxy.get_api_key_for_model") as mock_get_key,
        mock.patch("coreason_adlc_api.middleware.proxy.litellm.get_llm_provider") as mock_get_provider,
    ):
        mock_get_key.return_value = "key"
        mock_get_provider.return_value = ("openai", "model", "k", "b")

        with pytest.raises(HTTPException) as exc:
            await execute_inference_proxy([], "gpt-4", "proj-1")

        assert exc.value.status_code == 503
        assert "Upstream model service is currently unstable" in exc.value.detail
