# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

import asyncio
from typing import Any, Dict, List, Optional

import litellm
from coreason_veritas.anchor import DeterminismInterceptor
from coreason_veritas.exceptions import CircuitOpenError
from coreason_veritas.resilience import AsyncCircuitBreaker
from fastapi import HTTPException, status
from loguru import logger

from coreason_adlc_api.db import get_pool
from coreason_adlc_api.vault.crypto import VaultCrypto

# Circuit Breaker Registry
_breakers: Dict[str, AsyncCircuitBreaker] = {}


class InferenceProxyService:
    """
    Service to proxy inference requests to LLM providers.
    Handles cost estimation, provider selection, API key retrieval, and circuit breaking.
    """

    def get_circuit_breaker(self, provider: str) -> AsyncCircuitBreaker:
        if provider not in _breakers:
            _breakers[provider] = AsyncCircuitBreaker(fail_max=5, reset_timeout=60)
        return _breakers[provider]

    def get_provider_for_model(self, model: str) -> str:
        try:
            # litellm.get_llm_provider returns (provider, model, api_key, api_base)
            provider, _, _, _ = litellm.get_llm_provider(model)  # type: ignore[attr-defined]
            return str(provider)
        except Exception:
            return model.split("/")[0] if "/" in model else "openai"

    async def get_api_key_for_model(self, auc_id: str, model: str) -> str:
        pool = get_pool()
        provider = self.get_provider_for_model(model)

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
        try:
            crypto = VaultCrypto()
            return crypto.decrypt_secret(encrypted_value)
        except Exception as e:
            logger.error(f"Decryption failed for {auc_id}/{provider}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Secure Vault access failed."
            ) from e

    async def execute_inference(
        self, messages: List[Dict[str, Any]], model: str, auc_id: str, user_context: Optional[Dict[str, Any]] = None
    ) -> Any:
        try:
            provider = self.get_provider_for_model(model)
            api_key = await self.get_api_key_for_model(auc_id, model)

            kwargs = {
                "model": model,
                "messages": messages,
                "seed": user_context.get("seed", 42) if user_context else 42,
                "api_key": api_key,
            }
            # Enforce determinism via Veritas
            kwargs = DeterminismInterceptor.enforce_config(kwargs)

            breaker = self.get_circuit_breaker(provider)
            async with breaker:
                response = await litellm.acompletion(**kwargs)

            return response

        except CircuitOpenError as e:
            logger.error(f"Circuit Breaker Open for Inference Proxy (Provider: {self.get_provider_for_model(model)})")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Upstream model service is currently unstable. Please try again later.",
            ) from e
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Inference Proxy Error: {e}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)) from e

    async def estimate_request_cost(self, model: str, messages: List[Dict[str, Any]]) -> float:
        """
        Estimates cost. Runs CPU-bound token counting in a thread to avoid blocking.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._estimate_sync, model, messages)

    def _estimate_sync(self, model: str, messages: List[Dict[str, Any]]) -> float:
        try:
            input_tokens = litellm.token_counter(model=model, messages=messages)

            try:
                cost_info = litellm.model_cost.get(model)
                if not cost_info:
                    raise ValueError("Model cost not found")
                input_cost_per_token = float(cost_info.get("input_cost_per_token", 0.0))
                output_cost_per_token = float(cost_info.get("output_cost_per_token", 0.0))
            except Exception:
                input_cost_per_token = 0.0000005
                output_cost_per_token = 0.0000015

            estimated_output_tokens = 500
            total_cost = (float(input_tokens) * input_cost_per_token) + (
                estimated_output_tokens * output_cost_per_token
            )
            return total_cost
        except Exception:
            return 0.01


# Legacy wrappers
_service = InferenceProxyService()


async def execute_inference_proxy(
    messages: List[Dict[str, Any]], model: str, auc_id: str, user_context: Dict[str, Any] | None = None
) -> Any:
    return await _service.execute_inference(messages, model, auc_id, user_context)
