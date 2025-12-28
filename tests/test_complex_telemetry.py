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
from typing import Generator
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
import redis
from coreason_adlc_api.middleware.telemetry import async_log_telemetry
from coreason_adlc_api.telemetry.worker import telemetry_worker
from loguru import logger


class LogCapture:
    def __init__(self) -> None:
        self.logs: list[str] = []

    def write(self, message: str) -> None:
        self.logs.append(str(message))

    def __contains__(self, text: str) -> bool:
        return any(text in log for log in self.logs)

    def __repr__(self) -> str:
        return "\n".join(self.logs)


@pytest.fixture
def capture_logs() -> Generator[LogCapture, None, None]:
    capture = LogCapture()
    handler_id = logger.add(capture.write, format="{message}")
    yield capture
    logger.remove(handler_id)


@pytest.mark.asyncio
async def test_telemetry_producer_redis_failure(capture_logs: LogCapture) -> None:
    """
    Verify that async_log_telemetry handles Redis connection errors gracefully
    (logs error, does not raise exception to caller).
    """
    mock_client = MagicMock()
    mock_client.rpush.side_effect = redis.ConnectionError("Redis is down")

    with patch("coreason_adlc_api.middleware.telemetry.get_redis_client", return_value=mock_client):
        await async_log_telemetry(
            user_id=uuid4(),
            auc_id="test-auc",
            model_name="gpt-4",
            input_text="hello",
            output_text="world",
            metadata={"cost_usd": 0.01, "latency_ms": 100},
        )

    assert "Failed to log telemetry: Redis is down" in capture_logs


@pytest.mark.asyncio
async def test_telemetry_worker_malformed_and_empty_data(capture_logs: LogCapture) -> None:
    """
    Verify that telemetry_worker drops malformed JSON data, handles empty reads,
    and continues processing valid items without crashing.
    """
    # Mock Redis Client
    mock_client = MagicMock()
    valid_payload = {
        "user_uuid": str(uuid4()),
        "auc_id": "test-auc",
        "model_name": "gpt-4",
        "request_payload": "hello",
        "response_payload": "world",
        "cost_usd": 0.01,
        "latency_ms": 100,
        "timestamp": "2023-01-01T00:00:00Z",
    }

    # Side effects to cover all branches:
    # 1. None (Timeout) -> Matches `if not result: continue`
    # 2. (key, None/Empty) -> Matches `if not data: continue` (Simulated by empty string or None)
    # 3. Malformed JSON -> Matches `except Exception` inside loop
    # 4. Valid JSON -> Success path
    # 5. CancelledError -> Stop worker

    mock_client.blpop.side_effect = [
        None,  # Case 1: Timeout
        ("telemetry_queue", ""),  # Case 2: Empty data
        ("telemetry_queue", "{bad_json"),  # Case 3: Malformed
        ("telemetry_queue", json.dumps(valid_payload)),  # Case 4: Valid
        asyncio.CancelledError(),  # Case 5: Stop
    ]

    # Mock DB Pool
    mock_pool = MagicMock()
    mock_pool.execute = MagicMock()

    async def async_execute(*args: object, **kwargs: object) -> None:
        pass

    mock_pool.execute.side_effect = async_execute

    with (
        patch("coreason_adlc_api.telemetry.worker.get_redis_client", return_value=mock_client),
        patch("coreason_adlc_api.telemetry.worker.get_pool", return_value=mock_pool),
    ):
        await telemetry_worker()

    # Assertions
    # 1. Should log error for malformed data
    assert (
        "Failed to process telemetry log: Expecting property name enclosed in double quotes" in capture_logs
        or "Failed to process telemetry log" in capture_logs
    )

    # 2. Should have called DB execute exactly once (for the valid payload)
    assert mock_pool.execute.call_count == 1
    args = mock_pool.execute.call_args[0]
    # args[0] is query, args[1] is user_uuid, args[2] is auc_id, args[3] is model_name
    assert args[2] == "test-auc"


@pytest.mark.asyncio
async def test_telemetry_worker_redis_down(capture_logs: LogCapture) -> None:
    """
    Verify that telemetry_worker handles Redis connection errors with backoff
    and does not crash.
    """
    mock_client = MagicMock()
    # Side effects:
    # 1. Redis Connection Error
    # 2. Stop worker (CancelledError)
    mock_client.blpop.side_effect = [
        redis.ConnectionError("Redis unreachable"),
        asyncio.CancelledError(),
    ]

    mock_pool = MagicMock()

    with (
        patch("coreason_adlc_api.telemetry.worker.get_redis_client", return_value=mock_client),
        patch("coreason_adlc_api.telemetry.worker.get_pool", return_value=mock_pool),
        patch("asyncio.sleep", new_callable=MagicMock) as mock_sleep,
    ):

        async def async_sleep_side_effect(*args: object, **kwargs: object) -> None:
            pass

        mock_sleep.side_effect = async_sleep_side_effect

        await telemetry_worker()

        # Assertions
        assert "Telemetry Worker error: Redis unreachable" in capture_logs
        # Verify backoff sleep was called
        mock_sleep.assert_called_with(5)
