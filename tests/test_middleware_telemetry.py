# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

import json
import uuid
from unittest import mock

import pytest

from coreason_adlc_api.middleware.telemetry import async_log_telemetry


@pytest.fixture
def mock_redis():
    with mock.patch("coreason_adlc_api.middleware.telemetry.get_redis_client") as mock_get_client:
        client = mock.MagicMock()
        mock_get_client.return_value = client
        yield client


@pytest.mark.asyncio
async def test_log_telemetry_success(mock_redis):
    """Test successful pushing of telemetry."""
    user_id = uuid.uuid4()
    auc_id = "proj-123"
    model = "gpt-4"
    inp = "hello"
    out = "world"
    meta = {"cost_usd": 0.01, "latency_ms": 100}

    await async_log_telemetry(user_id, auc_id, model, inp, out, meta)

    mock_redis.rpush.assert_called_once()
    args = mock_redis.rpush.call_args[0]
    assert args[0] == "telemetry_queue"

    payload = json.loads(args[1])
    assert payload["user_uuid"] == str(user_id)
    assert payload["auc_id"] == auc_id
    assert payload["cost_usd"] == 0.01
    assert payload["latency_ms"] == 100
    assert payload["request_payload"] == inp


@pytest.mark.asyncio
async def test_log_telemetry_exception_handling(mock_redis):
    """Test that exceptions are caught and logged (fire-and-forget)."""
    mock_redis.rpush.side_effect = Exception("Redis down")

    # Should not raise exception
    await async_log_telemetry(None, None, "m", "i", "o", {})

    mock_redis.rpush.assert_called_once()
