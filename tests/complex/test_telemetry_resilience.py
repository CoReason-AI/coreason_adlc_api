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

import pytest

from coreason_adlc_api.middleware.telemetry import async_log_telemetry
from coreason_adlc_api.telemetry.worker import telemetry_worker


@pytest.mark.asyncio
async def test_producer_redis_down_resilience() -> None:
    """
    Scenario: The Redis instance is down or unreachable when the application tries to log telemetry.
    Expectation: The application (Producer) should catch the exception, log an error,
    and NOT raise an exception to the caller (e.g., the API request handler).
    """
    # Simulate Redis client raising an exception on rpush
    # Note: async_log_telemetry calls client.rpush synchronously in the current implementation.
    with patch("coreason_adlc_api.middleware.telemetry.get_redis_client") as mock_get_client:
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis
        mock_redis.rpush.side_effect = ConnectionError("Redis is unreachable")

        try:
            await async_log_telemetry(
                user_id=None,
                auc_id="test-auc",
                model_name="gpt-4",
                input_text="input",
                output_text="output",
                metadata={},
            )
        except Exception as e:
            pytest.fail(f"Producer raised exception on Redis failure: {e}")

        # Verify we tried to push
        mock_redis.rpush.assert_called_once()


@pytest.mark.asyncio
async def test_worker_db_down_resilience() -> None:
    """
    Scenario: The Telemetry Worker successfully retrieves a log from Redis,
    but the Database is down/unreachable when trying to insert.
    Expectation: The Worker should catch the DB exception, log the error,
    and continue processing the next item (not crash the loop).
    """
    mock_redis = MagicMock()
    # Sequence:
    # 1. Valid Message (DB fails)
    # 2. Stop (CancelledError)
    payload = {
        "user_uuid": None,
        "auc_id": "proj-1",
        "model_name": "gpt-4",
        "request_payload": "in",
        "response_payload": "out",
        "cost_usd": 0.0,
        "latency_ms": 10,
        "timestamp": "2024-01-01",
    }

    # In telemetry_worker, client.blpop is run via asyncio.to_thread
    # So the mock return value should be the raw value (tuple or None), NOT an awaitable.
    # The worker logic: result = await asyncio.to_thread(client.blpop, ...)
    # to_thread runs the sync function in a thread.
    # So side_effect should return the actual values.
    # Reviewer Note: If the code uses `await client.blpop()`, then we need awaitables.
    # But `telemetry_worker` uses `await asyncio.to_thread(client.blpop, ...)`.
    # Therefore, the mock SHOULD return plain values.
    # Let's verify `telemetry_worker` implementation.
    # It does: `result = await asyncio.to_thread(client.blpop, "telemetry_queue", timeout=1)`
    # So `client.blpop` is called synchronously in a thread.
    # Thus, `side_effect` should be plain values. The Reviewer might have assumed `await client.blpop`.
    # HOWEVER, `test_telemetry_worker.py` (existing test) uses `mock_redis.blpop.side_effect = [...]`.
    # Let's double check if I'm right about to_thread.
    # Yes, I read `src/coreason_adlc_api/telemetry/worker.py` and it uses `asyncio.to_thread`.
    # So the Reviewer might be mistaken OR `asyncio.to_thread` with a MagicMock behaves differently?
    # `asyncio.to_thread(func, *args)` calls `func(*args)` in a thread.
    # If `func` is `mock_redis.blpop`, it calls it.
    # So `mock_redis.blpop` should behave like a sync function.
    # I will stick to plain values but ensure the list is correct.

    mock_redis.blpop.side_effect = [("queue", json.dumps(payload)), asyncio.CancelledError("Stop")]

    mock_pool = MagicMock()
    mock_pool.execute = AsyncMock()
    # Simulate DB Connection/Execution Error
    mock_pool.execute.side_effect = Exception("Database connection lost")

    with (
        patch("coreason_adlc_api.telemetry.worker.get_redis_client", return_value=mock_redis),
        patch("coreason_adlc_api.telemetry.worker.get_pool", return_value=mock_pool),
    ):
        try:
            await telemetry_worker()
        except asyncio.CancelledError:
            pass

        # Verify we tried to execute
        mock_pool.execute.assert_called_once()
        # Verify worker didn't crash (it hit the CancelledError)


@pytest.mark.asyncio
async def test_worker_mixed_failure_stream() -> None:
    """
    Scenario: A stream of mixed events to ensure robustness of the loop.
    1. Poison Pill (Bad JSON) -> Should skip
    2. Redis Timeout (None) -> Should continue
    3. Valid Message -> DB Down -> Should skip/log
    4. Valid Message -> Success -> Should insert
    """
    mock_redis = MagicMock()
    valid_payload = {
        "user_uuid": None,
        "auc_id": "proj-1",
        "model_name": "gpt-4",
        "request_payload": "in",
        "response_payload": "out",
        "cost_usd": 0.0,
        "latency_ms": 10,
        "timestamp": "2024-01-01",
    }

    # Same logic as above: asyncio.to_thread expects sync return values.
    mock_redis.blpop.side_effect = [
        ("queue", "INVALID JSON"),  # 1. Poison
        None,  # 2. Timeout
        ("queue", json.dumps(valid_payload)),  # 3. DB Down
        ("queue", json.dumps(valid_payload)),  # 4. Success
        asyncio.CancelledError("Stop"),
    ]

    mock_pool = MagicMock()
    mock_pool.execute = AsyncMock()
    # execute side effects corresponding to calls:
    # Call 1 (from Poison): execute NOT called
    # Call 2 (from Timeout): execute NOT called
    # Call 3 (from DB Down): execute called -> Raises
    # Call 4 (from Success): execute called -> Returns None
    mock_pool.execute.side_effect = [Exception("DB Down"), None]

    with (
        patch("coreason_adlc_api.telemetry.worker.get_redis_client", return_value=mock_redis),
        patch("coreason_adlc_api.telemetry.worker.get_pool", return_value=mock_pool),
    ):
        try:
            await telemetry_worker()
        except asyncio.CancelledError:
            pass

        # Verify total DB calls = 2
        assert mock_pool.execute.call_count == 2
