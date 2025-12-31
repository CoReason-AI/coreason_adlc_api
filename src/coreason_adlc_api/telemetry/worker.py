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
from uuid import UUID

from loguru import logger

from coreason_adlc_api.db import get_pool
from coreason_adlc_api.utils import get_redis_client


async def telemetry_worker() -> None:
    """
    Background task that consumes telemetry logs from Redis and writes them to PostgreSQL.
    Run this as an asyncio Task.
    """
    logger.info("Telemetry Worker started.")
    client = get_redis_client()
    pool = get_pool()

    while True:
        try:
            # BLPOP blocks until an item is available
            # Returns (key, element) tuple. Timeout=0 means block indefinitely.
            # In asyncio, we use the async client's blpop which yields control.

            # Using a short timeout (1s) to allow loop cancellation checks cleanly if needed,
            # though asyncio.CancelledError handles task cancellation points too.
            result = await client.blpop("telemetry_queue", timeout=1)

            if not result:
                continue

            _, data = result  # result is (key, data)

            if not data:
                continue

            try:
                payload = json.loads(data)

                # Insert into DB
                query = """
                    INSERT INTO telemetry.telemetry_logs (
                        user_uuid, auc_id, model_name,
                        request_payload, response_payload,
                        cost_usd, latency_ms, timestamp
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """

                # Handle UUID conversion if needed
                user_uuid = UUID(payload["user_uuid"]) if payload.get("user_uuid") else None

                await pool.execute(
                    query,
                    user_uuid,
                    payload.get("auc_id"),
                    payload.get("model_name"),
                    json.dumps(payload.get("request_payload")),  # Store as JSONB
                    json.dumps(payload.get("response_payload")),  # Store as JSONB
                    payload.get("cost_usd"),
                    payload.get("latency_ms"),
                    payload.get("timestamp"),  # Postgres should handle ISO format string for TIMESTAMP
                )

            except Exception as e:
                logger.error(f"Failed to process telemetry log: {e}. Data: {data}")
                # We do not push back to queue to avoid infinite loops on bad data (Poison Message)

        except asyncio.CancelledError:
            logger.info("Telemetry Worker cancelled.")
            break
        except Exception as e:
            logger.error(f"Telemetry Worker error: {e}")
            await asyncio.sleep(5)  # Backoff on connection errors
