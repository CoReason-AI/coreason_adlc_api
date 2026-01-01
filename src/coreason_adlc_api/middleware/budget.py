# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

from uuid import UUID

import redis.asyncio as redis
from coreason_veritas.exceptions import QuotaExceededError
from coreason_veritas.quota import QuotaGuard
from fastapi import HTTPException, status
from loguru import logger

from coreason_adlc_api.config import settings
from coreason_adlc_api.utils import get_redis_client


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

        try:
            # Instantiate guard with daily limit
            guard = QuotaGuard(get_redis_client(), settings.DAILY_BUDGET_LIMIT)
            await guard.check_and_increment(str(user_id), estimated_cost)
            return True

        except QuotaExceededError as e:
            logger.warning(
                f"Budget exceeded for user {user_id}. "
                f"Attempted: ${estimated_cost}, Limit: ${settings.DAILY_BUDGET_LIMIT}"
            )
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="Daily budget limit exceeded.",
            ) from e

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
        try:
            guard = QuotaGuard(get_redis_client(), settings.DAILY_BUDGET_LIMIT)
            return await guard.check_status(str(user_id))

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
