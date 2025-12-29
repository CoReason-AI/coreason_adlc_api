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
from datetime import datetime, timezone
from typing import Any, Dict
from uuid import UUID

from loguru import logger

from coreason_adlc_api.utils import get_redis_client


async def async_log_telemetry(
    user_id: UUID | None,
    auc_id: str | None,
    model_name: str,
    input_text: str,
    output_text: str,
    metadata: Dict[str, Any],
) -> None:
    """
    Push telemetry data to a Redis Queue for asynchronous processing.

    Payload Structure:
    {
        "user_uuid": str,
        "auc_id": str,
        "model_name": str,
        "request_payload": str (scrubbed),
        "response_payload": str (scrubbed),
        "cost_usd": float,
        "latency_ms": int,
        "timestamp": str (ISO 8601)
    }
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

        client = get_redis_client()
        # RPUSH adds to the tail of the list
        client.rpush("telemetry_queue", json.dumps(payload))

    except Exception as e:
        # Fire-and-forget: we verify this in tests, but in prod we log and continue
        # to ensure the user response isn't blocked by telemetry failures.
        logger.error(f"Failed to log telemetry: {e}")
