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

import pytest

from coreason_adlc_api.middleware.circuit_breaker import AsyncCircuitBreaker, CircuitBreakerOpenError


@pytest.mark.asyncio
async def test_cb_state_transition() -> None:
    cb = AsyncCircuitBreaker(fail_max=2, reset_timeout=0.1, time_window=1.0)

    # 1. Closed state, success
    async with cb:
        pass
    assert cb.state == "closed"
    assert len(cb.failure_history) == 0

    # 2. Failures
    try:
        async with cb:
            raise ValueError("fail 1")
    except ValueError:
        pass
    assert len(cb.failure_history) == 1

    try:
        async with cb:
            raise ValueError("fail 2")
    except ValueError:
        pass
    assert len(cb.failure_history) == 2
    assert cb.state == "open"

    # 3. Open state rejects calls
    with pytest.raises(CircuitBreakerOpenError):
        async with cb:
            pass

    # 4. Wait for reset timeout -> Half-Open
    await asyncio.sleep(0.2)

    # Next call should be allowed (Half-Open)
    # If successful, closes circuit
    async with cb:
        pass

    assert cb.state == "closed"
    assert len(cb.failure_history) == 0


@pytest.mark.asyncio
async def test_cb_half_open_failure() -> None:
    cb = AsyncCircuitBreaker(fail_max=1, reset_timeout=0.1)

    # Trip it
    try:
        async with cb:
            raise ValueError("fail")
    except ValueError:
        pass

    await asyncio.sleep(0.2)

    # Half-open failure -> Open again
    try:
        async with cb:
            raise ValueError("fail again")
    except ValueError:
        pass

    assert cb.state == "open"

    # Check manual call method
    with pytest.raises(CircuitBreakerOpenError):
        await cb.call(lambda: None)


@pytest.mark.asyncio
async def test_cb_sliding_window_expiry() -> None:
    """
    Test that failures older than time_window are pruned and do not trip the breaker.
    """
    # 2 failures allowed in 0.5 seconds
    cb = AsyncCircuitBreaker(fail_max=2, time_window=0.5, reset_timeout=1.0)

    # 1. First failure
    try:
        async with cb:
            raise ValueError("fail 1")
    except ValueError:
        pass
    assert len(cb.failure_history) == 1
    assert cb.state == "closed"

    # 2. Wait for window to expire
    await asyncio.sleep(0.6)

    # 3. Second failure (First one should be pruned)
    try:
        async with cb:
            raise ValueError("fail 2")
    except ValueError:
        pass

    assert len(cb.failure_history) == 1
    assert cb.state == "closed"

    # 4. Rapid failure (now we have 2 in < 0.5s)
    try:
        async with cb:
            raise ValueError("fail 3")
    except ValueError:
        pass

    assert len(cb.failure_history) == 2
    assert cb.state == "open"


@pytest.mark.asyncio
async def test_cb_mixed_success_failure() -> None:
    """
    Test that successes DO clear history while Closed, preventing intermittent errors from tripping.
    """
    cb = AsyncCircuitBreaker(fail_max=2, time_window=1.0)

    # 1. Failure
    try:
        async with cb:
            raise ValueError("fail 1")
    except ValueError:
        pass

    # 2. Success
    async with cb:
        pass

    # History should be cleared
    assert len(cb.failure_history) == 0

    # 3. Failure (Within window)
    try:
        async with cb:
            raise ValueError("fail 2")
    except ValueError:
        pass

    # Should NOT trip because count was reset
    assert cb.state == "closed"
    assert len(cb.failure_history) == 1


@pytest.mark.asyncio
async def test_cb_call_method_transitions() -> None:
    """
    Test state transitions using the .call() method to ensure coverage.
    """
    cb = AsyncCircuitBreaker(fail_max=2, reset_timeout=0.1, time_window=1.0)

    async def success_func() -> str:
        return "ok"

    async def fail_func() -> None:
        raise ValueError("oops")

    # 1. Success call
    assert await cb.call(success_func) == "ok"
    assert cb.state == "closed"

    # 2. Failures via call()
    with pytest.raises(ValueError):
        await cb.call(fail_func)

    with pytest.raises(ValueError):
        await cb.call(fail_func)

    assert cb.state == "open"

    # 3. Call while Open -> Raise CircuitBreakerOpenError
    with pytest.raises(CircuitBreakerOpenError):
        await cb.call(success_func)

    # 4. Wait -> Half-Open
    await asyncio.sleep(0.2)

    # Call should succeed and close circuit
    assert await cb.call(success_func) == "ok"
    assert cb.state == "closed"
    assert len(cb.failure_history) == 0

    # 5. Trip again to test Half-Open failure via call()
    with pytest.raises(ValueError):
        await cb.call(fail_func)
    with pytest.raises(ValueError):
        await cb.call(fail_func)
    assert cb.state == "open"

    await asyncio.sleep(0.2)  # Wait for reset

    # Half-Open -> Failure -> Open
    with pytest.raises(ValueError):
        await cb.call(fail_func)

    assert cb.state == "open"
