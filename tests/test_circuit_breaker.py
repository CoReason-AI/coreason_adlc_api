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
async def test_cb_state_transition() -> None:
    cb = AsyncCircuitBreaker(fail_max=2, reset_timeout=0.1)

    # 1. Closed state, success
    async with cb:
        pass
    assert cb.state == "closed"
    assert cb.fail_counter == 0

    # 2. Failures
    try:
        async with cb:
            raise ValueError("fail 1")
    except ValueError:
        pass
    assert cb.fail_counter == 1

    try:
        async with cb:
            raise ValueError("fail 2")
    except ValueError:
        pass
    assert cb.fail_counter == 2
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
    assert cb.fail_counter == 0


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
