# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

import pytest
from unittest.mock import patch, AsyncMock
from coreason_adlc_api.db import init_db, close_db, get_pool
from coreason_adlc_api.config import settings

@pytest.mark.asyncio
async def test_db_lifecycle():
    """Verify init_db creates a pool and close_db closes it."""

    # Mock asyncpg.create_pool
    mock_pool = AsyncMock()

    with patch("asyncpg.create_pool", new=AsyncMock(return_value=mock_pool)) as mock_create:
        # Reset global state just in case
        import coreason_adlc_api.db as db_module
        db_module._pool = None

        # Test Init
        await init_db()

        mock_create.assert_called_once_with(
            user=settings.POSTGRES_USER,
            password=settings.POSTGRES_PASSWORD,
            host=settings.POSTGRES_HOST,
            port=settings.POSTGRES_PORT,
            database=settings.POSTGRES_DB,
            min_size=1,
            max_size=10
        )
        assert get_pool() == mock_pool

        # Test Double Init (should warn and return)
        await init_db()
        assert mock_create.call_count == 1

        # Test Close
        await close_db()
        mock_pool.close.assert_called_once()

        # Verify pool is cleared
        with pytest.raises(RuntimeError, match="Database pool is not initialized"):
            get_pool()

@pytest.mark.asyncio
async def test_db_init_failure():
    """Verify init_db raises exception on failure."""

    with patch("asyncpg.create_pool", side_effect=Exception("Connection failed")):
        import coreason_adlc_api.db as db_module
        db_module._pool = None

        with pytest.raises(Exception, match="Connection failed"):
            await init_db()

@pytest.mark.asyncio
async def test_close_db_idempotent():
    """Verify close_db handles being called when pool is None."""
    import coreason_adlc_api.db as db_module
    db_module._pool = None

    # Should not raise
    await close_db()
