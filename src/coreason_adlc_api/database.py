# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

from urllib.parse import quote_plus

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from coreason_adlc_api.config import settings

# Construct SQLAlchemy Database URL from settings
encoded_user = quote_plus(settings.POSTGRES_USER)
encoded_password = quote_plus(settings.POSTGRES_PASSWORD)

DATABASE_URL = (
    f"postgresql+asyncpg://{encoded_user}:{encoded_password}@"
    f"{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
)

# Create the Async Engine
engine = create_async_engine(
    DATABASE_URL,
    echo=settings.DEBUG,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

# Create the Session Factory
async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)
