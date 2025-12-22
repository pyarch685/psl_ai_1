"""
Main entry point for PSL Soccer Predictor application.

Loads environment variables, starts the background scheduler,
and runs the FastAPI server.
"""
from pathlib import Path

from dotenv import load_dotenv
import uvicorn

from app.api import app
from jobs.scheduler import start_scheduler

# --------------------------------------------------
# Load environment variables FIRST
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"

load_dotenv(ENV_PATH)

# --------------------------------------------------
# Start app components
# --------------------------------------------------

if __name__ == "__main__":
    start_scheduler()
    uvicorn.run(app, host="localhost", port=8000)
