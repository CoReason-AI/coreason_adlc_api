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
from unittest import mock

import pytest
from fastapi import HTTPException
from redis import RedisError

from coreason_adlc_api.config import settings
from coreason_adlc_api.middleware.budget import check_budget_guardrail


@pytest.fixture
def mock_redis():
    with mock.patch("coreason_adlc_api.middleware.budget.redis.Redis") as mock_redis_cls:
        client = mock.MagicMock()
        mock_redis_cls.return_value = client
        yield client


def test_check_budget_pass(mock_redis):
    """Test that check passes when under budget."""
    user_id = uuid.uuid4()
    cost = 0.5

    # Setup mock to return a value within limit
    # settings.DAILY_BUDGET_LIMIT is 50.0
    mock_redis.incrbyfloat.return_value = 10.0

    result = check_budget_guardrail(user_id, cost)

    assert result is True
    mock_redis.incrbyfloat.assert_called_once()
    # Verify key format roughly
    args, _ = mock_redis.incrbyfloat.call_args
    assert f"budget:" in args[0]
    assert str(user_id) in args[0]
    assert args[1] == cost


def test_check_budget_exceeded(mock_redis):
    """Test that check raises 402 when budget exceeded."""
    user_id = uuid.uuid4()
    cost = 10.0

    # Simulate that this charge pushes total to 60.0 (Limit is 50.0)
    mock_redis.incrbyfloat.return_value = 60.0

    with pytest.raises(HTTPException) as exc:
        check_budget_guardrail(user_id, cost)

    assert exc.value.status_code == 402
    assert "Daily budget limit exceeded" in exc.value.detail

    # Verify rollback
    assert mock_redis.incrbyfloat.call_count == 2
    # Second call should be negative cost
    call_args_list = mock_redis.incrbyfloat.call_args_list
    assert call_args_list[1][0][1] == -cost


def test_check_budget_redis_error(mock_redis):
    """Test fail-closed behavior on Redis error."""
    user_id = uuid.uuid4()
    mock_redis.incrbyfloat.side_effect = RedisError("Connection failed")

    with pytest.raises(HTTPException) as exc:
        check_budget_guardrail(user_id, 1.0)

    assert exc.value.status_code == 503
    assert "Budget service unavailable" in exc.value.detail


def test_check_budget_first_time(mock_redis):
    """Test that expiry is set on first charge."""
    user_id = uuid.uuid4()
    cost = 5.0
    mock_redis.incrbyfloat.return_value = 5.0

    check_budget_guardrail(user_id, cost)

    mock_redis.expire.assert_called_once()


def test_check_budget_negative_cost(mock_redis):
    """Test that negative cost raises ValueError."""
    user_id = uuid.uuid4()
    with pytest.raises(ValueError):
        check_budget_guardrail(user_id, -5.0)
