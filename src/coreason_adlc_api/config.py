# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application Configuration based on Pydantic Settings.
    Reads from environment variables.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=True, extra="ignore")

    # Core
    APP_ENV: str = "development"
    DEBUG: bool = False
    PORT: int = 8000
    HOST: str = "0.0.0.0"

    # Security
    # 32-byte hex string (64 chars). Default provided for dev/test only.
    # In prod, this MUST be overridden.
    ENCRYPTION_KEY: str = "0000000000000000000000000000000000000000000000000000000000000000"

    # Database
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "coreason_db"

    # Redis (Telemetry & Budget)
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    # Optional password if needed
    REDIS_PASSWORD: str | None = None

    # Governance
    DAILY_BUDGET_LIMIT: float = 50.0  # Dollars
    ENTERPRISE_LICENSE_KEY: str | None = None

    # Auth (OIDC)
    OIDC_DOMAIN: str = "https://example.auth0.com"  # e.g. dev-xyz.us.auth0.com
    OIDC_CLIENT_ID: str = "your-client-id"
    OIDC_CLIENT_SECRET: str = "your-client-secret"
    OIDC_AUDIENCE: str = "https://api.coreason.ai"

    # Logging
    LOG_LEVEL: str = "INFO"


# Global Settings Instance
settings = Settings()
