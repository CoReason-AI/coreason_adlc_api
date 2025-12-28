# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from coreason_adlc_api.telemetry.worker import telemetry_worker


@pytest.mark.asyncio
async def test_telemetry_worker_success() -> None:
    """Verify worker processes a message and inserts into DB."""

    mock_redis = MagicMock()

    # Data to be returned by blpop
    sample_payload = {
        "user_uuid": "00000000-0000-0000-0000-000000000001",
        "auc_id": "proj-1",
        "model_name": "gpt-4",
        "request_payload": "hello",
        "response_payload": "world",
        "cost_usd": 0.01,
        "latency_ms": 100,
        "timestamp": "2024-01-01T00:00:00+00:00",
    }

    # Side effect: first return data, then raise CancelledError to stop loop
    mock_redis.blpop.side_effect = [("telemetry_queue", json.dumps(sample_payload)), asyncio.CancelledError("Stop")]

    mock_pool = MagicMock()
    mock_pool.execute = AsyncMock()

    with (
        patch("coreason_adlc_api.telemetry.worker.get_redis_client", return_value=mock_redis),
        patch("coreason_adlc_api.telemetry.worker.get_pool", return_value=mock_pool),
    ):
        try:
            await telemetry_worker()
        except asyncio.CancelledError:
            pass

        # Verify DB insert
        assert mock_pool.execute.called
        args = mock_pool.execute.call_args[0]
        query = args[0]
        assert "INSERT INTO telemetry.telemetry_logs" in query

        # Args: user_uuid, auc_id, model_name, req, res, cost, latency, timestamp
        assert args[1] == UUID(str(sample_payload["user_uuid"]))
        assert args[2] == sample_payload["auc_id"]
        assert args[3] == sample_payload["model_name"]
        # JSON fields are dumped strings
        assert args[4] == json.dumps(sample_payload["request_payload"])
        assert args[5] == json.dumps(sample_payload["response_payload"])
        assert args[6] == sample_payload["cost_usd"]


@pytest.mark.asyncio
async def test_telemetry_worker_bad_json() -> None:
    """Verify worker handles bad JSON gracefully."""
    mock_redis = MagicMock()
    mock_redis.blpop.side_effect = [("telemetry_queue", "NOT JSON"), asyncio.CancelledError("Stop")]
    mock_pool = MagicMock()
    mock_pool.execute = AsyncMock()

    with (
        patch("coreason_adlc_api.telemetry.worker.get_redis_client", return_value=mock_redis),
        patch("coreason_adlc_api.telemetry.worker.get_pool", return_value=mock_pool),
    ):
        try:
            await telemetry_worker()
        except asyncio.CancelledError:
            pass

        # Should log error but not crash (handled by try/except inside loop)
        # Should NOT call DB
        mock_pool.execute.assert_not_called()


@pytest.mark.asyncio
async def test_telemetry_worker_empty_result() -> None:
    """Verify worker handles empty/None results from Redis (timeout)."""
    mock_redis = MagicMock()
    # 1. None (timeout)
    # 2. (key, None) (unexpected but possible if key exists but empty? BLPOP returns list or None)
    # 3. Stop
    mock_redis.blpop.side_effect = [None, ("telemetry_queue", None), asyncio.CancelledError("Stop")]
    mock_pool = MagicMock()

    with (
        patch("coreason_adlc_api.telemetry.worker.get_redis_client", return_value=mock_redis),
        patch("coreason_adlc_api.telemetry.worker.get_pool", return_value=mock_pool),
    ):
        try:
            await telemetry_worker()
        except asyncio.CancelledError:
            pass

        mock_pool.execute.assert_not_called()


@pytest.mark.asyncio
async def test_telemetry_worker_outer_exception() -> None:
    """Verify worker handles outer loop exceptions (e.g. Redis connection error)."""
    mock_redis = MagicMock()

    # raise Exception, then Stop
    mock_redis.blpop.side_effect = [Exception("Redis connection failed"), asyncio.CancelledError("Stop")]
    mock_pool = MagicMock()

    with (
        patch("coreason_adlc_api.telemetry.worker.get_redis_client", return_value=mock_redis),
        patch("coreason_adlc_api.telemetry.worker.get_pool", return_value=mock_pool),
        patch("asyncio.sleep", new=AsyncMock()) as mock_sleep,
    ):  # Mock sleep to avoid waiting
        try:
            await telemetry_worker()
        except asyncio.CancelledError:
            pass

        # Should have logged error and slept
        mock_sleep.assert_called_once_with(5)
