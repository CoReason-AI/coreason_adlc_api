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
from coreason_veritas.quota import QuotaExceededError
from fastapi import HTTPException
from redis import RedisError

from coreason_adlc_api.middleware.budget import check_budget_guardrail


@pytest.fixture
def mock_quota_guard() -> Any:
    # Patch the QuotaGuard class in the module
    with mock.patch("coreason_adlc_api.middleware.budget.QuotaGuard") as mock_guard_cls:
        instance = mock.AsyncMock()
        mock_guard_cls.return_value = instance
        yield instance


@pytest.mark.asyncio
async def test_check_budget_pass(mock_quota_guard: Any) -> None:
    """Test that check passes when under budget."""
    user_id = uuid.uuid4()
    cost = 0.5

    # Should just return without error
    mock_quota_guard.check_and_increment.return_value = None

    result = await check_budget_guardrail(user_id, cost)

    assert result is True
    mock_quota_guard.check_and_increment.assert_called_once_with(str(user_id), cost)


@pytest.mark.asyncio
async def test_check_budget_exceeded(mock_quota_guard: Any) -> None:
    """Test that check raises 402 when budget exceeded."""
    user_id = uuid.uuid4()
    cost = 10.0

    mock_quota_guard.check_and_increment.side_effect = QuotaExceededError("Quota exceeded")

    with pytest.raises(HTTPException) as exc:
        await check_budget_guardrail(user_id, cost)

    assert exc.value.status_code == 402
    assert "Daily budget limit exceeded" in exc.value.detail


@pytest.mark.asyncio
async def test_check_budget_redis_error(mock_quota_guard: Any) -> None:
    """Test fail-closed behavior on Redis error."""
    user_id = uuid.uuid4()
    mock_quota_guard.check_and_increment.side_effect = RedisError("Connection failed")

    with pytest.raises(HTTPException) as exc:
        await check_budget_guardrail(user_id, 1.0)

    assert exc.value.status_code == 503
    assert "Budget service unavailable" in exc.value.detail


@pytest.mark.asyncio
async def test_check_budget_negative_cost() -> None:
    """Test that negative cost raises ValueError."""
    user_id = uuid.uuid4()
    with pytest.raises(ValueError):
        await check_budget_guardrail(user_id, -5.0)


@pytest.mark.asyncio
async def test_check_budget_generic_exception(mock_quota_guard: Any) -> None:
    """Test 500 behavior on generic unexpected error."""
    user_id = uuid.uuid4()
    mock_quota_guard.check_and_increment.side_effect = Exception("Something weird happened")

    with pytest.raises(HTTPException) as exc:
        await check_budget_guardrail(user_id, 1.0)

    assert exc.value.status_code == 500
    assert "Internal server error" in exc.value.detail
