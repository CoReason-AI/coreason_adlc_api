# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

import httpx
import redis.asyncio as redis

from coreason_adlc_api.config import settings

# Global Redis pool
_redis_pool: redis.ConnectionPool | None = None  # type: ignore


def get_redis_client() -> redis.Redis:  # type: ignore
    """
    Creates and returns an ASYNC Redis client using a shared connection pool.
    """
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = redis.ConnectionPool.from_url(
            f"redis://:{settings.REDIS_PASSWORD}@{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}",
            decode_responses=True,
        )
    return redis.Redis(connection_pool=_redis_pool)


def get_http_client() -> httpx.AsyncClient:
    """
    Returns an async HTTP client for external requests.
    Useful for mocking in tests.
    """
    return httpx.AsyncClient()
