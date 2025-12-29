from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from coreason_adlc_api.middleware.proxy import _breakers, execute_inference_proxy


@pytest.mark.asyncio
async def test_circuit_breaker_isolation() -> None:
    """
    Verifies that failures in one provider (e.g., 'openai') do not trip the circuit breaker
    for another provider (e.g., 'anthropic').
    """
    # Reset breakers for test isolation
    _breakers.clear()

    # Mock dependencies
    with (
        patch("coreason_adlc_api.middleware.proxy.get_api_key_for_model", new_callable=AsyncMock) as mock_get_key,
        patch("coreason_adlc_api.middleware.proxy.litellm.acompletion", new_callable=AsyncMock) as mock_acompletion,
        patch("coreason_adlc_api.middleware.proxy.litellm.get_llm_provider") as mock_get_provider,
    ):
        # Setup mocks
        mock_get_key.return_value = "dummy-key"

        # We need get_llm_provider to distinguish providers
        def get_provider_side_effect(model: str) -> tuple[str, str, str, str]:
            if "fail-model" in model:
                return ("provider-fail", model, "key", "base")
            return ("provider-ok", model, "key", "base")

        mock_get_provider.side_effect = get_provider_side_effect

        # 1. Simulate failures for "fail-model" (Provider A)
        # We need enough failures to trip the breaker (default 5)
        mock_acompletion.side_effect = Exception("Upstream Error")

        for _ in range(5):
            with pytest.raises(HTTPException):
                await execute_inference_proxy(
                    messages=[{"role": "user", "content": "hi"}], model="fail-model", auc_id="proj-1"
                )

        # Check that provider-fail breaker is open
        assert _breakers["provider-fail"].state == "open"

        # 2. Attempt to call "ok-model" (Provider B)
        # This should SUCCEED now because it uses a different breaker

        mock_acompletion.side_effect = None
        mock_acompletion.return_value = "Success"

        response = await execute_inference_proxy(
            messages=[{"role": "user", "content": "hi"}], model="ok-model", auc_id="proj-1"
        )

        assert response == "Success"

        # Check that provider-ok breaker is closed (or created and closed)
        assert _breakers["provider-ok"].state == "closed"
