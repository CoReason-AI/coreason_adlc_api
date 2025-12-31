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

    # Updated to AsyncMock because get_redis_client now returns an async client
    mock_redis = AsyncMock()

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

    mock_session_factory = MagicMock()
    mock_session = AsyncMock()
    mock_session_factory.return_value.__aenter__.return_value = mock_session
    mock_session_factory.return_value.__aexit__.return_value = None

    with (
        patch("coreason_adlc_api.telemetry.worker.get_redis_client", return_value=mock_redis),
        patch("coreason_adlc_api.telemetry.worker.async_session_factory", mock_session_factory),
    ):
        try:
            await telemetry_worker()
        except asyncio.CancelledError:
            pass

        # Verify DB insert
        assert mock_session.execute.called
        args, kwargs = mock_session.execute.call_args
        stmt = args[0]
        params = args[1]

        assert "INSERT INTO telemetry.telemetry_logs" in str(stmt)

        # Args: user_uuid, auc_id, model_name, req, res, cost, latency, timestamp
        assert params["user_uuid"] == UUID(str(sample_payload["user_uuid"]))
        assert params["auc_id"] == sample_payload["auc_id"]
        assert params["model_name"] == sample_payload["model_name"]
        assert params["req_payload"] == json.dumps(sample_payload["request_payload"])
        assert params["res_payload"] == json.dumps(sample_payload["response_payload"])
        assert params["cost"] == sample_payload["cost_usd"]


@pytest.mark.asyncio
async def test_telemetry_worker_bad_json() -> None:
    """Verify worker handles bad JSON gracefully."""
    mock_redis = AsyncMock()
    mock_redis.blpop.side_effect = [("telemetry_queue", "NOT JSON"), asyncio.CancelledError("Stop")]

    mock_session_factory = MagicMock()
    mock_session = AsyncMock()
    mock_session_factory.return_value.__aenter__.return_value = mock_session

    with (
        patch("coreason_adlc_api.telemetry.worker.get_redis_client", return_value=mock_redis),
        patch("coreason_adlc_api.telemetry.worker.async_session_factory", mock_session_factory),
    ):
        try:
            await telemetry_worker()
        except asyncio.CancelledError:
            pass

        # Should log error but not crash (handled by try/except inside loop)
        # Should NOT call DB
        mock_session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_telemetry_worker_empty_result() -> None:
    """Verify worker handles empty/None results from Redis (timeout)."""
    mock_redis = AsyncMock()
    # 1. None (timeout)
    # 2. (key, None) (unexpected but possible if key exists but empty? BLPOP returns list or None)
    # 3. Stop
    mock_redis.blpop.side_effect = [None, ("telemetry_queue", None), asyncio.CancelledError("Stop")]

    mock_session_factory = MagicMock()
    mock_session = AsyncMock()
    mock_session_factory.return_value.__aenter__.return_value = mock_session

    with (
        patch("coreason_adlc_api.telemetry.worker.get_redis_client", return_value=mock_redis),
        patch("coreason_adlc_api.telemetry.worker.async_session_factory", mock_session_factory),
    ):
        try:
            await telemetry_worker()
        except asyncio.CancelledError:
            pass

        mock_session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_telemetry_worker_outer_exception() -> None:
    """Verify worker handles outer loop exceptions (e.g. Redis connection error)."""
    mock_redis = AsyncMock()

    # raise Exception, then Stop
    mock_redis.blpop.side_effect = [Exception("Redis connection failed"), asyncio.CancelledError("Stop")]

    mock_session_factory = MagicMock()

    with (
        patch("coreason_adlc_api.telemetry.worker.get_redis_client", return_value=mock_redis),
        patch("coreason_adlc_api.telemetry.worker.async_session_factory", mock_session_factory),
        patch("asyncio.sleep", new=AsyncMock()) as mock_sleep,
    ):  # Mock sleep to avoid waiting
        try:
            await telemetry_worker()
        except asyncio.CancelledError:
            pass

        # Should have logged error and slept
        mock_sleep.assert_called_once_with(5)
