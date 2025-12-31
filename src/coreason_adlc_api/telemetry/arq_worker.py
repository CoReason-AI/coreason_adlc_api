# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from arq import create_pool
from arq.connections import RedisSettings
from loguru import logger
from sqlmodel.ext.asyncio.session import AsyncSession

from coreason_adlc_api.config import settings
from coreason_adlc_api.db import async_session_factory
from coreason_adlc_api.db_models import TelemetryLog


async def store_telemetry(ctx: Dict[str, Any], data: Dict[str, Any]) -> None:
    """
    ARQ Job: Stores telemetry data into the database.
    """
    try:
        # Convert user_uuid string to UUID object if present
        user_uuid_str = data.get("user_uuid")
        user_uuid = UUID(user_uuid_str) if user_uuid_str else None

        log_entry = TelemetryLog(
            user_uuid=user_uuid,
            auc_id=data.get("auc_id"),
            model_name=data.get("model_name"),
            request_payload=data.get("request_payload"),
            response_payload=data.get("response_payload"),
            cost_usd=data.get("cost_usd"),
            latency_ms=data.get("latency_ms"),
            timestamp=datetime.fromisoformat(data["timestamp"]) if data.get("timestamp") else datetime.utcnow(),
        )

        async with async_session_factory() as session:
            session.add(log_entry)
            await session.commit()

    except Exception as e:
        logger.error(f"Failed to store telemetry log: {e}")
        # ARQ handles retries based on Worker settings
        raise


async def startup(ctx: Dict[str, Any]) -> None:
    logger.info("ARQ Worker started.")


async def shutdown(ctx: Dict[str, Any]) -> None:
    logger.info("ARQ Worker shutting down.")


# ARQ Worker Settings
class WorkerSettings:
    functions = [store_telemetry]
    redis_settings = RedisSettings(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        password=settings.REDIS_PASSWORD,
        database=settings.REDIS_DB,
    )
    on_startup = startup
    on_shutdown = shutdown
    # ARQ Built-in Retry Settings
    max_tries = 3
    retry_delay = 5  # seconds
