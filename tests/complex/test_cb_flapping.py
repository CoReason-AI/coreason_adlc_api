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

from coreason_adlc_api.middleware.circuit_breaker import AsyncCircuitBreaker


@pytest.mark.asyncio
async def test_flapping_service_retrigger() -> None:
    """
    Scenario: A service is "flapping" (Fail -> Trip -> Recover -> Fail -> Trip...).

    We verify that after a successful recovery (which resets the breaker),
    subsequent failures *do* eventually trip the breaker again.

    Configuration:
    - fail_max=3
    - reset_timeout=0.1
    """
    fail_max = 3
    cb = AsyncCircuitBreaker(fail_max=fail_max, reset_timeout=0.1, time_window=5.0)

    # 1. Trip the breaker (Fail 3 times)
    for _ in range(fail_max):
        try:
            async with cb:
                raise ValueError("fail")
        except ValueError:
            pass

    assert cb.state == "open"

    # 2. Wait for reset timeout -> Half-Open
    await asyncio.sleep(0.15)

    # 3. Successful call (Recover)
    # This should transition Half-Open -> Closed and CLEAR history.
    async with cb:
        pass  # Success

    assert cb.state == "closed"
    assert len(cb.failure_history) == 0

    # 4. Service fails again immediately
    # Since history is cleared, it needs `fail_max` failures to trip again.
    # It should NOT trip on the first failure.
    try:
        async with cb:
            raise ValueError("fail again 1")
    except ValueError:
        pass

    assert cb.state == "closed"
    assert len(cb.failure_history) == 1

    # 5. Continue failing until trip
    for _ in range(fail_max - 1):
        try:
            async with cb:
                raise ValueError("fail again")
        except ValueError:
            pass

    assert cb.state == "open"


@pytest.mark.asyncio
async def test_failed_recovery_immediate() -> None:
    """
    Scenario: Breaker is Open. Wait for reset. Probe fails.
    Condition: `reset_timeout` < `time_window`.

    In this case, the old failure history has NOT expired.
    So a single failure in Half-Open state should append to the history,
    keeping the count >= fail_max, and trip the breaker immediately back to Open.
    """
    fail_max = 2
    # Window is large (10s), Reset is small (0.1s)
    cb = AsyncCircuitBreaker(fail_max=fail_max, reset_timeout=0.1, time_window=10.0)

    # 1. Trip it
    try:
        async with cb:
            raise ValueError("1")
    except ValueError:
        pass
    try:
        async with cb:
            raise ValueError("2")
    except ValueError:
        pass

    assert cb.state == "open"

    # 2. Wait for reset (but not window expiry)
    await asyncio.sleep(0.15)

    # 3. Probe fails
    try:
        async with cb:
            raise ValueError("Probe fail")
    except ValueError:
        pass

    # Since history is preserved (10s window), we now have 3 failures in history.
    # 3 >= 2 -> Open.
    assert cb.state == "open"
    assert len(cb.failure_history) == 3


@pytest.mark.asyncio
async def test_failed_recovery_expired_history() -> None:
    """
    Scenario: Breaker is Open. Wait for reset. Probe fails.
    Condition: `reset_timeout` > `time_window`.

    In this case, the old failures HAVE expired by the time we try to recover.
    The failure history will be pruned to 0 before adding the new failure.
    So the count becomes 1.
    If `fail_max` > 1, the breaker will NOT trip immediately.
    It will effectively restart the "Closed" behavior (allowing traffic)
    until `fail_max` is reached again.

    This test documents this specific behavior.
    """
    fail_max = 3
    # Window is small (0.2s), Reset is larger (0.3s)
    cb = AsyncCircuitBreaker(fail_max=fail_max, reset_timeout=0.3, time_window=0.2)

    # 1. Trip it
    for _ in range(fail_max):
        try:
            async with cb:
                raise ValueError("fail")
        except ValueError:
            pass

    assert cb.state == "open"

    # 2. Wait for reset AND window expiry
    await asyncio.sleep(0.35)

    # 3. Probe fails
    try:
        async with cb:
            raise ValueError("Probe fail")
    except ValueError:
        pass

    # History was pruned (old failures > 0.2s ago).
    # New failure added. Count = 1.
    # 1 < 3 -> State is NOT Open.
    assert cb.state != "open"
    assert len(cb.failure_history) == 1

    # 4. Fail again (Count = 2)
    try:
        async with cb:
            raise ValueError("fail")
    except ValueError:
        pass
    assert cb.state != "open"

    # 5. Fail again (Count = 3 -> Trip)
    try:
        async with cb:
            raise ValueError("fail")
    except ValueError:
        pass
    assert cb.state == "open"
