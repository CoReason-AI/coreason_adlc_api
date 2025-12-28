# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest

import coreason_adlc_api.db as db_module
from coreason_adlc_api.db import _run_ddl


@pytest.mark.asyncio
async def test_run_ddl_execution() -> None:
    """Verify DDL execution reads files and executes SQL."""
    mock_pool = MagicMock()  # acquire is not async, it returns a CM
    mock_conn = AsyncMock()

    # Setup Async Context Manager for acquire()
    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_conn
    mock_pool.acquire.return_value = mock_cm

    original_pool = db_module._pool
    db_module._pool = mock_pool

    try:
        # Mock file existence and content
        with (
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data="CREATE TABLE test;")),
        ):
            await _run_ddl()

            # Verify execution
            mock_conn.execute.assert_awaited_with("CREATE TABLE test;")
    finally:
        db_module._pool = original_pool


@pytest.mark.asyncio
async def test_run_ddl_no_pool() -> None:
    """Verify returns early if no pool."""
    original_pool = db_module._pool
    db_module._pool = None
    try:
        # Should not raise
        await _run_ddl()
    finally:
        db_module._pool = original_pool


@pytest.mark.asyncio
async def test_run_ddl_file_missing() -> None:
    """Verify skips missing files."""
    mock_pool = MagicMock()
    mock_conn = AsyncMock()

    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_conn
    mock_pool.acquire.return_value = mock_cm

    original_pool = db_module._pool
    db_module._pool = mock_pool

    try:
        with patch("os.path.exists", return_value=False):
            await _run_ddl()
            # Should acquire connection but execute nothing
            mock_pool.acquire.assert_called()
            mock_conn.execute.assert_not_called()
    finally:
        db_module._pool = original_pool
