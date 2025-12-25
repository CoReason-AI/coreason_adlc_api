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
async def test_cb_success_resets_counter() -> None:
    cb = AsyncCircuitBreaker(fail_max=2, reset_timeout=0.1)

    # 1. First failure
    try:
        async with cb:
            raise ValueError("fail 1")
    except ValueError:
        pass
    assert cb.fail_counter == 1

    # 2. Success
    async with cb:
        pass

    # Counter should be reset to 0
    assert cb.fail_counter == 0

    # 3. Next failure should count as 1, not 2 (tripping)
    try:
        async with cb:
            raise ValueError("fail 1 again")
    except ValueError:
        pass
    assert cb.fail_counter == 1
    assert cb.state == "closed"
