# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from loguru import logger

from coreason_adlc_api.config import settings
from coreason_adlc_api.db import close_db, init_db
from coreason_adlc_api.routers import auth, interceptor, system, vault, workbench


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    FastAPI Lifespan event handler.
    Handles startup and shutdown events.
    """
    logger.info(f"Starting Coreason ADLC API in {settings.APP_ENV} mode...")

    # Initialize Database
    await init_db()

    # Placeholder for Vault Initialization
    # Placeholder for Enterprise License Check

    yield

    logger.info("Shutting down Coreason ADLC API...")
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
    app.include_router(interceptor.router, prefix="/api/v1")
    app.include_router(system.router, prefix="/api/v1")

    return app


# Expose the app instance for Uvicorn
app = create_app()
