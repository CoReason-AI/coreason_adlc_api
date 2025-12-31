# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

import logging
import os
import uuid
from typing import Any, Dict

from coreason_adlc_api.db import async_session_factory, close_db, init_db
from coreason_adlc_api.db_models import TelemetryLog

logger = logging.getLogger(__name__)


async def store_telemetry(ctx: Dict[str, Any], data: Dict[str, Any]) -> None:
    """
    ARQ job to store telemetry data in PostgreSQL.
    """
    logger.info(f"Processing telemetry for user {data.get('user_uuid')}")

    # We must create a new session here because this runs in a separate worker process/loop
    async with async_session_factory() as session:
        try:
            log_entry = TelemetryLog(
                user_uuid=uuid.UUID(data["user_uuid"]),
                auc_id=data["auc_id"],
                model_name=data["model_name"],
                request_payload=data["request_payload"],
                response_payload=data["response_payload"],
                cost_usd=float(data["cost_usd"]),
                latency_ms=float(data["latency_ms"]),
                # timestamp is auto-filled or passed? if passed, parse it.
                # Assuming data['timestamp'] is ISO string if present
            )
            # data.get("timestamp") parsing if needed, else default is Now.

            session.add(log_entry)
            await session.commit()
            logger.info("Telemetry stored successfully.")
        except Exception as e:
            logger.error(f"Failed to store telemetry: {e}")
            await session.rollback()
            # ARQ will retry if we raise, or we can suppress if we want to drop bad data.
            # Generally better to log and drop if it's a data error, retry if DB is down.
            # For now, let's just log.


async def startup(ctx: Dict[str, Any]) -> None:
    await init_db()
    logger.info("Telemetry worker started.")


async def shutdown(ctx: Dict[str, Any]) -> None:
    await close_db()
    logger.info("Telemetry worker stopped.")


class WorkerSettings:
    functions = [store_telemetry]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = {
        "host": os.getenv("REDIS_HOST", "localhost"),
        "port": int(os.getenv("REDIS_PORT", "6379")),
    }
