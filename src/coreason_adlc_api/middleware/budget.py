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


def check_budget_guardrail(user_id: UUID, estimated_cost: float) -> bool:
    """
    Checks if the user has enough budget for the estimated cost.
    Raises HTTPException(402) if budget is exceeded.

    Logic:
    1. Fetch current daily spend from Redis.
    2. Check if current + estimated > limit.
    3. Update the spend in Redis (optimistic allocation).
    """
    if estimated_cost < 0:
        raise ValueError("Estimated cost cannot be negative.")

    client = get_redis_client()

    # Key format: budget:{YYYY-MM-DD}:{user_uuid}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    key = f"budget:{today}:{user_id}"

    try:
        # Atomic check and update could be better with Lua script,
        # but for now we do simple GET then INCRBYFLOAT.
        # Since this is a "Guardrail", strict consistency is less critical than availability,
        # but we want to avoid overspending.
        # However, multiple requests could race.
        # Ideally: valid = redis.eval(lua_script...)

        # Let's use INCRBYFLOAT which returns the new value.
        # If new value > limit, we decrement it back and reject?
        # Or we check first.

        # Strategy: Check first (GET), then if ok, proceed? No, that has race conditions.
        # Strategy: Increment first. If result > limit, Decrement and Reject.
        # This is "Reservation".

        new_spend = client.incrbyfloat(key, estimated_cost)

        # Set expiry if new key (e.g. 48 hours to allow audit/logging later)
        if new_spend == estimated_cost:
            client.expire(key, 172800)  # 2 days

        if new_spend > settings.DAILY_BUDGET_LIMIT:
            # Revert the charge
            client.incrbyfloat(key, -estimated_cost)

            logger.warning(
                f"Budget exceeded for user {user_id}. "
                f"Attempted: ${estimated_cost}, New Total would be: ${new_spend}, Limit: ${settings.DAILY_BUDGET_LIMIT}"
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
