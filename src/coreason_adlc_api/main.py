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

import typer
import uvicorn

from coreason_adlc_api.telemetry.arq_worker import WorkerSettings

app_typer = typer.Typer()


@app_typer.command()
def start(
    host: str = typer.Option("0.0.0.0", help="Host to bind to"),
    port: int = typer.Option(8000, help="Port to bind to"),
    reload: bool = typer.Option(False, help="Enable auto-reload"),
    workers: int = typer.Option(1, help="Number of worker processes"),
) -> None:
    """
    Start the Coreason ADLC API server.
    """
    uvicorn.run(
        "coreason_adlc_api.app:app",
        host=host,
        port=port,
        reload=reload,
        workers=workers,
        log_level="info",
    )


@app_typer.command()
def worker() -> None:
    """
    Start the ARQ telemetry worker.
    """
    from arq import run_worker

    asyncio.run(run_worker(WorkerSettings))  # type: ignore


def main() -> None:
    app_typer()


if __name__ == "__main__":
    main()
