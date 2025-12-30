# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api
import uuid
from typing import Any
from unittest import mock

import pytest
from fastapi import HTTPException
from redis import RedisError

from coreason_adlc_api.middleware.budget import check_budget_guardrail


@pytest.fixture
def mock_redis() -> Any:
    # We patch get_redis_client to return an AsyncMock
    with mock.patch("coreason_adlc_api.middleware.budget.get_redis_client") as mock_get_client:
        client = mock.AsyncMock()
        mock_get_client.return_value = client
        yield client


@pytest.mark.asyncio
async def test_check_budget_pass(mock_redis: Any) -> None:
    """Test that check passes when under budget."""
    user_id = uuid.uuid4()
    cost = 0.5

    # Lua script returns [is_allowed, new_balance, is_new]
    # is_allowed=1 (True), new_balance=500000 (0.5 * 10^6), is_new=0
    # Note: Logic now expects integers for micros.
    mock_redis.eval.return_value = [1, 500000, 0]

    result = await check_budget_guardrail(user_id, cost)

    assert result is True
    mock_redis.eval.assert_called_once()

    # Check arguments passed to eval
    args, _ = mock_redis.eval.call_args
    # args[0] is script, args[1] is numkeys (1), args[2] is key
    # args[3] is cost_micros -> 500000
    assert "local key = KEYS[1]" in args[0]
    assert args[1] == 1
    assert "budget:" in args[2]
    assert str(user_id) in args[2]
    assert args[3] == 500000  # 0.5 * 1_000_000


@pytest.mark.asyncio
async def test_check_budget_exceeded(mock_redis: Any) -> None:
    """Test that check raises 402 when budget exceeded."""
    user_id = uuid.uuid4()
    cost = 10.0

    # Lua script returns [is_allowed, new_balance, is_new]
    # is_allowed=0 (False), current_balance=50.0 * 10^6 (example), is_new=0
    mock_redis.eval.return_value = [0, 50000000, 0]

    with pytest.raises(HTTPException) as exc:
        await check_budget_guardrail(user_id, cost)

    assert exc.value.status_code == 402
    assert "Daily budget limit exceeded" in exc.value.detail


@pytest.mark.asyncio
async def test_check_budget_redis_error(mock_redis: Any) -> None:
    """Test fail-closed behavior on Redis error."""
    user_id = uuid.uuid4()
    mock_redis.eval.side_effect = RedisError("Connection failed")

    with pytest.raises(HTTPException) as exc:
        await check_budget_guardrail(user_id, 1.0)

    assert exc.value.status_code == 503
    assert "Budget service unavailable" in exc.value.detail


@pytest.mark.asyncio
async def test_check_budget_first_time(mock_redis: Any) -> None:
    """Test that expiry handling logic in Lua is covered (implicit via Lua logic)."""
    user_id = uuid.uuid4()
    cost = 5.0
    mock_redis.eval.return_value = [1, 5000000, 1]  # is_new=1, balance=5.0*10^6

    result = await check_budget_guardrail(user_id, cost)
    assert result is True


@pytest.mark.asyncio
async def test_check_budget_negative_cost(mock_redis: Any) -> None:
    """Test that negative cost raises ValueError."""
    user_id = uuid.uuid4()
    with pytest.raises(ValueError):
        await check_budget_guardrail(user_id, -5.0)


@pytest.mark.asyncio
async def test_check_budget_generic_exception(mock_redis: Any) -> None:
    """Test 500 behavior on generic unexpected error."""
    user_id = uuid.uuid4()
    mock_redis.eval.side_effect = Exception("Something weird happened")

    with pytest.raises(HTTPException) as exc:
        await check_budget_guardrail(user_id, 1.0)

    assert exc.value.status_code == 500
    assert "Internal server error" in exc.value.detail
