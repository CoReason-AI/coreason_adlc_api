# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

import sys
import asyncio

import uvicorn
from loguru import logger
from arq import run_worker

from coreason_adlc_api.config import settings
from coreason_adlc_api.telemetry.arq_worker import WorkerSettings


def start() -> None:
    """
    Entry point for the CLI command `coreason-api start`.
    Runs the Uvicorn server.
    """
    logger.info(f"Initializing server on {settings.HOST}:{settings.PORT}")
    uvicorn.run(
        "coreason_adlc_api.app:app",
        host=settings.HOST,
        port=settings.PORT,
        log_level=settings.LOG_LEVEL.lower(),
        reload=settings.DEBUG,
    )


def worker() -> None:
    """
    Entry point for the CLI command `coreason-api worker`.
    Runs the ARQ worker.
    """
    logger.info("Initializing ARQ Worker...")
    asyncio.run(run_worker(WorkerSettings))


def main() -> None:
    """
    Main entry point for console scripts.
    Parses arguments.
    """
    if len(sys.argv) > 1:
        if sys.argv[1] == "start":
            start()
        elif sys.argv[1] == "worker":
            worker()
        else:
            print("Usage: coreason-api [start|worker]")
            sys.exit(1)
    else:
        print("Usage: coreason-api [start|worker]")
        sys.exit(1)


if __name__ == "__main__":  # pragma: no cover
    main()
