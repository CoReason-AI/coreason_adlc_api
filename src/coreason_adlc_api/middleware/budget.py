# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

from datetime import datetime, timezone
from uuid import UUID

import redis
from fastapi import HTTPException, status
from loguru import logger

from coreason_adlc_api.config import settings
from coreason_adlc_api.utils import get_redis_client

# Atomic check-and-update script
# Keys: [budget_key]
# Args: [cost, limit, expiry_seconds]
# Returns: [is_allowed (1/0), new_balance, is_new_key (1/0)]
BUDGET_LUA_SCRIPT = """
local key = KEYS[1]
local cost = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local expiry = tonumber(ARGV[3])

local current = tonumber(redis.call('GET', key) or "0")

if current + cost > limit then
    return {0, current, 0}
end

local new_balance = redis.call('INCRBYFLOAT', key, cost)
local is_new = 0

-- Check if this is the first write (roughly, if balance == cost)
-- Or we can check TTL. But INCRBYFLOAT doesn't reset TTL.
-- If new_balance is exactly cost, it was 0 before (or expired).
-- But float equality can be tricky. Let's rely on PTTL.
local ttl = redis.call('PTTL', key)

if ttl == -1 then
    -- No expiry set, so it's likely new (or persisted forever).
    redis.call('EXPIRE', key, expiry)
    is_new = 1
end

return {1, new_balance, is_new}
"""


def check_budget_guardrail(user_id: UUID, estimated_cost: float) -> bool:
    """
    Checks if the user has enough budget for the estimated cost.
    Raises HTTPException(402) if budget is exceeded.

    Logic (Atomic Lua):
    1. Check if current + estimated <= limit.
    2. If yes, increment and return Success.
    3. If no, return Failure (no change).
    """
    if estimated_cost < 0:
        raise ValueError("Estimated cost cannot be negative.")

    client = get_redis_client()

    # Key format: budget:{YYYY-MM-DD}:{user_uuid}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    key = f"budget:{today}:{user_id}"

    try:
        # Execute Lua Script
        # Result: [is_allowed (int), new_balance (float/str), is_new (int)]
        result = client.eval(  # type: ignore[no-untyped-call]
            BUDGET_LUA_SCRIPT,
            1,  # numkeys
            key,
            estimated_cost,
            settings.DAILY_BUDGET_LIMIT,
            172800,  # 2 days expiry
        )

        # Redis might return ints as ints, floats as strings or floats depending on client version/decoding.
        is_allowed = int(result[0])
        _new_balance = float(result[1])

        if not is_allowed:
            logger.warning(
                f"Budget exceeded for user {user_id}. "
                f"Attempted: ${estimated_cost}, Limit: ${settings.DAILY_BUDGET_LIMIT}"
            )
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="Daily budget limit exceeded.",
            )

        return True

    except redis.RedisError as e:
        logger.error(f"Redis error in budget check: {e}")
        # Fail safe? Or Fail closed?
        # BG-01 says "Prevent Cloud Bill Shock". Fail closed is safer financially.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Budget service unavailable.",
        ) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in budget check: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error checking budget.",
        ) from e


def check_budget_status(user_id: UUID) -> bool:
    """
    Read-only check if the user has exceeded their daily budget.
    Returns True if valid (under limit), False if limit reached.
    """
    client = get_redis_client()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    key = f"budget:{today}:{user_id}"

    try:
        current_spend = client.get(key)
        if current_spend is None:
            return True

        return float(current_spend) < settings.DAILY_BUDGET_LIMIT

    except (redis.RedisError, ValueError, TypeError, Exception) as e:
        logger.error(f"Error checking budget status: {e}")
        # Fail closed for safety
        return False
