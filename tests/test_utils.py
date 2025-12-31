# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

from unittest import mock

import httpx
import redis.asyncio as redis

from coreason_adlc_api.utils import get_http_client, get_redis_client


def test_get_http_client_real() -> None:
    """Verify that the real get_http_client function returns an AsyncClient."""
    client = get_http_client()
    assert isinstance(client, httpx.AsyncClient)


def test_get_redis_client_real_pool_creation() -> None:
    """
    Test that get_redis_client initializes the pool if None.
    We mock redis.ConnectionPool to avoid actual network calls.
    """
    # Reset the global pool for the test
    import coreason_adlc_api.utils

    coreason_adlc_api.utils._redis_pool = None

    with mock.patch("redis.asyncio.ConnectionPool") as mock_pool_cls:
        mock_pool = mock.MagicMock()
        mock_pool_cls.from_url.return_value = mock_pool

        # First call: should create pool
        client1 = get_redis_client()
        assert isinstance(client1, redis.Redis)
        mock_pool_cls.from_url.assert_called_once()

        # Second call: should reuse pool (assert_called_once should remain true, count=1)
        client2 = get_redis_client()
        assert isinstance(client2, redis.Redis)
        assert mock_pool_cls.from_url.call_count == 1
