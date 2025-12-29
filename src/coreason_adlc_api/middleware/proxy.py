# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

from typing import Any, Dict, List

import litellm
from fastapi import HTTPException, status
from loguru import logger

from coreason_adlc_api.db import get_pool
from coreason_adlc_api.middleware.circuit_breaker import AsyncCircuitBreaker, CircuitBreakerOpenError
from coreason_adlc_api.vault.crypto import VaultCrypto

# Circuit Breaker Registry
# Stores circuit breakers keyed by provider name
_breakers: Dict[str, AsyncCircuitBreaker] = {}


def get_circuit_breaker(provider: str) -> AsyncCircuitBreaker:
    """
    Returns the circuit breaker for the given provider.
    Creates a new one if it doesn't exist.
    """
    if provider not in _breakers:
        # Threshold: 5 errors.
        # Reset timeout: 60 seconds.
        _breakers[provider] = AsyncCircuitBreaker(fail_max=5, reset_timeout=60)
    return _breakers[provider]


def get_provider_for_model(model: str) -> str:
    """
    Determines the provider for a given model.
    """
    try:
        # litellm.get_llm_provider returns (provider, model, api_key, api_base)
        provider, _, _, _ = litellm.get_llm_provider(model)  # type: ignore[attr-defined]
        return str(provider)
    except Exception:
        # Fallback or strict?
        return model.split("/")[0] if "/" in model else "openai"


async def get_api_key_for_model(auc_id: str, model: str) -> str:
    """
    Fetches and decrypts the API key for the given model and project (AUC ID).
    """
    pool = get_pool()

    provider = get_provider_for_model(model)

    # Spec FR-API-013 says `service_name`.
    # Let's assume we store keys by service_name (e.g. 'openai').
    query = """
        SELECT encrypted_value
        FROM vault.secrets
        WHERE auc_id = $1 AND service_name = $2
    """

    row = await pool.fetchrow(query, auc_id, provider)

    if not row:
        logger.error(f"No API key found for project {auc_id} service {provider}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"API Key not configured for {provider} in this project."
        )

    encrypted_value = row["encrypted_value"]

    # Decrypt in memory
    try:
        crypto = VaultCrypto()
        return crypto.decrypt_secret(encrypted_value)
    except Exception as e:
        logger.error(f"Decryption failed for {auc_id}/{provider}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Secure Vault access failed."
        ) from e


async def execute_inference_proxy(
    messages: List[Dict[str, Any]], model: str, auc_id: str, user_context: Dict[str, Any] | None = None
) -> Any:
    """
    Proxies the inference request to the model provider via LiteLLM.
    Enforces temperature=0.0 and injects seed.
    """
    try:
        # 0. Determine Provider
        provider = get_provider_for_model(model)

        # 1. Get API Key
        # We do this outside the breaker because it's DB access, not external API.
        api_key = await get_api_key_for_model(auc_id, model)

        # 2. Prepare Parameters
        # Force deterministic outputs
        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": 0.0,
            "seed": user_context.get("seed", 42) if user_context else 42,
            "api_key": api_key,
        }

        # 3. Call LiteLLM
        # litellm.completion is blocking, but supports async via acompletion
        # We wrap the external call with the Circuit Breaker
        breaker = get_circuit_breaker(provider)
        async with breaker:
            response = await litellm.acompletion(**kwargs)

        return response

    except CircuitBreakerOpenError as e:
        logger.error(f"Circuit Breaker Open for Inference Proxy (Provider: {get_provider_for_model(model)})")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Upstream model service is currently unstable. Please try again later.",
        ) from e

    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"Inference Proxy Error: {e}")
        # Map LiteLLM errors to HTTP status codes if needed
        # For now, 500
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)) from e
