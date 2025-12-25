# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

import os
from unittest import mock

from coreason_adlc_api.config import Settings


def test_settings_defaults() -> None:
    """Test default values for new settings."""
    # We instantiate a new Settings object to avoid global state from import
    settings = Settings()

    assert settings.REDIS_HOST == "localhost"
    assert settings.REDIS_PORT == 6379
    assert settings.REDIS_DB == 0
    assert settings.REDIS_PASSWORD is None
    assert settings.DAILY_BUDGET_LIMIT == 50.0

def test_settings_env_override() -> None:
    """Test that environment variables override defaults."""
    env_vars = {
        "REDIS_HOST": "redis-prod",
        "REDIS_PORT": "1234",
        "REDIS_DB": "5",
        "REDIS_PASSWORD": "secret-pass",
        "DAILY_BUDGET_LIMIT": "100.5",
    }

    with mock.patch.dict(os.environ, env_vars):
        settings = Settings()

        assert settings.REDIS_HOST == "redis-prod"
        assert settings.REDIS_PORT == 1234
        assert settings.REDIS_DB == 5
        assert settings.REDIS_PASSWORD == "secret-pass"
        assert settings.DAILY_BUDGET_LIMIT == 100.5
