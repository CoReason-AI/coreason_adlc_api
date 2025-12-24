# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

import asyncpg
from asyncpg import Pool
from loguru import logger
from coreason_adlc_api.config import settings

# Global connection pool
_pool: Pool | None = None


async def init_db() -> None:
    """
    Initializes the PostgreSQL connection pool.
    """
    global _pool
    if _pool:
        logger.warning("Database pool already initialized.")
        return

    logger.info(f"Connecting to database at {settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}")
    try:
        _pool = await asyncpg.create_pool(
            user=settings.POSTGRES_USER,
            password=settings.POSTGRES_PASSWORD,
            host=settings.POSTGRES_HOST,
            port=settings.POSTGRES_PORT,
            database=settings.POSTGRES_DB,
            min_size=1,
            max_size=10
        )
        logger.info("Database connection pool established.")
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")
        raise


async def close_db() -> None:
    """
    Closes the PostgreSQL connection pool.
    """
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("Database connection pool closed.")


def get_pool() -> Pool:
    """
    Returns the active connection pool.
    Raises RuntimeError if not initialized.
    """
    if not _pool:
        raise RuntimeError("Database pool is not initialized.")
    return _pool
