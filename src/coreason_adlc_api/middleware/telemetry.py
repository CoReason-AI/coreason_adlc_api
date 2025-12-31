# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

from datetime import datetime, timezone
from typing import Any, Dict
from uuid import UUID

from arq import create_pool
from arq.connections import RedisSettings
from loguru import logger

from coreason_adlc_api.config import settings

# Global ARQ Pool
_arq_pool = None


async def get_arq_pool():
    global _arq_pool
    if _arq_pool is None:
        _arq_pool = await create_pool(
            RedisSettings(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                password=settings.REDIS_PASSWORD,
                database=settings.REDIS_DB,
            )
        )
    return _arq_pool


class TelemetryService:
    """
    Service for logging telemetry data asynchronously using ARQ.
    """

    async def async_log_telemetry(
        self,
        user_id: UUID | None,
        auc_id: str | None,
        model_name: str,
        input_text: str,
        output_text: str,
        metadata: Dict[str, Any],
    ) -> None:
        """
        Push telemetry data to ARQ for asynchronous processing.
        """
        try:
            payload = {
                "user_uuid": str(user_id) if user_id else None,
                "auc_id": auc_id,
                "model_name": model_name,
                "request_payload": input_text,
                "response_payload": output_text,
                "cost_usd": metadata.get("cost_usd", 0.0),
                "latency_ms": metadata.get("latency_ms", 0),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            arq = await get_arq_pool()
            await arq.enqueue_job("store_telemetry", data=payload)

        except Exception as e:
            logger.error(f"Failed to log telemetry: {e}")


# Legacy Wrapper
_service = TelemetryService()


async def async_log_telemetry(
    user_id: UUID | None,
    auc_id: str | None,
    model_name: str,
    input_text: str,
    output_text: str,
    metadata: Dict[str, Any],
) -> None:
    await _service.async_log_telemetry(user_id, auc_id, model_name, input_text, output_text, metadata)
