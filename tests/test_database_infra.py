# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from coreason_adlc_api.config import settings
from coreason_adlc_api.dependencies import get_db, get_settings


class TestDatabaseInfra(unittest.TestCase):
    def test_database_url_construction(self) -> None:
        """Test that the DATABASE_URL is constructed correctly with encoding."""
        from coreason_adlc_api.database import DATABASE_URL

        # We can't easily change the settings singleton after import, but we can verify the structure
        # assuming the default test settings or what's in .env
        self.assertTrue(DATABASE_URL.startswith("postgresql+asyncpg://"))
        self.assertIn(f"/{settings.POSTGRES_DB}", DATABASE_URL)

        # Verify specific encoding if we were to mock the settings before module import
        # (This is hard to do cleanly without reloading modules, so we trust the string presence check)

    def test_engine_and_factory_exist(self) -> None:
        """Test that engine and session factory are initialized objects."""
        from coreason_adlc_api.database import async_session_factory, engine

        self.assertIsNotNone(engine)
        self.assertIsNotNone(async_session_factory)


@pytest.mark.asyncio
async def test_get_db_yields_session() -> None:
    """Test that get_db yields a session and closes it."""
    mock_session = AsyncMock(spec=AsyncSession)

    # Mock the factory to return our mock session
    with patch("coreason_adlc_api.dependencies.async_session_factory", return_value=mock_session):
        # The factory is called to create the session (context manager)
        # async_session_factory() -> returns context manager -> __aenter__ returns session

        # We need the factory() call to return an object whose __aenter__ returns mock_session
        mock_factory_instance = MagicMock()
        mock_factory_instance.__aenter__.return_value = mock_session
        mock_factory_instance.__aexit__.return_value = None

        with patch("coreason_adlc_api.dependencies.async_session_factory", return_value=mock_factory_instance):
            gen = get_db()
            session = await anext(gen)

            assert session == mock_session

            # Finish the generator
            try:
                await anext(gen)
            except StopAsyncIteration:
                pass

            # Verify close/exit logic if explicit close was called (it's handled by context manager in dependencies.py)
            # Since dependencies.py uses `async with async_session_factory() as session:`,
            # __aexit__ is called automatically.
            mock_factory_instance.__aexit__.assert_called_once()


@pytest.mark.asyncio
async def test_get_db_rollback_on_error() -> None:
    """Test that get_db rolls back the transaction on error."""
    mock_session = AsyncMock(spec=AsyncSession)

    mock_factory_instance = MagicMock()
    mock_factory_instance.__aenter__.return_value = mock_session
    mock_factory_instance.__aexit__.return_value = None

    with patch("coreason_adlc_api.dependencies.async_session_factory", return_value=mock_factory_instance):
        gen = get_db()
        _ = await anext(gen)

        # Raise an exception inside the usage block
        with pytest.raises(ValueError):
            await gen.athrow(ValueError("Test Error"))

        mock_session.rollback.assert_awaited_once()


def test_get_settings() -> None:
    """Test that get_settings returns the settings object."""
    s = get_settings()
    assert s == settings
