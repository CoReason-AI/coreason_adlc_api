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
from typing import Any
from unittest import mock

import pytest
from fastapi import HTTPException

from coreason_adlc_api.middleware.budget import check_budget_guardrail
from coreason_adlc_api.middleware.circuit_breaker import AsyncCircuitBreaker
from coreason_adlc_api.middleware.pii import scrub_pii_payload

try:
    from presidio_analyzer import RecognizerResult  # noqa: F401

    HAS_PRESIDIO = True
except ImportError:
    HAS_PRESIDIO = False


# --- Budget Concurrency Test ---


@pytest.mark.asyncio
async def test_budget_concurrency_race() -> None:
    """
    Simulate multiple requests hitting the budget check concurrently.
    Ensure that the cumulative cost is tracked correctly (simulated via mock).
    """
    user_id = uuid.uuid4()
    cost_per_req = 10.0
    limit = 50.0

    # We mock Redis.eval to simulate atomic execution.
    # In a real race, Redis handles this atomically.
    # Here we verify that concurrent calls to check_budget_guardrail behave as expected
    # assuming the underlying eval works.

    current_spend = 0.0

    # Lock for thread-safe updates to current_spend in the mock
    lock = asyncio.Lock()

    def eval_side_effect(script: str, numkeys: int, key: str, cost: float, limit: float, expiry: int) -> list[Any]:
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
    def mock_eval(*args: Any, **kwargs: Any) -> list[Any]:
        # args[0] = script
        # args[1] = numkeys
        # args[2] = key
        # args[3] = cost
        # args[4] = limit
        # args[5] = expiry
        return eval_side_effect(args[0], args[1], args[2], args[3], args[4], args[5])

    with mock.patch("coreason_adlc_api.middleware.budget.get_redis_client") as mock_get_client:
        mock_redis = mock.MagicMock()
        mock_get_client.return_value = mock_redis
        mock_redis.eval.side_effect = mock_eval

        # 6 requests of 10.0 each. Total 60.0. Limit 50.0.
        # 5 should pass, 1 should fail.
        # Order is not guaranteed in async gather, but 1 must fail.

        tasks = []
        for _ in range(6):
            tasks.append(asyncio.to_thread(check_budget_guardrail, user_id, cost_per_req))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        successes = [r for r in results if r is True]
        failures = [r for r in results if isinstance(r, HTTPException) and r.status_code == 402]

        assert len(successes) == 5
        assert len(failures) == 1

        # Verify final spend
        assert current_spend == 50.0


# --- Circuit Breaker Complex Test ---


@pytest.mark.asyncio
async def test_circuit_breaker_half_open_logic() -> None:
    """
    Verify strict half-open behavior:
    1. Open
    2. Timeout passes -> Half-Open
    3. 1 Request allowed.
    4. If it fails -> Open again immediately.
    """
    cb = AsyncCircuitBreaker(fail_max=2, reset_timeout=0.1)

    # Trip it
    try:
        async with cb:
            raise ValueError("fail")
    except ValueError:
        pass
    try:
        async with cb:
            raise ValueError("fail")
    except ValueError:
        pass

    assert cb.state == "open"

    # Wait timeout
    await asyncio.sleep(0.2)

    # Next call should be allowed (half-open)
    # But if we simulate failure:
    try:
        async with cb:
            raise ValueError("fail in half-open")
    except ValueError:
        pass

    assert cb.state == "open"  # Should go back to open

    # Should block immediately
    from coreason_adlc_api.middleware.circuit_breaker import CircuitBreakerOpenError

    with pytest.raises(CircuitBreakerOpenError):
        async with cb:
            pass


# --- PII Complex Test ---


@pytest.mark.skipif(not HAS_PRESIDIO, reason="presidio-analyzer not installed")
def test_pii_complex_overlap() -> None:
    """
    Test overlapping or adjacent entities to ensure index handling is robust.
    """
    # "Call 555-1234 or email bob@example.com."
    # Entities: Phone (5-13), Email (23-38)
    # Overlapping example is hard with Presidio standard models, but we can mock results.

    text = "0123456789"
    # Imagine Entity A (0-5) and Entity B (4-9) - overlap at 4.
    # If logic sorts by start index reverse, it processes last first.
    # B (4-9) replaced. String changes.
    # A (0-5) indices invalid?
    # Actually, Presidio results shouldn't overlap usually.
    # But let's test adjacent: "0123456789" -> A(0-5), B(5-10)

    # Ensure import is safe
    from presidio_analyzer import RecognizerResult

    results = [RecognizerResult("A", 0, 5, 1.0), RecognizerResult("B", 5, 10, 1.0)]

    with mock.patch("coreason_adlc_api.middleware.pii.PIIAnalyzer") as mock_analyzer_cls:
        mock_instance = mock.MagicMock()
        mock_instance.get_analyzer.return_value.analyze.return_value = results
        mock_analyzer_cls.return_value = mock_instance

        # "0123456789"
        # Reverse sort: B first (5,10) -> "01234<REDACTED B>"
        # Then A (0,5) -> "<REDACTED A><REDACTED B>"

        scrubbed = scrub_pii_payload(text)
        assert scrubbed == "<REDACTED A><REDACTED B>"
