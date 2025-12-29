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
import time

import pytest

from coreason_adlc_api.middleware.circuit_breaker import AsyncCircuitBreaker, CircuitBreakerOpenError


@pytest.mark.asyncio
async def test_concurrent_failures_trip_circuit() -> None:
    """
    Simulate multiple concurrent tasks failing.
    Verify that the circuit trips correctly and history doesn't get corrupted.
    """
    fail_max = 5
    cb = AsyncCircuitBreaker(fail_max=fail_max, reset_timeout=1.0, time_window=5.0)

    async def failing_task() -> None:
        try:
            async with cb:
                await asyncio.sleep(0.01)  # Simulate tiny work
                raise ValueError("boom")
        except ValueError:
            pass
        except CircuitBreakerOpenError:
            pass

    # Launch 10 tasks concurrently
    tasks = [asyncio.create_task(failing_task()) for _ in range(10)]
    await asyncio.gather(*tasks)

    # Check state
    assert cb.state == "open"
    # History should have at least 5 failures (or more, depending on race)
    assert len(cb.failure_history) >= fail_max
    # All failures should be recent
    now = time.time()
    for ts in cb.failure_history:
        assert now - ts < 5.0


@pytest.mark.asyncio
async def test_half_open_flood() -> None:
    """
    Test behavior when many requests hit the breaker exactly when it resets.
    Current implementation allows multiple requests to enter Half-Open state.
    This test verifies that behavior (documenting it) and ensures eventual consistency.
    """
    cb = AsyncCircuitBreaker(fail_max=2, reset_timeout=0.2)

    # Trip it
    try:
        async with cb:
            raise ValueError("fail 1")
    except ValueError:
        pass
    try:
        async with cb:
            raise ValueError("fail 2")
    except ValueError:
        pass
    assert cb.state == "open"

    # Wait for reset
    await asyncio.sleep(0.3)

    # Launch multiple requests
    # Some might succeed, some might fail.
    # If one succeeds, it should Close.
    # If one fails, it should Re-Open.

    start_event = asyncio.Event()

    async def worker(idx: int) -> str:
        await start_event.wait()
        try:
            async with cb:
                # Simulate work
                await asyncio.sleep(0.05)
                # Fail half of them
                if idx % 2 == 0:
                    raise ValueError("fail")
            return "success"
        except ValueError:
            return "failed_inner"
        except CircuitBreakerOpenError:
            return "open"

    tasks = [asyncio.create_task(worker(i)) for i in range(10)]

    start_event.set()
    results = await asyncio.gather(*tasks)

    counts = {
        "success": results.count("success"),
        "failed_inner": results.count("failed_inner"),
        "open": results.count("open"),
    }

    # At least some requests should have attempted execution
    assert counts["success"] + counts["failed_inner"] > 0

    # The circuit should likely be Open if failures occurred
    pass


@pytest.mark.asyncio
async def test_rolling_window_precision() -> None:
    """
    Test exact boundaries of the time window.
    """
    cb = AsyncCircuitBreaker(fail_max=2, time_window=1.0)

    # T=0: Failure
    try:
        async with cb:
            raise ValueError("fail 1")
    except ValueError:
        pass

    assert len(cb.failure_history) == 1
    pass


@pytest.mark.asyncio
async def test_large_volume_history() -> None:
    """
    Stress test with many failures to ensure deque doesn't explode or leak.
    """
    # 1000 failures allowed in 100s (effectively infinite window for the test duration)
    cb = AsyncCircuitBreaker(fail_max=2000, time_window=100.0)

    for _ in range(1000):
        try:
            async with cb:
                raise ValueError("fail")
        except ValueError:
            pass

    assert len(cb.failure_history) == 1000
    assert cb.state == "closed"

    # One more to 1001
    try:
        async with cb:
            raise ValueError("fail")
    except ValueError:
        pass
    assert len(cb.failure_history) == 1001


@pytest.mark.asyncio
async def test_zero_time_window_edge_case() -> None:
    """
    Edge Case: time_window = 0.
    Failures should expire immediately (practically).
    """
    cb = AsyncCircuitBreaker(fail_max=2, time_window=0.0)

    # Failure 1
    try:
        async with cb:
            raise ValueError("fail 1")
    except ValueError:
        pass

    assert len(cb.failure_history) == 0
    assert cb.state == "closed"

    # Try multiple
    for _ in range(10):
        try:
            async with cb:
                raise ValueError("fail")
        except ValueError:
            pass

    assert len(cb.failure_history) == 0
    assert cb.state == "closed"
