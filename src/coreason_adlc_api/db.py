# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

import json
import os

import asyncpg
from asyncpg import Pool
from loguru import logger

from coreason_adlc_api.config import settings

# Global connection pool
_pool: Pool | None = None


async def init_conn(conn: asyncpg.Connection) -> None:
    """
    Initialize a connection (register codecs).
    """
    await conn.set_type_codec(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )


async def init_db() -> None:
    """
    Initializes the PostgreSQL connection pool and runs schema setup.
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
            max_size=10,
            init=init_conn,
        )
        logger.info("Database connection pool established.")

        # Run Schema Setup
        await _run_ddl()

    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")
        raise


async def _run_ddl() -> None:
    """
    Executes DDL scripts to initialize the database schema.
    """
    if not _pool:
        return

    logger.info("Checking database schema...")

    # Path to DDL files - naïve approach for atomic unit 1
    # In a real app, use Alembic. Here we load specific SQL files.
    base_path = os.path.dirname(__file__)

    # List of DDL files to execute in order
    ddl_files = [
        os.path.join(base_path, "auth", "ddl.sql"),
        os.path.join(base_path, "vault", "ddl.sql"),
        os.path.join(base_path, "workbench", "ddl.sql"),
        os.path.join(base_path, "telemetry", "ddl.sql"),
    ]

    async with _pool.acquire() as conn:
        for ddl_file in ddl_files:
            if os.path.exists(ddl_file):
                logger.debug(f"Executing DDL: {ddl_file}")
                with open(ddl_file, "r") as f:
                    sql = f.read()
                    await conn.execute(sql)
            else:
                logger.warning(f"DDL file not found: {ddl_file}")

    logger.info("Schema check complete.")


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
