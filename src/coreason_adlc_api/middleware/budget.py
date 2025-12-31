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

import redis.asyncio as redis
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
local cost_micros = tonumber(ARGV[1])
local limit_micros = tonumber(ARGV[2])
local expiry = tonumber(ARGV[3])

local current_micros = tonumber(redis.call('GET', key) or "0")

if current_micros + cost_micros > limit_micros then
    return {0, current_micros, 0}
end

local new_balance_micros = redis.call('INCRBY', key, cost_micros)
local is_new = 0

-- Check if this is the first write (roughly, if balance == cost)
-- Or we can check TTL. But INCRBY doesn't reset TTL.
-- If new_balance is exactly cost, it was 0 before (or expired).
local ttl = redis.call('PTTL', key)

if ttl == -1 then
    -- No expiry set, so it's likely new (or persisted forever).
    redis.call('EXPIRE', key, expiry)
    is_new = 1
end

return {1, new_balance_micros, is_new}
"""


class BudgetService:
    """
    Service for managing user budget guardrails.
    Checks against Redis to ensure daily limits are not exceeded.
    """

    async def check_budget_guardrail(self, user_id: UUID, estimated_cost: float) -> bool:
        """
        Checks if the user has enough budget for the estimated cost.
        Raises HTTPException(402) if budget is exceeded.
        """
        if estimated_cost < 0:
            raise ValueError("Estimated cost cannot be negative.")

        client = get_redis_client()

        # Key format: budget:{YYYY-MM-DD}:{user_uuid}
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        key = f"budget:{today}:{user_id}"

        # Convert to micros (integers)
        cost_micros = int(estimated_cost * 1_000_000)
        limit_micros = int(settings.DAILY_BUDGET_LIMIT * 1_000_000)

        try:
            # Execute Lua Script
            result = await client.eval(  # type: ignore[no-untyped-call]
                BUDGET_LUA_SCRIPT,
                1,  # numkeys
                key,
                cost_micros,
                limit_micros,
                172800,  # 2 days expiry
            )

            is_allowed = int(result[0])

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

    async def check_budget_status(self, user_id: UUID) -> bool:
        """
        Read-only check if the user has exceeded their daily budget.
        Returns True if valid (under limit), False if limit reached.
        """
        client = get_redis_client()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        key = f"budget:{today}:{user_id}"

        try:
            current_spend_micros = await client.get(key)
            if current_spend_micros is None:
                return True

            current_spend_micros_int = int(current_spend_micros)
            limit_micros = int(settings.DAILY_BUDGET_LIMIT * 1_000_000)

            return current_spend_micros_int < limit_micros

        except (redis.RedisError, ValueError, TypeError, Exception) as e:
            logger.error(f"Error checking budget status: {e}")
            return False


# Legacy Wrappers for backward compatibility (if needed by other modules, though we are refactoring to DI)
# We can keep these or remove them. For safety, I'll keep them but have them use the service.
# Actually, to be "Best Practice", we should remove global functions and rely on DI.
# But existing tests might rely on import check_budget_guardrail.
# Let's keep them as proxies for now.

_service = BudgetService()


async def check_budget_guardrail(user_id: UUID, estimated_cost: float) -> bool:
    return await _service.check_budget_guardrail(user_id, estimated_cost)


async def check_budget_status(user_id: UUID) -> bool:
    return await _service.check_budget_status(user_id)
