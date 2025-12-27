# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

import pytest
from coreason_adlc_api.middleware.circuit_breaker import AsyncCircuitBreaker


@pytest.mark.asyncio
async def test_cb_success_does_not_reset_history_in_sliding_window() -> None:
    """
    Verifies that a success does NOT reset the failure history in the sliding window implementation.
    The previous behavior (consecutive failures) reset on success, but sliding window retains failures within window.
    """
    # Use a long window so failures stick
    cb = AsyncCircuitBreaker(fail_max=2, reset_timeout=0.1, time_window=10.0)

    # 1. First failure
    try:
        async with cb:
            raise ValueError("fail 1")
    except ValueError:
        pass
    assert len(cb.failure_history) == 1

    # 2. Success
    async with cb:
        pass

    # Counter should NOT be reset to 0, because the failure is still in the 10s window
    assert len(cb.failure_history) == 1

    # 3. Next failure should count as 2, tripping the breaker
    try:
        async with cb:
            raise ValueError("fail 2")
    except ValueError:
        pass

    assert len(cb.failure_history) == 2
    assert cb.state == "open"
