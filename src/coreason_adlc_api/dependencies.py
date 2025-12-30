# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from coreason_adlc_api.config import Settings, settings
from coreason_adlc_api.database import async_session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency that provides an asynchronous SQLAlchemy session.
    """
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


def get_settings() -> Settings:
    """
    Dependency that provides the application settings.
    """
    return settings
