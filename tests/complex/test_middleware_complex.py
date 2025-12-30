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
import uuid
from typing import Any, AsyncGenerator
from unittest import mock

import pytest
from fastapi import HTTPException

from coreason_adlc_api.middleware.budget import check_budget_guardrail
from coreason_adlc_api.middleware.pii import scrub_pii_recursive

try:
    import presidio_analyzer  # noqa: F401

    HAS_PRESIDIO = True
except ImportError:
    HAS_PRESIDIO = False


@pytest.mark.skipif(not HAS_PRESIDIO, reason="presidio-analyzer not installed")
@pytest.mark.asyncio
async def test_pii_scrubbing_complex_structure() -> None:
    """
    Test deep scrubbing of a complex nested structure (JSON-like).
    Verifies recursion limit safety and correctness.
    """
    # 1. Setup Data
    deep_json = {
        "user": {"name": "John Doe", "email": "john@example.com"},
        "history": [
            {"query": "Call 555-1234", "response": "OK"},
            {"query": "Safe", "response": "Safe"},
        ],
        "meta": {"trace_id": "123", "debug": {"raw": "User John Doe said hi"}},
    }

    # 2. Mock PII Analyzer (Integration level logic check)
    # We rely on the real PII analyzer logic if installed, or mock the scan result
    # For a complex test, we want to see the recursive traversal logic working.
    # We'll patch the low-level analyze to be deterministic.

    async def mock_scrub_payload(text: str) -> str:
        if "John Doe" in text:
            text = text.replace("John Doe", "<REDACTED PERSON>")
        if "john@example.com" in text:
            text = text.replace("john@example.com", "<REDACTED EMAIL>")
        if "555-1234" in text:
            text = text.replace("555-1234", "<REDACTED PHONE>")
        return text

    with mock.patch("coreason_adlc_api.middleware.pii.scrub_pii_payload", side_effect=mock_scrub_payload):
        scrubbed = await scrub_pii_recursive(deep_json)

    # 3. Verify
    assert scrubbed["user"]["name"] == "<REDACTED PERSON>"
    assert scrubbed["user"]["email"] == "<REDACTED EMAIL>"
    assert scrubbed["history"][0]["query"] == "Call <REDACTED PHONE>"
    assert scrubbed["meta"]["debug"]["raw"] == "User <REDACTED PERSON> said hi"
    # Safe fields untouched
    assert scrubbed["history"][1]["query"] == "Safe"


@pytest.mark.asyncio
async def test_budget_concurrency_race() -> None:
    """
    Simulate multiple requests hitting the budget check concurrently.
    Ensure that the cumulative cost is tracked correctly (simulated via mock).
    """
    user_id = uuid.uuid4()
    cost_per_req = 10.0
    # limit = 50.0

    # We mock Redis.eval to simulate atomic execution.
    # In a real race, Redis handles this atomically.
    # Here we verify that concurrent calls to check_budget_guardrail behave as expected
    # assuming the underlying eval works.

    current_spend = 0.0

    # Lock for thread-safe updates to current_spend in the mock
    # lock = asyncio.Lock()

    def eval_side_effect(script: str, numkeys: int, key: str, cost: int, limit: int, expiry: int) -> list[Any]:
        nonlocal current_spend
        # Simulate atomic script execution
        # Note: In real Redis, this is atomic. Here we use a simple variable.
        # Check
        if current_spend + cost > limit:
            return [0, current_spend, 0]

        # Increment
        current_spend += cost
        is_new = 1 if current_spend == cost else 0
        return [1, current_spend, is_new]

    # Wrapper to handle the mock call arguments which might be positional
    # client.eval(script, numkeys, key, arg1, arg2...)
    async def mock_eval(*args: Any, **kwargs: Any) -> list[Any]:
        # args[0] = script
        # args[1] = numkeys
        # args[2] = key
        # args[3] = cost
        # args[4] = limit
        # args[5] = expiry
        return eval_side_effect(args[0], args[1], args[2], args[3], args[4], args[5])

    with mock.patch("coreason_adlc_api.middleware.budget.get_redis_client") as mock_get_client:
        mock_redis = mock.AsyncMock()
        mock_get_client.return_value = mock_redis
        mock_redis.eval.side_effect = mock_eval

        # 6 requests of 10.0 each. Total 60.0. Limit 50.0.
        # 5 should pass, 1 should fail.
        # Order is not guaranteed in async gather, but 1 must fail.

        tasks = []
        for _ in range(6):
            # Pass coroutines directly to gather
            tasks.append(check_budget_guardrail(user_id, cost_per_req))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        successes = [r for r in results if r is True]
        failures = [r for r in results if isinstance(r, HTTPException) and r.status_code == 402]

        assert len(successes) == 5
        assert len(failures) == 1
