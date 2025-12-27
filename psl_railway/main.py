"""
Main entry point for PSL Soccer Predictor application.

Loads environment variables, validates configuration, starts the background scheduler,
and runs the FastAPI server with production-ready settings.
"""
import os
import signal
import sys
from pathlib import Path

from dotenv import load_dotenv
import uvicorn

from app.api import app
from jobs.scheduler import start_scheduler

# Load environment variables FIRST
BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"

# Load .env file if it exists (for local development)
# In Railway, environment variables are set directly
if ENV_PATH.exists():
    load_dotenv(ENV_PATH)

# Validate environment configuration
try:
    from config.settings import validate_environment
    validate_environment()
    print("[main] Environment validation passed")
except RuntimeError as e:
    print(f"[main] Environment validation failed: {e}")
    if os.getenv("ENVIRONMENT", "").lower() == "production":
        sys.exit(1)
    print("[main] Continuing in development mode...")

# Graceful shutdown handler
def shutdown_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    print(f"[main] Received signal {signum}, shutting down gracefully...")
    # Stop scheduler
    try:
        from jobs.scheduler import stop_scheduler
        stop_scheduler()
    except Exception as e:
        print(f"[main] Error stopping scheduler: {e}")
    sys.exit(0)

# Register signal handlers for graceful shutdown
signal.signal(signal.SIGINT, shutdown_handler)
signal.signal(signal.SIGTERM, shutdown_handler)

if __name__ == "__main__":
    # Get port from environment (Railway sets PORT)
    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "0.0.0.0")  # Bind to all interfaces in production
    
    print(f"[main] Starting PSL Soccer Predictor API on {host}:{port}")
    
    # Start background scheduler
    try:
        start_scheduler()
        print("[main] Background scheduler started")
    except Exception as e:
        print(f"[main] Warning: Failed to start scheduler: {e}")
        print("[main] Continuing without scheduler...")
    
    # Run FastAPI server
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
        access_log=True,
        # Production settings
        workers=1,  # Railway handles scaling, use single worker
        loop="uvloop",  # Use uvloop for better performance
    )

