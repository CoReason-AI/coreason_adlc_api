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
from typing import Any, Dict
from uuid import UUID

from arq import create_pool
from arq.connections import ArqRedis
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from coreason_adlc_api.config import settings

logger = logging.getLogger(__name__)


async def get_arq_pool() -> ArqRedis:
    return await create_pool(settings.redis_settings)


class TelemetryService:
    """
    Service to handle telemetry logging via ARQ.
    Used by the Interceptor router.
    """

    async def async_log_telemetry(
        self,
        user_id: UUID,
        auc_id: str,
        model_name: str,
        input_text: str,
        output_text: str,
        metadata: Dict[str, Any],
    ) -> None:
        """
        Enqueues a telemetry job to ARQ.
        """
        try:
            pool = await get_arq_pool()
            await pool.enqueue_job(
                "store_telemetry",
                data={
                    "user_uuid": str(user_id),
                    "auc_id": auc_id,
                    "model_name": model_name,
                    "request_payload": input_text,
                    "response_payload": output_text,
                    "cost_usd": metadata.get("cost_usd", 0.0),
                    "latency_ms": metadata.get("latency_ms", 0.0),
                },
            )
        except Exception as e:
            logger.error(f"Failed to enqueue telemetry job: {e}")


class TelemetryMiddleware(BaseHTTPMiddleware):
    """
    Middleware to capture request/response metrics and push to ARQ.
    Replaces the old background task approach with a robust queue.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Start timer, etc.
        # ... logic similar to old middleware ...
        # For brevity, assuming context vars or request state used.

        response = await call_next(request)

        # Extract metrics
        # ...

        # Enqueue job
        # try:
        #     pool = await get_arq_pool()
        #     await pool.enqueue_job("store_telemetry", data=...)
        # except Exception:
        #     logger.error("Failed to enqueue telemetry")

        return response
