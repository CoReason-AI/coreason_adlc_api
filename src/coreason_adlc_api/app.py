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
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from loguru import logger

from coreason_adlc_api.config import settings
from coreason_adlc_api.db import close_db, init_db
from coreason_adlc_api.routers import auth, interceptor, models, system, vault, workbench
from coreason_adlc_api.telemetry.worker import telemetry_worker
from coreason_adlc_api.utils import get_redis_client
from coreason_veritas.auditor import IERLogger
import json


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    FastAPI Lifespan event handler.
    Handles startup and shutdown events.
    """
    logger.info(f"Starting Coreason ADLC API in {settings.APP_ENV} mode...")

    # Initialize Database
    await init_db()

    # Wire up Audit Sink
    def sink_callback(event: dict) -> None:
        """
        Adapts IERLogger event to Telemetry Worker schema and pushes to Redis.
        """
        attributes = event.get("attributes", {})
        payload = {
            "user_uuid": str(attributes.get("co.user_id", "")),
            "auc_id": str(attributes.get("co.asset_id", "")),
            "model_name": event.get("span_name", "unknown"),
            "request_payload": attributes.get("co.request", {}), # Best effort mapping
            "response_payload": attributes.get("co.response", {}), # Best effort mapping
            "cost_usd": 0.0, # Default, as governance might not track cost directly yet
            "latency_ms": 0, # Default
            "timestamp": event.get("timestamp"),
        }

        # Safe push
        try:
            get_redis_client().rpush("telemetry_queue", json.dumps(payload))
        except Exception as e:
            logger.error(f"Failed to push audit log to telemetry queue: {e}")

    IERLogger().register_sink(sink_callback)

    # Start Telemetry Worker
    telemetry_task = asyncio.create_task(telemetry_worker())

    # Enterprise License Check (BC-03)
    if settings.ENTERPRISE_LICENSE_KEY:
        logger.info("Enterprise Mode Enabled. SSO and Remote Features Active.")
    else:
        logger.info("Community Mode Enabled. Features restricted to local storage.")

    yield

    logger.info("Shutting down Coreason ADLC API...")

    # Stop Telemetry Worker
    telemetry_task.cancel()
    try:
        await telemetry_task
    except asyncio.CancelledError:
        logger.info("Telemetry Worker stopped.")

    await close_db()


def create_app() -> FastAPI:
    """
    Factory function to create the FastAPI application.
    """
    app = FastAPI(
        title="Coreason ADLC API",
        description="Secure ADLC Middleware",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.DEBUG else None,
        redoc_url="/redoc" if settings.DEBUG else None,
    )

    @app.get("/health")
    async def health_check() -> dict[str, str]:
        """
        Basic health check endpoint.
        """
        return {"status": "ok", "env": settings.APP_ENV}

    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(vault.router, prefix="/api/v1")
    app.include_router(workbench.router, prefix="/api/v1")
    app.include_router(models.router, prefix="/api/v1")
    app.include_router(interceptor.router, prefix="/api/v1")
    app.include_router(system.router, prefix="/api/v1")

    return app


# Expose the app instance for Uvicorn
app = create_app()
