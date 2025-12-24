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
import uvicorn
from loguru import logger
from coreason_adlc_api.config import settings


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
        reload=settings.DEBUG
    )


def main() -> None:
    """
    Main entry point for console scripts.
    Parses arguments (simple implementation for now).
    """
    if len(sys.argv) > 1 and sys.argv[1] == "start":
        start()
    else:
        print("Usage: coreason-api start")
        sys.exit(1)


if __name__ == "__main__": # pragma: no cover
    main()
