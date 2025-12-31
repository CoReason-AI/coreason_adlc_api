# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

import os
import contextlib
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

# Use sqlmodel's AsyncSession to get .exec() support, but we need
# create_async_engine from sqlalchemy.ext.asyncio (which is compatible).

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"postgresql+asyncpg://{os.getenv('POSTGRES_USER', 'postgres')}:{os.getenv('POSTGRES_PASSWORD', 'postgres')}@"
    f"{os.getenv('POSTGRES_HOST', 'localhost')}:{os.getenv('POSTGRES_PORT', '5432')}/"
    f"{os.getenv('POSTGRES_DB', 'coreason_adlc')}"
)

# Create the engine
# future=True is default in 1.4+, but explicit doesn't hurt.
engine = create_async_engine(DATABASE_URL, echo=False, future=True)

# Create a session factory
# Note: we use AsyncSession from sqlmodel.ext.asyncio.session
async_session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)


async def init_db() -> None:
    """
    Initializes the database connection.
    In a real SQLModel setup, we might also create tables here using
    conn.run_sync(SQLModel.metadata.create_all), but we are likely using Alembic or existing schemas.
    """
    # For now, just ensure we can connect?
    # Or just a placeholder if using migrations.
    pass


async def close_db() -> None:
    """Closes the database connection pool."""
    await engine.dispose()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for getting a database session."""
    async with async_session_factory() as session:
        yield session


@contextlib.asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Context manager for manual session usage outside of FastAPI dependencies
    (e.g., in background workers or scripts).
    """
    async with async_session_factory() as session:
        yield session
