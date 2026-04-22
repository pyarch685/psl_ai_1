"""
Main entry point for PSL Soccer Predictor application.

Loads environment variables, validates configuration, starts the scheduler,
and runs the FastAPI server with production-safe defaults.
"""
from __future__ import annotations

import os
import signal
import sys
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

from app.api import app
from config.settings import validate_environment
from jobs.scheduler import shutdown_scheduler, start_scheduler

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"

if ENV_PATH.exists():
    load_dotenv(ENV_PATH)


def _shutdown_handler(signum: int, frame: object) -> None:
    """Handle process shutdown and stop the background scheduler."""
    print(f"[main] Received signal {signum}, shutting down gracefully...")
    try:
        shutdown_scheduler()
    except Exception as exc:  # pragma: no cover - defensive shutdown path
        print(f"[main] Error stopping scheduler: {exc}")
    sys.exit(0)


signal.signal(signal.SIGINT, _shutdown_handler)
signal.signal(signal.SIGTERM, _shutdown_handler)


if __name__ == "__main__":
    try:
        validate_environment()
        print("[main] Environment validation passed")
    except RuntimeError as exc:
        print(f"[main] Environment validation failed: {exc}")
        if os.getenv("ENVIRONMENT", "").lower() == "production":
            sys.exit(1)
        print("[main] Continuing in development mode...")

    try:
        start_scheduler()
        print("[main] Background scheduler started")
    except Exception as exc:
        print(f"[main] Warning: Failed to start scheduler: {exc}")
        print("[main] Continuing without scheduler...")

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    print(f"[main] Starting API on {host}:{port}")
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
        access_log=True,
        workers=1,
    )
