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
from coreason_veritas.exceptions import CircuitOpenError
from fastapi import HTTPException

from coreason_adlc_api.middleware.proxy import (
    InferenceProxyService,
    _breakers,
)


@pytest.mark.asyncio
async def test_get_api_key_decryption_failure() -> None:
    """Test get_api_key_for_model when decryption fails."""
    proxy_service = InferenceProxyService()

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
            await proxy_service.get_api_key_for_model("proj-1", "gpt-4")

        assert exc.value.status_code == 500
        assert "Secure Vault access failed" in exc.value.detail


@pytest.mark.asyncio
async def test_proxy_generic_exception() -> None:
    """Test execute_inference_proxy handling generic exception from inside block."""
    proxy_service = InferenceProxyService()

    # We patch the METHODS of the service class if we want to mock internal calls,
    # OR we mock the external dependencies.
    # Here we mock dependencies.

    with (
        mock.patch.object(proxy_service, "get_api_key_for_model") as mock_get_key,
        mock.patch("coreason_adlc_api.middleware.proxy.litellm.acompletion") as mock_completion,
        mock.patch("coreason_adlc_api.middleware.proxy.litellm.get_llm_provider") as mock_get_provider,
    ):
        mock_get_key.return_value = "key"
        mock_completion.side_effect = Exception("Unexpected Error")
        mock_get_provider.return_value = ("openai", "model", "k", "b")

        # Reset breaker state
        _breakers.clear()

        with pytest.raises(HTTPException) as exc:
            await proxy_service.execute_inference([], "gpt-4", "proj-1")

        assert exc.value.status_code == 500
        assert "Unexpected Error" in exc.value.detail


@pytest.mark.asyncio
async def test_proxy_breaker_open_exception() -> None:
    """Explicitly test the CircuitOpenError catch block in proxy."""
    proxy_service = InferenceProxyService()

    # We need to mock the breaker to ensure it raises CircuitOpenError
    mock_breaker = mock.AsyncMock()
    mock_breaker.__aenter__.side_effect = CircuitOpenError("Circuit is open")
    mock_breaker.__aexit__.return_value = None

    with (
        mock.patch.object(proxy_service, "get_api_key_for_model") as mock_get_key,
        mock.patch("coreason_adlc_api.middleware.proxy.litellm.get_llm_provider") as mock_get_provider,
        mock.patch.object(proxy_service, "get_circuit_breaker", return_value=mock_breaker),
    ):
        mock_get_key.return_value = "key"
        mock_get_provider.return_value = ("openai", "model", "k", "b")

        with pytest.raises(HTTPException) as exc:
            await proxy_service.execute_inference([], "gpt-4", "proj-1")

        assert exc.value.status_code == 503
        assert "Upstream model service is currently unstable" in exc.value.detail
